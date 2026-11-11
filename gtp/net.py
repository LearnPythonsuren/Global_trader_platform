"""SSRF-safe HTTP fetcher for external documents (exchange PDFs, audio, ...).

Fetching a URL that a client supplies is dangerous: without controls it lets a
caller reach internal services ("server-side request forgery"). Every fetch
here must clear four gates:

1. HTTPS only.
2. The host is on an explicit allowlist (exchange / data-vendor domains).
3. Every IP the host resolves to is a public address — never loopback,
   private, link-local, multicast or reserved.
4. Redirects are refused, and the body is capped in size and time.

The host allowlist is the primary control; the IP check is defence in depth.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

# Domains whose subdomains may be fetched by default: the exchanges that host
# filings and the Global Datafeeds attachment hosts.
DEFAULT_DOC_HOSTS = (
    "bseindia.com", "nseindia.com", "nse-india.com", "archives.nseindia.com",
    "globaldatafeeds.in", "lisuns.com",
)


class FetchError(RuntimeError):
    """A document could not be fetched."""


class FetchNotAllowed(FetchError):
    """The URL is blocked by policy (bad scheme, host, address or redirect)."""


def host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == a or host.endswith("." + a) for a in allowed)


def _is_public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.is_global and not (a.is_private or a.is_loopback or a.is_link_local
                                or a.is_multicast or a.is_reserved or a.is_unspecified)


class SafeFetcher:
    def __init__(self, allowed_hosts: tuple[str, ...] = DEFAULT_DOC_HOSTS, *, timeout: float = 20.0,
                 max_bytes: int = 30_000_000, resolver=socket.getaddrinfo, transport: httpx.BaseTransport | None = None):
        self.allowed = tuple(h.lower().lstrip(".") for h in allowed_hosts)
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._resolver = resolver
        self._transport = transport

    def check(self, url: str) -> str:
        """Validate a URL against policy. Returns the hostname, or raises FetchNotAllowed."""
        p = urlparse(url)
        if p.scheme != "https":
            raise FetchNotAllowed("Only https URLs are allowed")
        host = p.hostname
        if not host or not host_allowed(host, self.allowed):
            raise FetchNotAllowed(f"Host {host!r} is not on the document allowlist")
        try:
            infos = self._resolver(host, p.port or 443, type=socket.SOCK_STREAM)
        except OSError as e:
            raise FetchNotAllowed(f"Could not resolve {host!r}: {e}") from None
        ips = {info[4][0] for info in infos}
        if not ips or not all(_is_public(ip) for ip in ips):
            raise FetchNotAllowed(f"{host!r} resolves to a non-public address")
        return host

    def fetch(self, url: str, *, accept: tuple[str, ...] | None = None, max_redirects: int = 5) -> tuple[str, bytes]:
        """Return (content_type, body) for an allowlisted URL, or raise FetchError.

        Redirects are followed (exchange filings often go through a redirecting .aspx link),
        but every hop is re-validated against the same policy — https, host allowlist and a
        public-address check — so a redirect can never be used to reach an internal target.
        """
        self.check(url)
        current = url
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False, transport=self._transport) as client:
                for _ in range(max_redirects + 1):
                    with client.stream("GET", current, headers={"User-Agent": "GlobalTraderPlatform/1.0"}) as r:
                        if r.status_code in (301, 302, 303, 307, 308):
                            location = r.headers.get("location")
                            if not location:
                                raise FetchError("Redirect response without a Location")
                            current = urljoin(current, location)
                            self.check(current)       # re-validate the hop before following it
                            continue
                        if r.status_code >= 400:
                            raise FetchError(f"Document host returned HTTP {r.status_code}")
                        ctype = r.headers.get("content-type", "application/octet-stream").split(";")[0].strip().lower()
                        if accept and not any(a in ctype for a in accept) and "octet-stream" not in ctype:
                            # Some exchanges mislabel PDFs; the caller re-checks magic bytes for octet-stream.
                            raise FetchError(f"Unexpected content type {ctype!r}")
                        buf = bytearray()
                        for chunk in r.iter_bytes():
                            buf += chunk
                            if len(buf) > self.max_bytes:
                                raise FetchError(f"Document exceeds the {self.max_bytes // 1_000_000} MB limit")
                        return ctype, bytes(buf)
            raise FetchNotAllowed(f"Too many redirects (over {max_redirects})")
        except httpx.HTTPError as e:
            raise FetchError(f"Could not fetch document: {e}") from None
