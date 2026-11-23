"""Public API.  Run several copies behind nginx:  uvicorn app.main:app --workers 4"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import news
from .balancer import Balancer
from .config import settings
from .store import feed, get_json, redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.r = redis_client()
    app.state.q = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    app.state.bal = Balancer(app.state.r)
    yield
    await app.state.q.aclose()
    await app.state.bal.http.aclose()
    await app.state.r.aclose()


app = FastAPI(title="NewsDecoder API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


@app.middleware("http")
async def per_client_limit(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "?")
        key = f"rl:{ip}:{int(time.time() // 60)}"
        r = request.app.state.r
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 70)
        if n > settings.client_rpm:
            return JSONResponse({"detail": "Too many requests, slow down"}, status_code=429)
    return await call_next(request)


@app.get("/api/categories")
async def categories():
    return [{"id": k, "label": v["label"]} for k, v in news.CATEGORIES.items()]


@app.get("/api/feed/{category}")
async def get_feed(category: str, request: Request):
    if category not in news.CATEGORIES:
        raise HTTPException(404, "unknown category")
    stories, at = await feed(request.app.state.r, category)
    return {"category": category, "updated": at, "stories": stories}


@app.get("/api/decode/{story_id}")
async def decode(story_id: str, request: Request):
    """Returns the decoded story if ready; otherwise queues it (once, however many readers ask)
    and returns the current status. The app polls this every ~1.5 s."""
    r = request.app.state.r
    done = await get_json(r, f"explain:{story_id}")
    if done:
        return {"status": "ready", "result": done}
    if not await r.exists(f"story:{story_id}"):
        raise HTTPException(404, "story not found, refresh the feed")
    status = await r.get(f"explain:{story_id}:status")
    if status and status.startswith("error:"):
        await r.delete(f"explain:{story_id}:status")       # let the next poll retry
        return {"status": "error", "message": status[6:]}
    if not status:
        await r.set(f"explain:{story_id}:status", "queued", ex=600)
        await request.app.state.q.enqueue_job("decode_story", story_id, _job_id=f"decode:{story_id}")
        status = "queued"
    position = await r.zcard("arq:queue")
    return {"status": status, "queue": position}


@app.get("/api/health")
async def health(request: Request):
    return {"ok": True, "queue": await request.app.state.r.zcard("arq:queue"),
            "lanes": await request.app.state.bal.status()}
