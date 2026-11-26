"""Restricted HTTPS GET transport. No real source is configured by default."""
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import http.client
import ipaddress
import re
import socket
import ssl
import time
from typing import Callable
from urllib.parse import urlsplit, urljoin
from urllib.robotparser import RobotFileParser

AGENT = "BakataIntelligence"
USER_AGENT = AGENT + "/0.1"


class FetchError(RuntimeError):
    pass


class PolicyError(FetchError):
    pass


@dataclass(frozen=True)
class SourcePolicy:
    host: str
    terms_approved: bool
    robots_text: str
    robots_valid_until: datetime

    def validate(self, url: str) -> str:
        if not self.terms_approved:
            raise PolicyError("Source terms not approved")
        if self.robots_valid_until.tzinfo is None or datetime.now(timezone.utc) >= self.robots_valid_until:
            raise PolicyError("Missing or expired robots review")
        if not isinstance(url, str) or len(url) > 2048 or any(ord(c) <= 32 or ord(c) >= 127 for c in url) or "\\" in url:
            raise PolicyError("Invalid URL")
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            if (parsed.scheme != "https" or not host or parsed.username is not None
                    or parsed.password is not None or parsed.port not in (None, 443)
                    or parsed.fragment or host != self.host
                    or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
                    or parsed.netloc not in (host, host + ":443")):
                raise PolicyError("Destination not allowed")
        except ValueError as exc:
            raise PolicyError("Invalid destination") from exc
        if not self.robots_text.strip() or len(self.robots_text) > 262144:
            raise PolicyError("Missing or oversized robots policy")
        robots = RobotFileParser()
        robots.parse(self.robots_text.splitlines())
        if not robots.can_fetch(AGENT, url):
            raise PolicyError("Disallowed by robots policy")
        return host

    def interval(self) -> float:
        robots = RobotFileParser()
        robots.parse(self.robots_text.splitlines())
        rate = robots.request_rate(AGENT)
        return max(2.0, float(robots.crawl_delay(AGENT) or 0),
                   rate.seconds / rate.requests if rate and rate.requests > 0 else 0)


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


def public_ip(host: str, resolver=socket.getaddrinfo) -> str:
    addresses = resolver(host, 443, type=socket.SOCK_STREAM)
    ips = [ipaddress.ip_address(item[4][0]) for item in addresses]
    if not ips or any(not ip.is_global or ip.is_multicast or ip.is_reserved or
                      (isinstance(ip, ipaddress.IPv6Address) and
                       (ip.ipv4_mapped is not None or ip.sixtofour is not None or ip.teredo is not None))
                      for ip in ips):
        raise PolicyError("Non-public DNS destination")
    return str(ips[0])


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, timeout: float):
        super().__init__(host, port=443, timeout=timeout, context=ssl.create_default_context())
        self.ip = ip

    def connect(self):
        # Numeric IP avoids a second lookup; TLS still verifies the original hostname.
        raw = socket.create_connection((self.ip, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def https_get(url: str, host: str, timeout: float, max_bytes: int, *,
              accept: str = "text/html, application/xhtml+xml",
              expected_ip: str | None = None) -> Response:
    ip = public_ip(host)
    if expected_ip is not None and ip != expected_ip:
        raise PolicyError("DNS destination differs from reviewed address")
    parsed = urlsplit(url)
    target = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
    conn = PinnedHTTPS(host, ip, timeout)
    try:
        conn.request("GET", target, headers={"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "identity", "Connection": "close"})
        response = conn.getresponse()
        headers = {k.lower(): v for k, v in response.getheaders()}
        if response.status != 200:
            return Response(response.status, headers, b"")
        if accept == "application/json" and headers.get("content-type", "").split(";",1)[0].strip().lower() != accept:
            raise FetchError("Unexpected JSON media type")
        if headers.get("content-encoding", "identity").lower() != "identity":
            raise FetchError("Compressed response rejected")
        length = headers.get("content-length")
        if length is not None and (not length.isdecimal() or int(length) > max_bytes):
            raise FetchError("Invalid or oversized content length")
        body = bytearray()
        deadline = time.monotonic() + timeout
        while True:
            if time.monotonic() >= deadline:
                raise FetchError("Body deadline exceeded")
            chunk = response.read1(min(65536, max_bytes + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > max_bytes:
                raise FetchError("Body exceeds limit")
        if length is not None and len(body) != int(length):
            raise FetchError("Incomplete response body")
        return Response(response.status, headers, bytes(body))
    finally:
        conn.close()


class Fetcher:
    def __init__(self, policy: SourcePolicy, transport: Callable = https_get,
                 clock: Callable = time.monotonic, sleep: Callable = time.sleep):
        self.policy = policy
        self.transport = transport
        self.clock = clock
        self.sleep = sleep
        self.last = None

    def _wait(self):
        interval = self.policy.interval()
        if interval > 30:
            raise FetchError("Crawl delay requires deferred scheduling")
        if self.last is not None:
            self.sleep(max(0.0, self.last + interval - self.clock()))
        self.last = self.clock()

    def fetch(self, url: str) -> Response:
        # Per-instance serial limiter; no parallel workers in this phase.
        retries = redirects = 0
        for _ in range(5):
            host = self.policy.validate(url)
            self._wait()
            try:
                response = self.transport(url, host, 10.0, 524288)
            except (OSError, http.client.HTTPException) as exc:
                raise FetchError("Transport failure") from exc
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location or redirects >= 2:
                    raise FetchError("Redirect limit or missing location")
                redirects += 1
                url = urljoin(url, location)
                continue
            if response.status in (429, 502, 503, 504):
                if retries >= 2:
                    raise FetchError("Retry limit")
                delay = 2 ** (retries + 1)
                raw = response.headers.get("retry-after")
                if raw is not None:
                    try:
                        seconds = int(raw) if raw.isdecimal() else (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()
                        delay = max(delay, seconds)
                    except (ValueError, TypeError, OverflowError):
                        raise FetchError("Invalid Retry-After; defer")
                if delay > 30:
                    raise FetchError("Retry-After requires deferred scheduling")
                retries += 1
                self.sleep(delay)
                continue
            if response.status != 200:
                raise FetchError(f"HTTP {response.status}")
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if mime not in ("text/html", "application/xhtml+xml") or len(response.body) > 524288:
                raise FetchError("Unsupported or oversized response")
            return response
        raise FetchError("Request budget exhausted")
