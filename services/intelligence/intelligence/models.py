from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit
import re


@dataclass(frozen=True, slots=True)
class Observation:
    source: str
    external_id: str
    title: str
    url: str
    observed_at: datetime
    currency: str
    price_minor: int | None

    def __post_init__(self):
        for key, limit in (("source", 64), ("external_id", 128), ("title", 300), ("url", 2048)):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
                raise ValueError(f"Invalid {key}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", self.source):
            raise ValueError("Invalid source identifier")
        url = urlsplit(self.url)
        if url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None or url.fragment:
            raise ValueError("Expected HTTPS product URL without credentials or fragment")
        if not isinstance(self.observed_at, datetime) or self.observed_at.utcoffset() is None:
            raise ValueError("Timestamp must include timezone")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(timezone.utc))
        if not isinstance(self.currency, str) or not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("Expected three-letter currency code")
        if self.price_minor is not None and (type(self.price_minor) is not int or not 0 <= self.price_minor <= 10**15):
            raise ValueError("Invalid minor-unit price")

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source, self.external_id, self.observed_at.isoformat())
