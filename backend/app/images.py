"""Find a photo for stories whose RSS item had none.

Most top stories come from Google News, whose RSS has no images. For those we open the
original article and read its share image (og:image / twitter:image), the same picture
the site shows when the link is shared. Google News links are first resolved to the real
article address. Results are cached in Redis so each article is looked up once."""
from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import re

import httpx

from .news import UA

log = logging.getLogger("images")

META = re.compile(
    r"""<meta\s+[^>]*?(?:property|name)\s*=\s*["'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["'][^>]*?content\s*=\s*["']([^"']+)["']"""
    r"""|<meta\s+[^>]*?content\s*=\s*["']([^"']+)["'][^>]*?(?:property|name)\s*=\s*["'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["']""",
    re.I)


def _is_google(url: str) -> bool:
    return "news.google.com" in url


async def _resolve_google(url: str) -> str:
    try:
        from googlenewsdecoder import gnews_decoder_async
        res = await gnews_decoder_async(url, timeout=8)
        return res.get("decoded_url", "") if res.get("success") else ""
    except Exception as e:  # noqa: BLE001
        log.info("google link not resolved: %s", e)
        return ""


async def _og_image(url: str, client: httpx.AsyncClient) -> str:
    try:
        async with client.stream("GET", url, timeout=8, follow_redirects=True, headers={"User-Agent": UA}) as r:
            if r.status_code >= 400:
                return ""
            buf = b""
            async for chunk in r.aiter_bytes():
                buf += chunk
                if b"</head>" in buf or len(buf) > 600_000:
                    break
        m = META.search(buf.decode("utf-8", "ignore"))
        if not m:
            return ""
        img = html.unescape(m.group(1) or m.group(2)).strip()
        if img.startswith("//"):
            img = "https:" + img
        return img if img.startswith(("http://", "https://")) else ""
    except Exception:  # noqa: BLE001
        return ""


async def _find(story: dict, r, client: httpx.AsyncClient) -> None:
    sources = story.get("sources") or []
    # publisher links first (no extra lookup), then Google News links resolved to the article
    ordered = [s for s in sources if not _is_google(s.get("url", ""))] + [s for s in sources if _is_google(s.get("url", ""))]
    for src in ordered[:3]:
        url = src.get("url", "")
        if not url:
            continue
        key = "img:" + hashlib.sha1(url.encode()).hexdigest()[:16]
        cached = await r.get(key)
        if cached is not None:
            img = cached
        else:
            target = await _resolve_google(url) if _is_google(url) else url
            img = await _og_image(target, client) if target else ""
            await r.set(key, img, ex=3 * 24 * 3600 if img else 6 * 3600)
        if img:
            story["image"] = img.replace("http://", "https://", 1)
            story["image_credit"] = src.get("name", "")
            return


async def add_missing_images(stories: list[dict], r) -> int:
    """Fill story['image'] where missing. Returns how many were found."""
    todo = [s for s in stories if not s.get("image")]
    if not todo:
        return 0
    async with httpx.AsyncClient() as client:
        try:
            await asyncio.wait_for(asyncio.gather(*[_find(s, r, client) for s in todo]), timeout=40)
        except asyncio.TimeoutError:
            pass
    return sum(1 for s in todo if s.get("image"))
