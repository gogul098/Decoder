import asyncio
import socket

import fakeredis
import httpx
import pytest
import respx

from app import netsafe, store


@pytest.mark.parametrize("ip,ok", [
    ("8.8.8.8", True), ("151.101.1.140", True), ("127.0.0.1", False), ("10.1.2.3", False), ("172.16.0.5", False),
    ("192.168.1.1", False), ("169.254.169.254", False), ("100.64.0.1", False), ("0.0.0.0", False),
    ("::1", False), ("fe80::1", False), ("fc00::1", False), ("::ffff:127.0.0.1", False), ("2606:4700::1111", True),
])
def test_ip_classification(ip, ok):
    assert netsafe.ip_is_public(ip) is ok


@pytest.fixture
def fake_dns(monkeypatch):
    table = {"news.example.com": "93.184.216.34", "evil.example.com": "169.254.169.254", "rebind.example.com": "10.0.0.7"}

    async def getaddrinfo(host, port, **kw):
        if host not in table:
            raise socket.gaierror("nx")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], port))]

    loop_cls = type(asyncio.get_event_loop_policy().get_event_loop())
    monkeypatch.setattr(loop_cls, "getaddrinfo", lambda self, h, p, **kw: getaddrinfo(h, p, **kw))
    return table


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://localhost/x.jpg", "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data", "http://[::1]/",
    "http://2130706433/", "http://evil.example.com/a.jpg", "http://rebind.example.com/", "ftp://news.example.com/a",
    "http://news.example.com:6379/", "http://user:pw@news.example.com/", "http://red-abc123/", "http://svc.internal/",
])
async def test_blocked_targets(url, fake_dns):
    with pytest.raises(netsafe.Blocked):
        await netsafe.check_url(url)


@pytest.mark.asyncio
@respx.mock
async def test_redirect_to_internal_is_blocked(fake_dns):
    respx.get("https://news.example.com/r").mock(return_value=httpx.Response(302, headers={"location": "http://169.254.169.254/latest"}))
    async with httpx.AsyncClient() as c:
        with pytest.raises(netsafe.Blocked):
            await netsafe.safe_get(c, "https://news.example.com/r")


@pytest.mark.asyncio
@respx.mock
async def test_public_redirect_and_size_cap(fake_dns):
    respx.get("https://news.example.com/a").mock(return_value=httpx.Response(301, headers={"location": "/b.jpg"}))
    respx.get("https://news.example.com/b.jpg").mock(return_value=httpx.Response(200, content=b"x" * 100, headers={"content-type": "image/jpeg"}))
    respx.get("https://news.example.com/huge.jpg").mock(return_value=httpx.Response(200, content=b"x" * 2000))
    async with httpx.AsyncClient() as c:
        status, h, body = await netsafe.safe_get(c, "https://news.example.com/a")
        assert status == 200 and body == b"x" * 100
        with pytest.raises(netsafe.Blocked):
            await netsafe.safe_get(c, "https://news.example.com/huge.jpg", max_bytes=1000)


@pytest.mark.asyncio
async def test_only_server_attached_images_are_proxyable():
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    await store.allow_images(r, [{"image": "https://cdn.example.com/p.jpg"}, {"image": ""}])
    assert await store.image_allowed(r, "https://cdn.example.com/p.jpg")
    assert not await store.image_allowed(r, "http://169.254.169.254/")


def _req(headers, host="10.0.0.5"):
    from starlette.requests import Request
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                    "client": (host, 1234)})


def test_client_ip_cannot_be_spoofed():
    from app.main import client_ip
    # Render: Cloudflare's header wins over anything the caller wrote
    assert client_ip(_req({"True-Client-IP": "49.36.1.2", "X-Forwarded-For": "1.1.1.1"})) == "49.36.1.2"
    # caller-written entries on the left are ignored; Render's private hops on the right are skipped
    assert client_ip(_req({"X-Forwarded-For": "8.8.8.8, 49.36.1.2, 10.1.45.23"})) == "49.36.1.2"
    assert client_ip(_req({"X-Forwarded-For": "8.8.8.8, 49.36.1.2"})) == "49.36.1.2"
    # junk is never used as an identity
    assert client_ip(_req({"True-Client-IP": "not-an-ip", "X-Forwarded-For": "zzz"})) == "10.0.0.5"
    assert client_ip(_req({})) == "10.0.0.5"
