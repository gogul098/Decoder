import httpx
import pytest
import respx

from app import releases
from app.config import settings

UPDATE = {"build": 42, "version": "1.0.42", "notes": "New things", "published": "2026-11-27T10:00:00Z",
          "apk_url": "https://github.com/gogul098/Decoder/releases/download/latest/news-decoded.apk"}


@pytest.fixture(autouse=True)
def fresh():
    releases._cache.update(at=0.0, assets={}, info=None)
    old = settings.github_token
    yield
    settings.github_token = old


@pytest.mark.asyncio
@respx.mock
async def test_private_repo_uses_token_and_signed_links():
    settings.github_token = "tok"
    repo = settings.github_repo
    rel = respx.get(f"https://api.github.com/repos/{repo}/releases/tags/latest").mock(
        return_value=httpx.Response(200, json={"assets": [{"name": "update.json", "id": 1}, {"name": "news-decoded.apk", "id": 2}]}))
    respx.get(f"https://api.github.com/repos/{repo}/releases/assets/1").mock(
        return_value=httpx.Response(302, headers={"location": "https://objects.githubusercontent.com/u?sig=a"}))
    respx.get(f"https://api.github.com/repos/{repo}/releases/assets/2").mock(
        return_value=httpx.Response(302, headers={"location": "https://objects.githubusercontent.com/apk?sig=b"}))
    respx.get("https://objects.githubusercontent.com/u?sig=a").mock(return_value=httpx.Response(200, json=UPDATE))
    async with httpx.AsyncClient() as c:
        info = await releases.latest(c)
        assert info["build"] == 42 and info["apk_url"] == "/api/apk?b=42"      # download goes through our server
        assert rel.calls[0].request.headers["authorization"] == "Bearer tok"
        assert await releases.apk_link(c) == "https://objects.githubusercontent.com/apk?sig=b"
        await releases.latest(c)
    assert rel.call_count == 1                                                  # cached for 5 minutes


@pytest.mark.asyncio
@respx.mock
async def test_public_repo_without_token():
    settings.github_token = ""
    respx.get(f"https://github.com/{settings.github_repo}/releases/download/latest/update.json").mock(
        return_value=httpx.Response(200, json=UPDATE))
    async with httpx.AsyncClient() as c:
        info = await releases.latest(c)
        assert info["version"] == "1.0.42" and "authorization" not in str(respx.calls[0].request.headers).lower()
        assert (await releases.apk_link(c)).endswith("/releases/download/latest/news-decoded.apk")


@pytest.mark.asyncio
@respx.mock
async def test_missing_release_is_unavailable():
    settings.github_token = "tok"
    respx.get(f"https://api.github.com/repos/{settings.github_repo}/releases/tags/latest").mock(
        return_value=httpx.Response(404))
    async with httpx.AsyncClient() as c:
        with pytest.raises(releases.Unavailable):
            await releases.latest(c)
