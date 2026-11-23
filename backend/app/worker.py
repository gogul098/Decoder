"""Queue workers (arq). Run as many copies as you like:  arq app.worker.WorkerSettings
Each copy handles WORKER_CONCURRENCY jobs at once; all copies share the Redis queue and
the Redis-backed model balancer, so adding workers never overshoots Groq's limits."""
from __future__ import annotations

import json
import logging

from arq import cron, func
from arq.connections import RedisSettings

from . import news
from .balancer import Balancer, LLMError
from .config import settings
from .explain import build_messages, validate
from .store import get_json, redis_client, refresh_feed

log = logging.getLogger("worker")


async def startup(ctx):
    ctx["r"] = redis_client()
    ctx["bal"] = Balancer(ctx["r"])
    await ctx["bal"].discover()
    log.info("worker ready with %d lanes", len(ctx["bal"].lanes))


async def shutdown(ctx):
    await ctx["bal"].http.aclose()
    await ctx["r"].aclose()


async def decode_story(ctx, story_id: str) -> str:
    r = ctx["r"]
    if await r.exists(f"explain:{story_id}"):
        return "cached"
    story = await get_json(r, f"story:{story_id}")
    if not story:
        await r.set(f"explain:{story_id}:status", "error:story expired, pull to refresh", ex=600)
        return "missing"
    await r.set(f"explain:{story_id}:status", "decoding", ex=600)
    try:
        leads = await news.previous_leads(story)
        raw, model = await ctx["bal"].chat_json(build_messages(story, leads))
        result = validate(raw)
    except (LLMError, Exception) as e:  # noqa: BLE001 — any failure becomes a readable status
        log.exception("decode failed for %s", story_id)
        await r.set(f"explain:{story_id}:status", f"error:{str(e)[:160]}", ex=120)
        return "error"
    result.update({"id": story_id, "model": model, "story": story,
                   "leads": [{k: l[k] for k in ("title", "source", "url", "published")} for l in leads]})
    await r.set(f"explain:{story_id}", json.dumps(result), ex=settings.explain_ttl)
    await r.delete(f"explain:{story_id}:status")
    return "ok"


async def refresh_all(ctx):
    for cat in news.CATEGORIES:
        stories = await refresh_feed(ctx["r"], cat)
        if settings.prewarm:
            for s in stories:
                await ctx["redis"].enqueue_job("decode_story", s["id"], _job_id=f"decode:{s['id']}")


class WorkerSettings:
    functions = [func(decode_story, keep_result=0, timeout=180, max_tries=2)]
    cron_jobs = [cron(refresh_all, minute=set(range(0, 60, max(1, settings.feed_ttl // 60))), run_at_startup=True)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = settings.worker_concurrency
