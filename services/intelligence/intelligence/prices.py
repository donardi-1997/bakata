"""Read-only price intelligence. No currency conversion, pricing writes or margin estimates."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
from .models import Observation
from .matching import ReviewedLink
from .references import ref
import re

CURRENCIES = ("COP", "USD", "EUR")
MAX_MINOR = 10**15


def _timestamp(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Timestamp must include timezone")
    return value.astimezone(timezone.utc)


def _amount(value: int | None):
    if value is not None and (type(value) is not int or not 0 <= value <= MAX_MINOR):
        raise ValueError("Invalid additional cost in minor units")


def percent_change(previous: int | None, current: int | None) -> Decimal | None:
    _amount(previous)
    _amount(current)
    if previous is None or current is None or previous == 0:
        return None
    return (Decimal(current - previous) * 100 / Decimal(previous)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class PriceStats:
    count: int
    minimum_minor: int | None
    maximum_minor: int | None
    median_minor: Decimal | None


def _stats(values: list[int]) -> PriceStats:
    values = sorted(values)
    n = len(values)
    if not n:
        return PriceStats(0, None, None, None)
    median = (Decimal(values[(n - 1) // 2]) + Decimal(values[n // 2])) / 2
    return PriceStats(n, values[0], values[-1], median)


@dataclass(frozen=True, slots=True)
class PriceHistory:
    identity: tuple[str, str]
    currency: str
    observations: tuple[Observation, ...]
    stats: PriceStats
    unknown_count: int
    latest_age: timedelta
    latest_change_pct: Decimal | None


def price_history(rows: tuple[Observation, ...], *, as_of: datetime) -> PriceHistory:
    """Observed advertised prices only, one identity and one currency."""
    as_of = _timestamp(as_of)
    if not 1 <= len(rows) <= 1000:
        raise ValueError("History requires 1–1000 observations")
    identity = rows[0].source, rows[0].external_id
    currency = rows[0].currency
    if currency not in CURRENCIES:
        raise ValueError("Unsupported currency")
    unique = {}
    for row in rows:
        if (row.source, row.external_id) != identity or row.currency != currency:
            raise ValueError("Mixed identity or currency")
        if row.observed_at > as_of:
            raise ValueError("Future observation")
        if row.key in unique and unique[row.key] != row:
            raise ValueError("Conflicting observation")
        unique[row.key] = row
    ordered = tuple(sorted(unique.values(), key=lambda row: row.observed_at))
    known = [row.price_minor for row in ordered if row.price_minor is not None]
    change = percent_change(ordered[-2].price_minor, ordered[-1].price_minor) if len(ordered) > 1 else None
    return PriceHistory(identity, currency, ordered, _stats(known), len(ordered) - len(known),
                        as_of - ordered[-1].observed_at, change)


@dataclass(frozen=True, slots=True)
class ReviewedPriceContext:
    """Externally reviewed costs for exactly one observation and purchase scenario."""
    observation_key: tuple[str, str, str]
    evidence_ref: str
    destination: str
    price_kind: str
    condition: str
    tax_included: bool | None
    additional_tax_minor: int | None
    shipping_minor: int | None
    quantity: int = 1

    def __post_init__(self):
        if not isinstance(self.observation_key, tuple) or len(self.observation_key) != 3:
            raise ValueError("Expected exact observation key")
        if not isinstance(self.evidence_ref, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", self.evidence_ref):
            raise ValueError("Missing reviewed cost evidence")
        if not isinstance(self.destination, str) or not re.fullmatch(r"[A-Z]{2}:[A-Za-z0-9_-]{1,64}", self.destination):
            raise ValueError("Expected explicit country and delivery zone")
        if self.price_kind not in ("retail", "supplier") or self.condition not in ("new", "used", "refurbished"):
            raise ValueError("Unsupported price scenario")
        if type(self.quantity) is not int or self.quantity != 1:
            raise ValueError("Only one-unit scenarios are supported")
        if self.tax_included is not None and type(self.tax_included) is not bool:
            raise ValueError("Invalid tax basis")
        _amount(self.additional_tax_minor)
        _amount(self.shipping_minor)
        if self.tax_included is True and self.additional_tax_minor not in (None, 0):
            raise ValueError("Contradictory included taxes")


@dataclass(frozen=True, slots=True)
class Quote:
    observation: Observation
    context: ReviewedPriceContext

    def __post_init__(self):
        if self.observation.key != self.context.observation_key:
            raise ValueError("Price context belongs to another observation")

    @property
    def total_minor(self) -> int | None:
        row, ctx = self.observation, self.context
        if row.price_minor is None or ctx.tax_included is None or ctx.shipping_minor is None:
            return None
        tax = 0 if ctx.tax_included else ctx.additional_tax_minor
        if tax is None:
            return None
        total = row.price_minor + tax + ctx.shipping_minor
        _amount(total)
        return total


@dataclass(frozen=True, slots=True)
class MarketComparison:
    currency: str
    destination: str
    price_kind: str
    condition: str
    totals: tuple[tuple[tuple[str, str, str], int], ...]
    stats: PriceStats
    spread_minor: int
    lowest_vs_highest_pct: Decimal | None


def market_comparison(quotes: tuple[Quote, ...], links: tuple[ReviewedLink, ...], *,
                      as_of: datetime, max_age: timedelta,
                      max_skew: timedelta) -> MarketComparison:
    """Require explicit approval of every pair, never infer transitive equivalence.

    The caller is trusted to provide authentic reviewed links and cost annotations.
    These values are not authorization tokens; persistent verification is future work.
    """
    as_of = _timestamp(as_of)
    if not 2 <= len(quotes) <= 50:
        raise ValueError("Comparison requires 2–50 quotes")
    if not timedelta(0) < max_age <= timedelta(days=30):
        raise ValueError("Choose a positive freshness window up to 30 days")
    if not timedelta(0) <= max_skew <= max_age:
        raise ValueError("Invalid capture skew")
    ordered = sorted(quotes, key=lambda quote: quote.observation.key)
    sources = {q.observation.source for q in ordered}
    if len(sources) != len(ordered):
        raise ValueError("Use one quote per independent source identifier")
    first = ordered[0]
    currency = first.observation.currency
    context = first.context
    scenario = context.destination, context.price_kind, context.condition, context.quantity
    if currency not in CURRENCIES:
        raise ValueError("Unsupported currency")
    totals = []
    times = []
    for quote in ordered:
        row, ctx = quote.observation, quote.context
        if row.currency != currency:
            raise ValueError("Mixed currencies; no implicit FX conversion")
        if (ctx.destination, ctx.price_kind, ctx.condition, ctx.quantity) != scenario:
            raise ValueError("Different purchase scenarios")
        age = as_of - row.observed_at
        if not timedelta(0) <= age <= max_age:
            raise ValueError("Future or stale observation")
        total = quote.total_minor
        if total is None:
            raise ValueError("Unknown price, taxes or shipping")
        totals.append((row.key, total))
        times.append(row.observed_at)
    if max(times) - min(times) > max_skew:
        raise ValueError("Captures too far apart in time")
    expected = {frozenset((a.observation.key, b.observation.key)) for a, b in combinations(ordered, 2)}
    if len(links) != len(expected):
        raise ValueError("Require direct review for every pair")
    reviewed = set()
    for link in links:
        pair = frozenset((link.left_key, link.right_key))
        if pair not in expected or pair in reviewed:
            raise ValueError("Invalid, duplicate or stale equivalence review")
        ref(link.review_ref)
        reviewed.add(pair)
    stats = _stats([total for _, total in totals])
    return MarketComparison(currency, context.destination, context.price_kind, context.condition,
                            tuple(totals), stats, stats.maximum_minor - stats.minimum_minor,
                            percent_change(stats.maximum_minor, stats.minimum_minor))
