"""Safe outbound HTTP for URLs that come from outside (image proxy, article pages).

Blocks server-side request forgery (SSRF): every hop must be http(s) on the normal ports,
and the host must resolve only to public internet addresses (no loopback, private,
link-local/cloud-metadata, reserved or multicast ranges). Redirects are followed by hand
so each new location is checked too, and bodies are size-capped."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

REDIRECTS = {301, 302, 303, 307, 308}


class Blocked(Exception):
    """The URL points somewhere the server must not fetch."""


def ip_is_public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a.is_global and not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast
                                or a.is_reserved or a.is_unspecified)


async def check_url(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise Blocked("only http(s) URLs")
    if p.username or p.password:
        raise Blocked("no credentials in URLs")
    port = p.port or (443 if p.scheme == "https" else 80)
    if port not in (80, 443):
        raise Blocked("only standard ports")
    host = p.hostname.lower().rstrip(".")
    try:                                     # a literal IP address
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        if "." not in host or host.endswith((".internal", ".local", ".localhost", ".lan", ".home", ".corp")) or host == "localhost":
            raise Blocked("internal host name")
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            raise Blocked("host does not resolve")
        addrs = [i[4][0] for i in infos]
    if not addrs or not all(ip_is_public(a) for a in addrs):
        raise Blocked("host resolves to a non-public address")


async def safe_get(client: httpx.AsyncClient, url: str, *, headers: dict | None = None, timeout: float = 10,
                   max_bytes: int = 5_000_000, max_redirects: int = 3, stop_marker: bytes | None = None):
    """GET with SSRF checks on every hop. Returns (status, headers, body_bytes).
    Raises Blocked for forbidden targets and httpx errors for network failures."""
    for _ in range(max_redirects + 1):
        await check_url(url)
        async with client.stream("GET", url, headers=headers, timeout=timeout, follow_redirects=False) as r:
            if r.status_code in REDIRECTS and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            declared = int(r.headers.get("content-length") or 0)
            if declared > max_bytes:
                raise Blocked("too large")
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if stop_marker and stop_marker in buf:
                    break
                if len(buf) > max_bytes:
                    if stop_marker:
                        break
                    raise Blocked("too large")
            return r.status_code, r.headers, bytes(buf)
    raise Blocked("too many redirects")
