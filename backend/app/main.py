"""Public API.  Run several copies behind nginx:  uvicorn app.main:app --workers 2

Phones can't (and shouldn't) talk to Redis directly, so the API is the bridge:
it holds ONE Redis subscription per process and fans every message out to all the
phones connected to it over Server-Sent Events (SSE). 10,000 open apps = a handful of
Redis connections, not 10,000."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import news
from .balancer import Balancer
from .config import settings
from .store import NEWS_CHANNEL, decode_channel, get_json, redis_client, snapshot

log = logging.getLogger("api")
HEARTBEAT = 15


class Broadcaster:
    """One Redis pattern-subscription per process -> many in-memory listener queues."""

    def __init__(self, redis):
        self.r = redis
        self.subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self.task: asyncio.Task | None = None

    def start(self):
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    @contextlib.contextmanager
    def listen(self, channel: str):
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self.subs[channel].add(q)
        try:
            yield q
        finally:
            self.subs[channel].discard(q)
            if not self.subs[channel]:
                self.subs.pop(channel, None)

    async def _run(self):
        delay = 1
        while True:
            try:
                ps = self.r.pubsub()
                await ps.psubscribe(NEWS_CHANNEL, "decode:*")
                delay = 1
                async for msg in ps.listen():
                    if msg["type"] != "pmessage":
                        continue
                    for q in list(self.subs.get(msg["channel"], ())):
                        if q.full():          # a stuck client must never slow the others
                            with contextlib.suppress(asyncio.QueueEmpty):
                                q.get_nowait()
                        q.put_nowait(msg["data"])
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("redis subscription dropped (%s), reconnecting", e)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.r = redis_client()
    app.state.q = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    app.state.bal = Balancer(app.state.r)
    app.state.hub = Broadcaster(app.state.r)
    app.state.hub.start()
    yield
    await app.state.hub.stop()
    await app.state.q.aclose()
    await app.state.bal.http.aclose()
    await app.state.r.aclose()


app = FastAPI(title="News Decoded API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


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


@app.get("/api/stream")
async def stream(request: Request):
    """Open once when the app starts. Sends every category's current top 5 straight from
    Redis, then pushes each update the ingester publishes. Never touches RSS."""
    r, hub = request.app.state.r, request.app.state.hub

    async def gen():
        with hub.listen(NEWS_CHANNEL) as q:
            yield "retry: 3000\n\n"
            empty = False
            for cat in news.CATEGORIES:
                snap = await snapshot(r, cat)
                empty |= not snap["stories"]
                yield sse("snapshot", snap)
            if empty:   # first boot: ask a worker to ingest now (deduplicated by job id)
                await request.app.state.q.enqueue_job("ingest_all", _job_id=f"ingest:{int(time.time() // 60)}")
                yield sse("status", {"message": "Collecting today's news…"})
            while not await request.is_disconnected():
                try:
                    data = await asyncio.wait_for(q.get(), HEARTBEAT)
                    yield f"event: update\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


async def _ensure_queued(request: Request, story_id: str) -> dict:
    """Return the current decode state, queueing the job if nobody has yet."""
    r = request.app.state.r
    done = await get_json(r, f"explain:{story_id}")
    if done:
        return {"stage": "ready", "result": done}
    if not await r.exists(f"story:{story_id}"):
        return {"stage": "error", "message": "Story not found. Pull down to refresh."}
    status = await r.get(f"explain:{story_id}:status")
    if status and status.startswith("error:"):
        await r.delete(f"explain:{story_id}:status")       # the next open retries
        return {"stage": "error", "message": status[6:]}
    if not status:
        await r.set(f"explain:{story_id}:status", "queued", ex=600)
        await request.app.state.q.enqueue_job("decode_story", story_id, _job_id=f"decode:{story_id}")
        status = "queued"
    return {"stage": status, "queue": await r.zcard("arq:queue")}


@app.get("/api/decode/{story_id}/stream")
async def decode_stream(story_id: str, request: Request):
    """Live progress of one story: queued -> finding -> writing -> ready (with the result)."""
    hub = request.app.state.hub

    async def gen():
        with hub.listen(decode_channel(story_id)) as q:      # subscribe BEFORE checking, so nothing is missed
            state = await _ensure_queued(request, story_id)
            yield sse("ready" if state["stage"] == "ready" else "error" if state["stage"] == "error" else "progress", state)
            if state["stage"] in ("ready", "error"):
                return
            deadline = time.time() + 180
            while time.time() < deadline and not await request.is_disconnected():
                try:
                    msg = json.loads(await asyncio.wait_for(q.get(), HEARTBEAT))
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                stage = msg.get("stage", "")
                if stage == "ready":
                    yield sse("ready", msg)
                    return
                if stage.startswith("error:"):
                    yield sse("error", {"stage": "error", "message": stage[6:]})
                    return
                yield sse("progress", msg)
            yield sse("error", {"stage": "error", "message": "Taking too long. Try again."})

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/api/feed/{category}")
async def get_feed(category: str, request: Request):
    """Plain JSON fallback (reads Redis only)."""
    if category not in news.CATEGORIES:
        raise HTTPException(404, "unknown category")
    return await snapshot(request.app.state.r, category)


@app.get("/api/decode/{story_id}")
async def decode(story_id: str, request: Request):
    """Plain JSON fallback for clients without SSE."""
    return await _ensure_queued(request, story_id)


@app.get("/api/health")
async def health(request: Request):
    hub = request.app.state.hub
    return {"ok": True, "queue": await request.app.state.r.zcard("arq:queue"),
            "sse_listeners": sum(len(v) for v in hub.subs.values()),
            "lanes": await request.app.state.bal.status()}
