"""App updates, served by this server so the GitHub repo can be private.

The phone asks /api/update for the newest build and downloads it from /api/apk. Both read the
"latest" GitHub release. With GITHUB_TOKEN set (a fine-grained token with read-only access to
the repo's contents) they read a private repo; without it they read the public release pages.
The APK itself is never streamed through this server: /api/apk answers with a redirect to
GitHub's short-lived signed download link.
"""
from __future__ import annotations

import json
import time

import httpx

from .config import settings

API = "https://api.github.com"
APK_NAME = "news-decoded.apk"
_cache: dict = {"at": 0.0, "assets": {}, "info": None}
CACHE_S = 300


class Unavailable(Exception):
    pass


def _gh_headers(accept: str = "application/vnd.github+json") -> dict:
    h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "decoded-api"}
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


async def _assets(client: httpx.AsyncClient) -> dict[str, int]:
    r = await client.get(f"{API}/repos/{settings.github_repo}/releases/tags/latest", headers=_gh_headers(), timeout=10)
    if r.status_code != 200:
        raise Unavailable(f"release lookup {r.status_code}")
    return {a["name"]: a["id"] for a in r.json().get("assets", [])}


async def _asset_link(client: httpx.AsyncClient, asset_id: int) -> str:
    """GitHub's signed, few-minutes-valid download link for one release file."""
    r = await client.get(f"{API}/repos/{settings.github_repo}/releases/assets/{asset_id}",
                         headers=_gh_headers("application/octet-stream"), timeout=10, follow_redirects=False)
    loc = r.headers.get("location", "")
    if r.status_code not in (301, 302, 303, 307, 308) or not loc.startswith("https://"):
        raise Unavailable(f"asset link {r.status_code}")
    return loc


async def latest(client: httpx.AsyncClient) -> dict:
    """update.json of the newest build, with apk_url pointing at this server."""
    now = time.time()
    if _cache["info"] and now - _cache["at"] < CACHE_S:
        return _cache["info"]
    if settings.github_token:
        assets = await _assets(client)
        if "update.json" not in assets:
            raise Unavailable("no update.json")
        r = await client.get(await _asset_link(client, assets["update.json"]), timeout=10)
    else:
        assets = {}
        r = await client.get(f"https://github.com/{settings.github_repo}/releases/download/latest/update.json",
                             timeout=10, follow_redirects=True)
    if r.status_code != 200:
        raise Unavailable(f"update.json {r.status_code}")
    raw = json.loads(r.content)
    info = {k: raw[k] for k in ("build", "version", "notes", "published") if k in raw}
    if not isinstance(info.get("build"), int):
        raise Unavailable("bad update.json")
    info["apk_url"] = f"/api/apk?b={info['build']}"
    _cache.update(at=now, assets=assets, info=info)
    return info


async def apk_link(client: httpx.AsyncClient) -> str:
    if not settings.github_token:
        return f"https://github.com/{settings.github_repo}/releases/download/latest/{APK_NAME}"
    assets = _cache["assets"] if time.time() - _cache["at"] < CACHE_S and _cache["assets"] else await _assets(client)
    if APK_NAME not in assets:
        raise Unavailable("no apk")
    return await _asset_link(client, assets[APK_NAME])
