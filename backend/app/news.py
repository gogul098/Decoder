"""Fetch live headlines, group duplicates across outlets, rank the top 5 per category,
and look up earlier coverage ("previous news leads") for a story."""
from __future__ import annotations

import hashlib
import html
import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import feedparser
import httpx

from .config import settings

GN = "https://news.google.com/rss"


def _edition() -> str:
    r = settings.region
    return f"hl=en-{r}&gl={r}&ceid={r}:en"


def _search(q: str, window: str = "1d") -> str:
    return f"{GN}/search?q={quote_plus(q)}+when:{window}&{_edition()}"


def _topic(t: str) -> str:
    return f"{GN}/headlines/section/topic/{t}?{_edition()}"


CATEGORIES: dict[str, dict] = {
    "tech": {
        "label": "Tech & AI",
        "feeds": [_topic("TECHNOLOGY"), _search("artificial intelligence OR AI model OR chip OR startup")],
    },
    "india": {
        "label": "Indian Politics",
        "feeds": [_topic("NATION"), _search("India government OR parliament OR election OR minister")],
    },
    "world": {
        "label": "World Politics",
        "feeds": [_topic("WORLD"), _search("diplomacy OR summit OR sanctions OR president OR war")],
    },
    "markets": {
        "label": "Markets",
        "feeds": [_topic("BUSINESS"), _search("Sensex OR Nifty OR stock market OR shares OR Wall Street OR RBI rate")],
    },
    "oil": {
        "label": "Oil & Energy",
        "feeds": [_search("crude oil price OR Brent OR OPEC OR petrol diesel price OR natural gas price")],
    },
    "security": {
        "label": "Terror & Security",
        "feeds": [_search("terror attack OR terrorism OR militants OR blast OR security forces")],
    },
}

STOP = set("""a an the of to in on for and or but with at by from as is are was were be been has have had
it its this that these those after over into amid says said say new will would could can than more about
up out not no his her their they he she we you who what why how when where which while vs via
news live updates today report reports latest""".split())


def tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if len(w) > 2 and w not in STOP}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _split_source(title: str, entry) -> tuple[str, str]:
    src = getattr(entry, "source", {}) or {}
    name = src.get("title") if isinstance(src, dict) else None
    if " - " in title:
        head, tail = title.rsplit(" - ", 1)
        return head.strip(), (name or tail.strip())
    return title.strip(), (name or "Unknown")


def _ts(entry) -> float:
    for key in ("published", "updated"):
        val = entry.get(key)
        if val:
            try:
                return parsedate_to_datetime(val).timestamp()
            except Exception:
                pass
    return time.time()


def parse_feed(xml: str) -> list[dict]:
    items = []
    for e in feedparser.parse(xml).entries:
        title, source = _split_source(e.get("title", ""), e)
        if not title:
            continue
        items.append({
            "title": title,
            "source": source,
            "url": e.get("link", ""),
            "published": _ts(e),
            "summary": _clean(e.get("summary", ""))[:400],
        })
    return items


async def fetch(url: str, client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get(url, timeout=12, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 NewsDecoder/1.0"})
        r.raise_for_status()
        return parse_feed(r.text)
    except Exception:
        return []


def story_id(title: str) -> str:
    key = " ".join(sorted(tokens(title)))
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def cluster(items: list[dict], threshold: float = 0.34) -> list[list[dict]]:
    """Greedy clustering of headlines that describe the same event."""
    groups: list[tuple[set[str], list[dict]]] = []
    for it in sorted(items, key=lambda x: -x["published"]):
        tk = tokens(it["title"])
        for gtk, members in groups:
            if jaccard(tk, gtk) >= threshold:
                members.append(it)
                gtk |= tk
                break
        else:
            groups.append((set(tk), [it]))
    return [m for _, m in groups]


def rank(groups: list[list[dict]], now: float | None = None, top: int = 5) -> list[dict]:
    """Score = how many distinct outlets cover it (importance) + freshness."""
    now = now or time.time()
    scored = []
    for members in groups:
        outlets = {m["source"] for m in members}
        newest = max(m["published"] for m in members)
        age_h = max(0.0, (now - newest) / 3600)
        score = len(outlets) * 2.0 + max(0.0, 6 - age_h) * 0.5
        scored.append((score, members))
    scored.sort(key=lambda s: -s[0])
    out = []
    for score, members in scored[:top]:
        lead = max(members, key=lambda m: (len(m["title"]) if len(m["title"]) < 140 else 0, m["published"]))
        seen, sources = set(), []
        for m in sorted(members, key=lambda m: -m["published"]):
            if m["source"] not in seen:
                seen.add(m["source"])
                sources.append({"name": m["source"], "url": m["url"], "title": m["title"]})
        out.append({
            "id": story_id(lead["title"]),
            "title": lead["title"],
            "summary": next((m["summary"] for m in members if len(m["summary"]) > 60), ""),
            "published": max(m["published"] for m in members),
            "outlets": len(seen),
            "sources": sources[:8],
            "score": round(score, 2),
        })
    return out


async def top_stories(category: str) -> list[dict]:
    if settings.news_mock:
        from .mock import mock_items
        items = mock_items(category)
    else:
        async with httpx.AsyncClient() as client:
            items = []
            for url in CATEGORIES[category]["feeds"]:
                items += await fetch(url, client)
    stories = rank(cluster(items))
    for s in stories:
        s["category"] = category
    return stories


async def previous_leads(story: dict, limit: int = 10) -> list[dict]:
    """Earlier headlines on the same subject (last 30 days), oldest first.
    These are what the LLM uses to explain *why* something happened."""
    keys = sorted(tokens(story["title"]), key=len, reverse=True)[:4]
    if not keys:
        return []
    if settings.news_mock:
        from .mock import mock_leads
        items = mock_leads(story)
    else:
        async with httpx.AsyncClient() as client:
            items = await fetch(_search(" ".join(keys), "30d"), client)
    cutoff = story["published"] - 6 * 3600
    st = tokens(story["title"])
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["published"]):
        sid = story_id(it["title"])
        if it["published"] > cutoff or sid in seen or jaccard(tokens(it["title"]), st) > 0.7:
            continue
        seen.add(sid)
        out.append(it)
    return out[-limit:]
