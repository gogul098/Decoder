"""Redis layout shared by the ingester, the workers and the API.

  feed:<category>        latest top-5 for the category (JSON)        written by the ingester only
  feed:<category>:at     when it was written
  story:<id>             one story (JSON), kept 3 days
  explain:<id>           decoded story (JSON), kept 24 h
  explain:<id>:status    queued / finding / writing / error:...

Pub/sub channels
  news:updates           ingester -> {"category", "updated", "stories"} whenever a top-5 changes
  decode:<id>            worker   -> {"stage": ..., ...} progress of one story's decoding
"""
import json
import time

import redis.asyncio as aioredis

from . import news
from .config import settings

NEWS_CHANNEL = "news:updates"


def decode_channel(story_id: str) -> str:
    return f"decode:{story_id}"


def redis_client() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def get_json(r: aioredis.Redis, key: str):
    v = await r.get(key)
    return json.loads(v) if v else None


def _ist_day() -> str:
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")


def archive_key(category: str) -> str:
    return f"archive:{category}:{_ist_day()}"


def _brief(s: dict, now: float) -> dict:
    return {"id": s["id"], "title": s["title"], "published": s["published"], "outlets": s.get("outlets", 1),
            "source": (s.get("sources") or [{}])[0].get("name", ""), "category": s.get("category", ""), "archived": now}


def _seen(title: str, pool: list[dict]) -> bool:
    """Same event as anything in pool? (titles change between ingests, so compare words, not ids)"""
    tk = news.tokens(title)
    return any(p["id"] == news.story_id(title) or news.jaccard(tk, news.tokens(p["title"])) >= 0.34 for p in pool)


async def ingest(r: aioredis.Redis, category: str, rotate: bool = False) -> dict:
    """Pull RSS for one category and update its top 5.

    Stories that leave the top 5 go to today's archive (kept for the day, IST). Archived stories
    never come back into the top 5. With rotate=True (pull-to-refresh) the whole current top 5 is
    archived and replaced by the best stories not seen yet today. Only the ingester calls this,
    so opening the app never triggers RSS fetches by itself."""
    now = time.time()
    log = {"category": category, "at": now, "rotate": rotate, "feeds": []}
    if not await r.set(f"lock:ingest:{category}", "1", nx=True, ex=120):
        log["result"] = "skipped: another ingest is running"
        return log
    try:
        candidates = await news.top_stories(category, top=30, report=log["feeds"])
        log["candidates"] = len(candidates)
        old = await get_json(r, f"feed:{category}") or []
        archive = await get_json(r, archive_key(category)) or []
        pool = [c for c in candidates if not _seen(c["title"], archive)]
        if rotate:
            pool = [c for c in pool if not _seen(c["title"], old)]
        if not candidates:
            log["result"] = "no items from any feed (blocked or down); kept the old list"
            return log
        if rotate and not pool:
            log["result"] = "nothing new since the last refresh; kept the current list"
            await r.set(f"feed:{category}:at", str(now))
            return log
        new = pool[:5] if not rotate else pool[:5]
        if not rotate and len(new) < 5:          # keep current stories to fill the list when news is slow
            new += [o for o in old if not _seen(o["title"], new)][: 5 - len(new)]
        retired = old if rotate else [o for o in old if not _seen(o["title"], new)]
        archive = [_brief(o, now) for o in retired if not _seen(o["title"], archive)] + archive
        pipe = r.pipeline()
        for s in new:
            pipe.set(f"story:{s['id']}", json.dumps(s), ex=3 * 24 * 3600)
        pipe.set(f"feed:{category}", json.dumps(new))
        pipe.set(f"feed:{category}:at", str(now))
        pipe.set(archive_key(category), json.dumps(archive[:60]), ex=36 * 3600)
        await pipe.execute()
        changed = [s["id"] for s in new] != [s["id"] for s in old]
        log.update(new=[s["title"][:80] for s in new], archived=len(retired), archive_size=len(archive))
        if changed:
            receivers = await r.publish(NEWS_CHANNEL, json.dumps(
                {"category": category, "updated": now, "stories": new, "archive": archive[:60]}))
            log["result"] = f"published new top 5 to Redis ({receivers} API process(es) listening)"
        else:
            log["result"] = "same top 5 as before; nothing published"
        return log
    except Exception as e:  # noqa: BLE001
        log["result"] = f"error: {e}"
        return log
    finally:
        await r.delete(f"lock:ingest:{category}")
        await r.set(f"ingest:last:{category}", json.dumps(log), ex=7 * 24 * 3600)


async def snapshot(r: aioredis.Redis, category: str) -> dict:
    stories = await get_json(r, f"feed:{category}") or []
    archive = await get_json(r, archive_key(category)) or []
    return {"category": category, "updated": float(await r.get(f"feed:{category}:at") or 0),
            "stories": stories, "archive": archive}


async def set_status(r: aioredis.Redis, story_id: str, stage: str, ttl: int = 600, **extra) -> None:
    await r.set(f"explain2:{story_id}:status", stage, ex=ttl)
    await r.publish(decode_channel(story_id), json.dumps({"stage": stage, **extra}))
