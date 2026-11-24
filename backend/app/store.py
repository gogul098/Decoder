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


async def ingest(r: aioredis.Redis, category: str) -> list[dict]:
    """Pull RSS for one category, rank the top 5, store it and publish it to subscribers.
    Only the ingester calls this, so phones opening the app never trigger RSS fetches."""
    if not await r.set(f"lock:ingest:{category}", "1", nx=True, ex=120):
        return await get_json(r, f"feed:{category}") or []
    try:
        stories = await news.top_stories(category)
        if not stories:                      # feed down: keep serving what we had
            return await get_json(r, f"feed:{category}") or []
        now = time.time()
        old_ids = [s["id"] for s in (await get_json(r, f"feed:{category}") or [])]
        pipe = r.pipeline()
        for s in stories:
            pipe.set(f"story:{s['id']}", json.dumps(s), ex=3 * 24 * 3600)
        pipe.set(f"feed:{category}", json.dumps(stories))
        pipe.set(f"feed:{category}:at", str(now))
        await pipe.execute()
        if [s["id"] for s in stories] != old_ids:
            await r.publish(NEWS_CHANNEL, json.dumps({"category": category, "updated": now, "stories": stories}))
        return stories
    finally:
        await r.delete(f"lock:ingest:{category}")


async def snapshot(r: aioredis.Redis, category: str) -> dict:
    stories = await get_json(r, f"feed:{category}") or []
    return {"category": category, "updated": float(await r.get(f"feed:{category}:at") or 0), "stories": stories}


async def set_status(r: aioredis.Redis, story_id: str, stage: str, ttl: int = 600, **extra) -> None:
    await r.set(f"explain2:{story_id}:status", stage, ex=ttl)
    await r.publish(decode_channel(story_id), json.dumps({"stage": stage, **extra}))
