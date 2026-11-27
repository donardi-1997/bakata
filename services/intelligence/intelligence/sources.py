"""Explicit offline source registry. An approval reference is not proof of authorization."""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import urlsplit
import re


class SourceKind(str, Enum):
    STORE_API = "woocommerce-store-api"
    JSON_LD = "json-ld"
    AUTHORIZED_CSV = "authorized-csv"


@dataclass(frozen=True, slots=True)
class SourceSpec:
    source: str
    host: str
    kind: SourceKind
    approval_ref: str | None = None
    approved_until: datetime | None = None

    def __post_init__(self):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", self.source):
            raise ValueError("Invalid source identifier")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", self.host):
            raise ValueError("Expected exact lowercase hostname")
        if not isinstance(self.kind, SourceKind):
            raise ValueError("Unsupported adapter kind")

    def require_approval(self, now: datetime):
        if not self.approval_ref or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", self.approval_ref):
            raise ValueError("Missing reviewed offline authorization reference")
        if (now.utcoffset() is None or self.approved_until is None
                or self.approved_until.utcoffset() is None or now >= self.approved_until):
            raise ValueError("Source approval missing or expired")

    def validate_url(self, url: str) -> str:
        if not isinstance(url, str) or len(url) > 2048 or any(ord(c) <= 32 or ord(c) >= 127 for c in url) or "\\" in url:
            raise ValueError("Invalid provenance URL")
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != self.host
                or parsed.netloc not in (self.host, self.host + ":443")
                or parsed.query or parsed.fragment):
            raise ValueError("URL outside approved source or contains query/fragment")
        return url


class SourceRegistry:
    def __init__(self, specs: tuple[SourceSpec, ...] = ()):
        self._specs = {}
        for spec in specs:
            if spec.source in self._specs:
                raise ValueError("Duplicate source identifier")
            self._specs[spec.source] = spec

    def get(self, source: str, now: datetime | None = None) -> SourceSpec:
        if source not in self._specs:
            raise ValueError("Unregistered source")
        spec = self._specs[source]
        spec.require_approval(now if now is not None else datetime.now(timezone.utc))
        return spec
