"""Import reviewed, bounded offline snapshots. Never fetch or write WooCommerce."""
from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import re
from .extraction import extract_products
from .models import Observation
from .sources import SourceRegistry, SourceKind

MAX_BYTES = 524288
MAX_ROWS = 100
CURRENCIES = ("COP", "USD", "EUR")


@dataclass(frozen=True, slots=True)
class Capture:
    source: str
    url: str
    observed_at: datetime
    body: bytes


@dataclass(frozen=True, slots=True)
class Evidence:
    source: str
    url: str
    observed_at: datetime
    sha256: str
    adapter: str
    approval_ref: str


@dataclass(frozen=True, slots=True)
class CommercialBatch:
    evidence: Evidence
    observations: tuple[Observation, ...]


def _minor(raw) -> int | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{1,16}", raw) or int(raw) > 10**15:
        raise ValueError("Expected bounded price in minor units")
    return int(raw)


def _observation(spec, capture, external_id, title, url, currency, price):
    if currency not in CURRENCIES:
        raise ValueError("Unsupported or missing currency")
    return Observation(spec.source, external_id, title, spec.validate_url(url),
                       capture.observed_at, currency, price)


def _store_api(spec, capture):
    data = json.loads(capture.body.decode("utf-8-sig"))
    if not isinstance(data, list) or len(data) > MAX_ROWS:
        raise ValueError("Expected bounded product collection")
    rows = []
    for item in data:
        if not isinstance(item, dict) or type(item.get("id")) is not int or not 0 < item["id"] <= 2**63 - 1:
            raise ValueError("Missing stable WooCommerce product ID")
        prices = item.get("prices")
        if not isinstance(prices, dict) or type(prices.get("currency_minor_unit")) is not int or prices["currency_minor_unit"] != 2:
            raise ValueError("Unsupported Store API price exponent")
        if item.get("is_password_protected") is not False:
            raise ValueError("Product visibility not explicitly public")
        # Variable product price ranges are not a single comparable price.
        amount = None if prices.get("price_range") is not None or item.get("type") != "simple" else _minor(prices.get("price"))
        rows.append(_observation(spec, capture, str(item["id"]), item.get("name"),
                                 item.get("permalink"), prices.get("currency_code"), amount))
    return rows


def _csv(spec, capture):
    reader = csv.DictReader(io.StringIO(capture.body.decode("utf-8-sig"), newline=""), strict=True)
    expected = ["external_id", "title", "url", "currency", "price_minor"]
    if reader.fieldnames != expected:
        raise ValueError("Unexpected CSV contract")
    rows = []
    for index, row in enumerate(reader):
        if index >= MAX_ROWS or None in row or any(value is None for value in row.values()):
            raise ValueError("Invalid or oversized CSV batch")
        rows.append(_observation(spec, capture, row["external_id"], row["title"], row["url"],
                                 row["currency"], _minor(row["price_minor"])))
    return rows


def _json_ld(spec, capture, external_id):
    candidates = extract_products(capture.body)
    if len(candidates) != 1 or not isinstance(external_id, str) or not external_id.strip():
        raise ValueError("Single product and reviewed stable external ID required")
    candidate = candidates[0]
    return [_observation(spec, capture, external_id, candidate.title, capture.url,
                         candidate.currency, candidate.price_minor)]


def import_capture(registry: SourceRegistry, capture: Capture, *, external_id: str | None = None,
                   now: datetime | None = None) -> CommercialBatch:
    now = now if now is not None else datetime.now(timezone.utc)
    spec = registry.get(capture.source, now)
    spec.validate_url(capture.url)
    if (not isinstance(capture.observed_at, datetime) or capture.observed_at.utcoffset() is None
            or capture.observed_at > now):
        raise ValueError("Invalid capture timestamp")
    if not isinstance(capture.body, bytes) or not 0 < len(capture.body) <= MAX_BYTES:
        raise ValueError("Invalid or oversized capture")
    if spec.kind is SourceKind.STORE_API:
        if url_path(capture.url).rstrip("/") != "/wp-json/wc/store/v1/products":
            raise ValueError("Not the public products collection path")
        rows = _store_api(spec, capture)
    elif spec.kind is SourceKind.AUTHORIZED_CSV:
        rows = _csv(spec, capture)
    else:
        rows = _json_ld(spec, capture, external_id)
    # A single source snapshot may not contain conflicting or duplicate identities.
    if len({row.external_id for row in rows}) != len(rows):
        raise ValueError("Duplicate product identity in capture")
    evidence = Evidence(spec.source, capture.url, capture.observed_at.astimezone(timezone.utc),
                        hashlib.sha256(capture.body).hexdigest(), spec.kind.value, spec.approval_ref)
    return CommercialBatch(evidence, tuple(rows))


def url_path(url):
    from urllib.parse import urlsplit
    return urlsplit(url).path
