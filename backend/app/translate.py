"""Headline translation for the list, the archive, the widget and alerts. One model call
translates a whole batch; each result is cached per story and language for 3 days."""
from __future__ import annotations

import json

from .balancer import Balancer
from .config import settings
from .langs import LANGS


async def titles(r, bal: Balancer, lang: str, items: list[dict]) -> dict[str, str]:
    """items: [{"id", "title"}] -> {id: translated title}. Falls back to the original on failure."""
    if lang == "en" or not items:
        return {i["id"]: i["title"] for i in items}
    out: dict[str, str] = {}
    keys = [f"tr:{lang}:{i['id']}" for i in items]
    cached = await r.mget(keys) if keys else []
    todo = []
    for item, hit in zip(items, cached):
        if hit:
            out[item["id"]] = hit
        else:
            todo.append(item)
    import time as _t
    day = _t.strftime("%Y%m%d", _t.gmtime())
    for start in range(0, len(todo), 20):
        batch = todo[start:start + 20]
        n = await r.incr(f"cap:tr:{day}")
        await r.expire(f"cap:tr:{day}", 90000)
        if n > settings.translate_daily_cap:           # daily guard: show English instead of spending more
            out.update({i["id"]: i["title"] for i in batch})
            continue
        try:
            if settings.llm_mock:
                got = {i["id"]: f"[{lang}] {i['title']}" for i in batch}
            else:
                name, native = LANGS[lang]
                msgs = [
                    {"role": "system", "content":
                        f"Translate news headlines into {name} ({native}) in its own script, the way an Indian "
                        f"newspaper in {name} would write them: natural, short, accurate. Keep names and numbers "
                        f"correct. Return JSON: {{\"t\": {{\"<id>\": \"<translated headline>\"}}}} with every id."},
                    {"role": "user", "content": json.dumps({i["id"]: i["title"] for i in batch}, ensure_ascii=False)},
                ]
                data, _ = await bal.chat_json(msgs, wait_budget=25, min_weight=2)
                got = {k: str(v).strip() for k, v in (data.get("t") or data).items() if isinstance(v, str) and v.strip()}
        except Exception:  # noqa: BLE001 — show English rather than nothing
            got = {}
        pipe = r.pipeline()
        for i in batch:
            t = got.get(i["id"])
            if t:
                out[i["id"]] = t
                pipe.set(f"tr:{lang}:{i['id']}", t, ex=3 * 24 * 3600)
            else:
                out[i["id"]] = i["title"]
        await pipe.execute()
    return out
