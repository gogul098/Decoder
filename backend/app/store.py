"""Small Redis helpers shared by the API and the workers."""
import json
import time

import redis.asyncio as aioredis

from . import news
from .config import settings


def redis_client() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def get_json(r: aioredis.Redis, key: str):
    v = await r.get(key)
    return json.loads(v) if v else None


async def refresh_feed(r: aioredis.Redis, category: str) -> list[dict]:
    """Rebuild a category's top 5 (one process at a time, thanks to a short lock)."""
    lock = await r.set(f"lock:feed:{category}", "1", nx=True, ex=60)
    if not lock:
        for _ in range(30):                       # someone else is building it; wait for them
            cached = await get_json(r, f"feed:{category}")
            if cached is not None:
                return cached
            await _sleep(0.5)
    try:
        stories = await news.top_stories(category)
        if not stories:                            # keep serving the old list if the fetch failed
            return await get_json(r, f"feed:{category}") or []
        pipe = r.pipeline()
        for s in stories:
            pipe.set(f"story:{s['id']}", json.dumps(s), ex=3 * 24 * 3600)
        pipe.set(f"feed:{category}", json.dumps(stories), ex=settings.feed_ttl * 4)
        pipe.set(f"feed:{category}:at", str(time.time()))
        await pipe.execute()
        return stories
    finally:
        await r.delete(f"lock:feed:{category}")


async def feed(r: aioredis.Redis, category: str) -> tuple[list[dict], float]:
    cached = await get_json(r, f"feed:{category}")
    at = float(await r.get(f"feed:{category}:at") or 0)
    if cached is None or time.time() - at > settings.feed_ttl:
        cached = await refresh_feed(r, category)
        at = float(await r.get(f"feed:{category}:at") or time.time())
    return cached, at


async def _sleep(s: float):
    import asyncio
    await asyncio.sleep(s)
