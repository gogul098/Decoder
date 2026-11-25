"""Queue workers (arq). Run as many copies as you like:  arq app.worker.WorkerSettings

Two kinds of work:
  * ingest_all (cron, every FEED_TTL): RSS -> rank -> Redis -> publish on news:updates
  * decode_story (queued on demand): previous news leads -> Groq (via the balancer) -> Redis,
    publishing progress on decode:<id> so the app sees it live.
The cron runs on every worker, but a Redis lock lets only one of them ingest each category."""
from __future__ import annotations

import json
import logging

from arq import cron, func
from arq.connections import RedisSettings

from . import news
from .balancer import Balancer
from .config import settings
from .explain import build_messages, validate
from .langs import norm, story_key
from .store import decode_channel, get_json, ingest, redis_client, set_status

log = logging.getLogger("worker")


async def startup(ctx):
    ctx["r"] = redis_client()
    ctx["bal"] = Balancer(ctx["r"])
    await ctx["bal"].discover()
    log.info("worker ready with %d model lanes", len(ctx["bal"].lanes))


async def shutdown(ctx):
    await ctx["bal"].http.aclose()
    await ctx["r"].aclose()


async def decode_story(ctx, story_id: str, lang: str = "en") -> str:
    r = ctx["r"]
    lang = norm(lang)
    sk = story_key(story_id, lang)                  # one cache entry per story per language
    done = await r.get(f"explain2:{sk}")
    if done:
        await r.publish(decode_channel(sk), json.dumps({"stage": "ready", "result": json.loads(done)}))
        return "cached"
    story = await get_json(r, f"story:{story_id}")
    if not story:
        await set_status(r, sk, "error:This story has expired. Pull down to refresh.", ttl=60)
        return "missing"
    try:
        await set_status(r, sk, "finding")
        leads = await news.previous_leads(story)
        await set_status(r, sk, "writing", leads=len(leads))
        raw, model = await ctx["bal"].chat_json(build_messages(story, leads, lang), min_weight=3 if lang != "en" else 0)
        result = validate(raw)
    except Exception as e:  # noqa: BLE001 — any failure becomes a readable status
        log.exception("decode failed for %s", sk)
        await set_status(r, sk, f"error:{str(e)[:160]}", ttl=60)
        return "error"
    result.update({"id": story_id, "lang": lang, "model": model, "story": story,
                   "leads": [{k: l[k] for k in ("title", "source", "url", "published")} for l in leads]})
    await r.set(f"explain2:{sk}", json.dumps(result), ex=settings.explain_ttl)
    await r.delete(f"explain2:{sk}:status")
    await r.publish(decode_channel(sk), json.dumps({"stage": "ready", "result": result}))
    return "ok"


async def ingest_all(ctx):
    for cat in news.CATEGORIES:
        await ingest(ctx["r"], cat)
        if settings.prewarm:
            for s in await get_json(ctx["r"], f"feed:{cat}") or []:
                await ctx["redis"].enqueue_job("decode_story", s["id"], _job_id=f"decode:{s['id']}")


async def refresh_category(ctx, category: str):
    """Pull-to-refresh: archive the current top 5 and bring in the next unseen stories."""
    return (await ingest(ctx["r"], category, rotate=True)).get("result")


class WorkerSettings:
    functions = [func(decode_story, keep_result=0, timeout=180, max_tries=2),
                 func(ingest_all, keep_result=0, timeout=300),
                 func(refresh_category, keep_result=0, timeout=120)]
    cron_jobs = [cron(ingest_all, minute=set(range(0, 60, max(1, settings.feed_ttl // 60))),
                      run_at_startup=True, unique=True)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.worker_concurrency
