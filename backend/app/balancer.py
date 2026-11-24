"""Multi-model load balancer for Groq.

Every (API key, model) pair is a *lane*. Groq limits requests per organisation per model,
so each lane has its own budget. All lane state lives in Redis, so any number of worker
processes on any number of machines share one consistent view:

  lane:<id>:rpm:<minute>  requests sent this minute (atomic, via Lua)
  lane:<id>:cool          exists while the lane is cooling down after a 429 / outage
  lane:<id>:inflight      requests currently running on the lane
  lane:<id>:ok / :fail    rolling health counters

Pick order: the lane with the best  weight × spare-capacity ÷ (1 + in-flight),
skipping lanes that are cooling or out of budget. On failure the call moves to the next lane.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass

import httpx
import redis.asyncio as aioredis

from .config import ModelSpec, settings

log = logging.getLogger("balancer")

ACQUIRE = """
if redis.call('EXISTS', KEYS[2]) == 1 then return -1 end
local n = tonumber(redis.call('GET', KEYS[1]) or '0')
if n >= tonumber(ARGV[1]) then return 0 end
redis.call('INCR', KEYS[1]); redis.call('EXPIRE', KEYS[1], 70)
return 1
"""


class NoCapacity(Exception):
    pass


class LLMError(Exception):
    pass


@dataclass
class Lane:
    key: str
    spec: ModelSpec

    @property
    def id(self) -> str:
        return hashlib.sha1(f"{self.key}|{self.spec.model}".encode()).hexdigest()[:10]

    def k(self, suffix: str) -> str:
        return f"lane:{self.id}:{suffix}"


class Balancer:
    def __init__(self, redis: aioredis.Redis, lanes: list[Lane] | None = None, http: httpx.AsyncClient | None = None):
        self.r = redis
        self.lanes = lanes if lanes is not None else [Lane(k, m) for k in settings.groq_keys for m in settings.models]
        self.http = http or httpx.AsyncClient(timeout=60)
        self._acquire = self.r.register_script(ACQUIRE)

    # ---------- discovery ----------
    async def discover(self) -> None:
        """Drop configured models that Groq no longer serves (models get retired often)."""
        if settings.llm_mock:
            return
        live: set[str] = set()
        for key in {l.key for l in self.lanes}:
            try:
                r = await self.http.get(f"{settings.groq_base}/models", headers={"Authorization": f"Bearer {key}"})
                r.raise_for_status()
                live |= {m["id"] for m in r.json().get("data", [])}
            except Exception as e:  # keep the configured list if discovery fails
                log.warning("model discovery failed: %s", e)
                return
        keep = [l for l in self.lanes if l.spec.model in live]
        dropped = {l.spec.model for l in self.lanes} - {l.spec.model for l in keep}
        if dropped:
            log.warning("models not available on Groq, skipped: %s", ", ".join(sorted(dropped)))
        if keep:
            self.lanes = keep

    # ---------- selection ----------
    async def _snapshot(self) -> list[tuple[float, Lane]]:
        minute = int(time.time() // 60)
        pipe = self.r.pipeline()
        for l in self.lanes:
            pipe.get(l.k(f"rpm:{minute}"))
            pipe.exists(l.k("cool"))
            pipe.get(l.k("inflight"))
            pipe.get(l.k("ok"))
            pipe.get(l.k("fail"))
        vals = await pipe.execute()
        ranked = []
        for i, l in enumerate(self.lanes):
            used, cool, infl, ok, fail = vals[i * 5:(i + 1) * 5]
            if cool:
                continue
            used = int(used or 0)
            spare = 1 - used / max(1, l.spec.rpm)
            if spare <= 0:
                continue
            ok, fail = int(ok or 0), int(fail or 0)
            health = (ok + 1) / (ok + fail + 1)
            score = l.spec.weight * spare * health / (1 + int(infl or 0))
            ranked.append((score, l))
        ranked.sort(key=lambda x: -x[0])
        return ranked

    async def _take(self, exclude: set[str]) -> Lane:
        minute = int(time.time() // 60)
        for _, lane in await self._snapshot():
            if lane.id in exclude:
                continue
            got = await self._acquire(keys=[lane.k(f"rpm:{minute}"), lane.k("cool")], args=[lane.spec.rpm])
            if got == 1:
                return lane
        raise NoCapacity()

    async def _cool(self, lane: Lane, seconds: float) -> None:
        await self.r.set(lane.k("cool"), "1", ex=max(1, int(seconds)))

    async def _health(self, lane: Lane, ok: bool) -> None:
        key = lane.k("ok" if ok else "fail")
        await self.r.incr(key)
        await self.r.expire(key, 600)

    async def status(self) -> list[dict]:
        minute = int(time.time() // 60)
        out = []
        for l in self.lanes:
            used, cool, infl, ok, fail = await asyncio.gather(
                self.r.get(l.k(f"rpm:{minute}")), self.r.ttl(l.k("cool")), self.r.get(l.k("inflight")),
                self.r.get(l.k("ok")), self.r.get(l.k("fail")))
            out.append({"lane": l.id, "model": l.spec.model, "rpm_used": int(used or 0), "rpm_limit": l.spec.rpm,
                        "cooling_s": max(0, cool or 0), "inflight": int(infl or 0),
                        "ok_10m": int(ok or 0), "fail_10m": int(fail or 0)})
        return out

    # ---------- the call ----------
    async def chat_json(self, messages: list[dict], max_attempts: int = 5, wait_budget: float = 90) -> tuple[dict, str]:
        """Return (parsed JSON, model used). Waits for capacity up to wait_budget seconds."""
        tried: set[str] = set()
        deadline = time.time() + wait_budget
        last_err: Exception | None = None
        attempts = 0
        while attempts < max_attempts:
            try:
                lane = await self._take(tried)
            except NoCapacity:
                if len(tried) >= len(self.lanes):
                    tried.clear()          # every lane tried once; allow retries on recovered lanes
                if time.time() > deadline:
                    raise LLMError(f"no model capacity (last error: {last_err})")
                await asyncio.sleep(1.5)
                continue
            attempts += 1
            tried.add(lane.id)
            await self.r.incr(lane.k("inflight"))
            try:
                data = await self._call(lane, messages)
                await self._health(lane, True)
                return data, lane.spec.model
            except LLMError as e:
                last_err = e
                await self._health(lane, False)
                log.warning("lane %s (%s) failed: %s", lane.id, lane.spec.model, e)
            finally:
                await self.r.decr(lane.k("inflight"))
        raise LLMError(f"all attempts failed: {last_err}")

    async def _call(self, lane: Lane, messages: list[dict]) -> dict:
        if settings.llm_mock:
            from .mock import mock_llm_answer
            await asyncio.sleep(0.2)
            return parse_json(mock_llm_answer(lane.spec.model))
        body = {"model": lane.spec.model, "messages": messages, "temperature": 0.6,
                "max_tokens": 3200, "response_format": {"type": "json_object"}}
        for _ in range(2):
            try:
                r = await self.http.post(f"{settings.groq_base}/chat/completions", json=body,
                                         headers={"Authorization": f"Bearer {lane.key}"})
            except httpx.HTTPError as e:
                await self._cool(lane, 10)
                raise LLMError(f"network: {e}")
            if r.status_code == 400 and "response_format" in body:
                body.pop("response_format")      # some models reject JSON mode; retry in plain mode
                continue
            break
        if r.status_code == 429:
            await self._cool(lane, float(r.headers.get("retry-after", "20") or 20))
            raise LLMError("rate limited")
        if r.status_code in (404, 410):
            await self._cool(lane, 3600)          # model retired
            raise LLMError(f"model gone: {r.status_code}")
        if r.status_code >= 500:
            await self._cool(lane, 15)
            raise LLMError(f"server {r.status_code}")
        if r.status_code >= 400:
            raise LLMError(f"http {r.status_code}: {r.text[:200]}")
        if r.headers.get("x-ratelimit-remaining-requests") == "0":
            await self._cool(lane, 30)
        try:
            return parse_json(r.json()["choices"][0]["message"]["content"])
        except Exception as e:
            raise LLMError(f"bad output: {e}")


def parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))
