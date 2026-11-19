"""Check whether a URL cited in a document still resolves — without becoming an SSRF proxy.

Rules: http/https only, default ports only, no credentials in the URL, and every hop
(including redirects) must resolve exclusively to public addresses. Private, loopback,
link-local, multicast and reserved ranges are refused before any connection is made.
Only headers and at most 64 KiB of body are read.

Behind an outbound HTTP(S) proxy (``HTTPS_PROXY``), name resolution happens at the proxy, so
address checks are the proxy's egress policy; literal IPs and internal names are still refused
here. A lookup that fails for any reason other than "name does not exist" is reported as
"could not check", never as a broken link.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.request import getproxies, proxy_bypass

import httpx

from app.adapters.scholarly import USER_AGENT

MAX_REDIRECTS = 4
TIMEOUT = httpx.Timeout(10.0, connect=6.0)


@dataclass
class UrlResult:
    url: str
    ok: bool
    status: int | None
    final_url: str
    reason: str = ""
    checked: bool = True  # False: we could not tell either way


class UnsafeUrl(Exception):
    pass


class CannotCheck(Exception):
    pass


def _via_proxy(scheme: str, host: str) -> bool:
    return bool(getproxies().get(scheme)) and not proxy_bypass(host)


def _public(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved or a.is_unspecified)


async def assert_safe(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeUrl("Only http and https links are checked.")
    if parts.username or parts.password:
        raise UnsafeUrl("Links with embedded credentials are not checked.")
    if parts.port not in (None, 80, 443):
        raise UnsafeUrl("Links to non-standard ports are not checked.")
    host = parts.hostname or ""
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise UnsafeUrl("Links to local or internal hosts are not checked.")
    try:
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        if _via_proxy(parts.scheme, host):
            return
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            if exc.errno == socket.EAI_NONAME:
                raise UnsafeUrl("The host name does not exist.") from exc
            raise CannotCheck("The host name could not be looked up right now.") from exc
        addrs = [str(i[4][0]) for i in infos]
    if not addrs or not all(_public(a) for a in addrs):
        raise UnsafeUrl("The link points to a private or reserved network address.")


async def check_url(url: str, transport: httpx.AsyncBaseTransport | None = None) -> UrlResult:
    current = url
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=False, transport=transport
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                await assert_safe(current)
            except UnsafeUrl as exc:
                return UrlResult(url, False, None, current, str(exc))
            except CannotCheck as exc:
                return UrlResult(url, False, None, current, str(exc), checked=False)
            try:
                async with client.stream("GET", current) as r:
                    read = 0
                    async for chunk in r.aiter_bytes():
                        read += len(chunk)
                        if read >= 65536:
                            break
                    status, location = r.status_code, r.headers.get("location")
            except httpx.ProxyError as exc:  # refused by our own egress policy, not by the site
                return UrlResult(url, False, None, current, f"Not reachable from this server ({exc}).", checked=False)
            except httpx.HTTPError as exc:
                return UrlResult(url, False, None, current, f"Could not connect ({type(exc).__name__}).")
            if status in (301, 302, 303, 307, 308) and location:
                current = urljoin(current, location)
                continue
            if status < 400:
                return UrlResult(url, True, status, current)
            if status in (401, 403, 429):  # exists but refuses robots — not evidence of a dead link
                return UrlResult(url, True, status, current, "The site refused an automated check.")
            return UrlResult(url, False, status, current, f"HTTP {status}.")
    return UrlResult(url, False, None, current, "Too many redirects.")
