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
        "feeds": [_topic("TECHNOLOGY"), _search("artificial intelligence OR AI model OR chip OR startup"),
                  "https://feeds.bbci.co.uk/news/technology/rss.xml", "https://techcrunch.com/feed/",
                  "https://www.theverge.com/rss/index.xml", "https://www.thehindu.com/sci-tech/technology/feeder/default.rss"],
    },
    "india": {
        "label": "Indian Politics",
        "feeds": [_topic("NATION"), _search("India government OR parliament OR election OR minister"),
                  "https://www.thehindu.com/news/national/feeder/default.rss", "https://indianexpress.com/section/political-pulse/feed/",
                  "https://feeds.feedburner.com/ndtvnews-india-news"],
    },
    "world": {
        "label": "World Politics",
        "feeds": [_topic("WORLD"), _search("diplomacy OR summit OR sanctions OR president OR war"),
                  "https://feeds.bbci.co.uk/news/world/rss.xml", "https://www.thehindu.com/news/international/feeder/default.rss",
                  "https://www.aljazeera.com/xml/rss/all.xml"],
    },
    "markets": {
        "label": "Markets",
        "feeds": [_topic("BUSINESS"), _search("Sensex OR Nifty OR stock market OR shares OR Wall Street OR RBI rate"),
                  "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "https://www.livemint.com/rss/markets",
                  "https://feeds.bbci.co.uk/news/business/rss.xml"],
    },
    "oil": {
        "label": "Oil & Energy",
        "feeds": [_search("crude oil price OR Brent OR OPEC OR petrol diesel price OR natural gas price"),
                  "https://oilprice.com/rss/main", "https://economictimes.indiatimes.com/industry/energy/oil-gas/rssfeeds/13358350.cms"],
    },
    "security": {
        "label": "Terror & Security",
        "feeds": [_search("terror attack OR terrorism OR militants OR blast OR security forces"),
                  _search("encounter militants OR IED OR NIA OR counter-terror")],
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


def _image(e) -> str:
    """Thumbnail the publisher put in the feed (media:thumbnail / media:content / enclosure / <img>)."""
    for key in ("media_thumbnail", "media_content"):
        for m in e.get(key) or []:
            url = m.get("url", "")
            if url and (key == "media_thumbnail" or m.get("medium") == "image" or "image" in m.get("type", "")
                        or re.search(r"\.(jpe?g|png|webp)(\?|$)", url, re.I)):
                return url
    for l in e.get("links") or []:
        if l.get("rel") == "enclosure" and "image" in l.get("type", ""):
            return l.get("href", "")
    m = re.search(r'<img[^>]+src="([^"]+)"', e.get("summary", "") or "")
    if m and not m.group(1).startswith("data:") and "pixel" not in m.group(1):
        return html.unescape(m.group(1))
    return ""


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
            "image": _image(e),
        })
    return items


UA = ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Mobile Safari/537.36 NewsDecoder/1.1")


async def fetch(url: str, client: httpx.AsyncClient, report: list | None = None) -> list[dict]:
    """Fetch one RSS feed. If `report` is given, append what happened (for /api/debug)."""
    from urllib.parse import urlparse
    host = urlparse(url).netloc + (urlparse(url).path[:40] if "google" not in url else "/" + url.split("/rss/")[-1][:40])
    try:
        r = await client.get(url, timeout=12, follow_redirects=True, headers={"User-Agent": UA})
        if r.status_code >= 400:
            if report is not None:
                report.append({"feed": host, "status": r.status_code, "items": 0})
            return []
        items = parse_feed(r.text)
        if report is not None:
            report.append({"feed": host, "status": r.status_code, "items": len(items)})
        return items
    except Exception as e:  # noqa: BLE001
        if report is not None:
            report.append({"feed": host, "status": "error", "error": str(e)[:120], "items": 0})
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
        score = len(outlets) * 2.0 + max(0.0, 12 - age_h) * 0.6   # coverage + a strong push for fresh news
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
            **_pick_image(lead, members),
        })
    return out


def _pick_image(lead: dict, members: list[dict]) -> dict:
    """Prefer the lead headline's photo, else any outlet's; keep who it came from for the credit."""
    for m in [lead] + members:
        if m.get("image", "").startswith(("http://", "https://")) or (settings.news_mock and m.get("image", "").startswith("data:")):
            return {"image": m["image"].replace("http://", "https://", 1), "image_credit": m["source"]}
    return {"image": "", "image_credit": ""}


async def top_stories(category: str, top: int = 5, report: list | None = None) -> list[dict]:
    """Ranked stories for a category, best first. Items older than 36 h are dropped."""
    if settings.news_mock:
        from .mock import mock_items
        items = mock_items(category)
    else:
        import asyncio
        async with httpx.AsyncClient() as client:
            results = await asyncio.gather(*[fetch(u, client, report) for u in CATEGORIES[category]["feeds"]])
        items = [it for res in results for it in res]
    cutoff = time.time() - 36 * 3600
    items = [it for it in items if it["published"] >= cutoff]
    stories = rank(cluster(items), top=top)
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
