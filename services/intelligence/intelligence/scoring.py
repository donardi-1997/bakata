"""Versioned, explainable commercial screening; no automated listing or price writes."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from types import MappingProxyType
import re

from .models import Observation

RUBRIC_VERSION = "int06-v1"
WEIGHTS = MappingProxyType({
    "profitability": 25, "demand": 20, "supplier_reliability": 15,
    "logistics": 15, "advertising": 10, "differentiation": 10, "return_risk": 5,
})
REVIEW_CRITERIA = tuple(k for k in WEIGHTS if k != "profitability")
MAX_MINOR = 10**12


def _timestamp(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Timestamp must include timezone")
    return value.astimezone(timezone.utc)


def _reference(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
        raise ValueError("Expected evidence reference")


def _key(value):
    if not isinstance(value, tuple) or len(value) != 3 or any(not isinstance(v, str) or not v for v in value):
        raise ValueError("Expected exact observation key")


def _money(value):
    if value is not None and (type(value) is not int or not 0 <= value <= MAX_MINOR):
        raise ValueError("Invalid minor-unit amount")


@dataclass(frozen=True, slots=True)
class UnitEconomics:
    observation_key: tuple[str, str, str]
    evidence_ref: str
    reviewed_at: datetime
    currency: str
    sale_price_minor: int | None
    supplier_cost_minor: int | None
    shipping_minor: int | None
    fixed_fee_minor: int | None
    return_reserve_minor: int | None
    other_cost_minor: int | None
    variable_deduction_bps: int | None

    def __post_init__(self):
        _key(self.observation_key)
        _reference(self.evidence_ref)
        _timestamp(self.reviewed_at)
        if self.currency not in ("COP", "USD", "EUR"):
            raise ValueError("Unsupported currency")
        for value in (self.sale_price_minor, self.supplier_cost_minor, self.shipping_minor,
                      self.fixed_fee_minor, self.return_reserve_minor, self.other_cost_minor):
            _money(value)
        bps = self.variable_deduction_bps
        if bps is not None and (type(bps) is not int or not 0 <= bps <= 10000):
            raise ValueError("Invalid variable deductions")
        if self.sale_price_minor == 0:
            raise ValueError("Positive scenario sale price required")

    @property
    def contribution_minor(self) -> int | None:
        values = (self.sale_price_minor, self.supplier_cost_minor, self.shipping_minor,
                  self.fixed_fee_minor, self.return_reserve_minor, self.other_cost_minor,
                  self.variable_deduction_bps)
        if any(v is None for v in values):
            return None
        # Same aggregate rounding convention as the Bakatá Core pricing preview.
        variable = (self.sale_price_minor * self.variable_deduction_bps + 9999) // 10000
        return self.sale_price_minor - sum(values[1:6]) - variable

    @property
    def margin_pct(self) -> Decimal | None:
        contribution = self.contribution_minor
        if contribution is None:
            return None
        return Decimal(contribution) * 100 / Decimal(self.sale_price_minor)


@dataclass(frozen=True, slots=True)
class CriterionReview:
    observation_key: tuple[str, str, str]
    criterion: str
    score: int
    evidence_ref: str
    reviewed_at: datetime
    rationale: str
    rubric_version: str = RUBRIC_VERSION

    def __post_init__(self):
        _key(self.observation_key)
        _reference(self.evidence_ref)
        _timestamp(self.reviewed_at)
        if self.criterion not in REVIEW_CRITERIA:
            raise ValueError("Unsupported manual criterion")
        if type(self.score) is not int or self.score not in (0, 25, 50, 75, 100):
            raise ValueError("Use the five explicit rubric levels")
        if self.rubric_version != RUBRIC_VERSION:
            raise ValueError("Unsupported rubric version")
        if not isinstance(self.rationale, str) or not self.rationale.strip() or len(self.rationale) > 500 or any(ord(c) < 32 for c in self.rationale):
            raise ValueError("Provide bounded review rationale")


class ScreeningStatus(str, Enum):
    INCOMPLETE = "incomplete"
    BLOCKED = "blocked"
    REVIEW_READY = "review-ready"


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    criterion: str
    weight: int
    score: Decimal | None
    points: Decimal | None
    evidence_ref: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class ScoreResult:
    observation_key: tuple[str, str, str]
    rubric_version: str
    as_of: datetime
    max_age: timedelta
    status: ScreeningStatus
    components: tuple[ScoreComponent, ...]
    coverage_pct: int
    total: Decimal | None
    contribution_minor: int | None
    margin_pct: Decimal | None
    blockers: tuple[str, ...]


def evaluate(observation: Observation, economics: UnitEconomics | None,
             reviews: tuple[CriterionReview, ...], *, as_of: datetime,
             max_age: timedelta) -> ScoreResult:
    as_of = _timestamp(as_of)
    if not isinstance(max_age, timedelta) or not timedelta(0) < max_age <= timedelta(days=30):
        raise ValueError("Specify freshness window of at most 30 days")
    if observation.observed_at > as_of:
        raise ValueError("Future observation")
    if len(reviews) > len(REVIEW_CRITERIA):
        raise ValueError("Too many criterion reviews")
    by_criterion = {}
    for review in reviews:
        if review.observation_key != observation.key or review.criterion in by_criterion:
            raise ValueError("Wrong observation or duplicate criterion")
        if _timestamp(review.reviewed_at) < observation.observed_at:
            raise ValueError("Review predates observation")
        if _timestamp(review.reviewed_at) > as_of:
            raise ValueError("Future review")
        by_criterion[review.criterion] = review

    components = []
    blockers = []
    if as_of - observation.observed_at > max_age:
        blockers.append("stale-observation")

    contribution = margin = None
    for criterion, weight in WEIGHTS.items():
        score = evidence = None
        reason = "missing-evidence"
        if criterion == "profitability" and economics is not None:
            if economics.observation_key != observation.key or economics.currency != observation.currency:
                raise ValueError("Economics belongs to another observation or currency")
            at = _timestamp(economics.reviewed_at)
            if not observation.observed_at <= at <= as_of:
                raise ValueError("Economics review outside observation window")
            evidence = economics.evidence_ref
            if as_of - at > max_age:
                reason = "stale-evidence"
            elif economics.contribution_minor is None:
                reason = "unknown-costs"
            else:
                contribution = economics.contribution_minor
                margin = economics.margin_pct
                # Provisional linear rubric: 0% margin -> 0, 30% -> 100.
                score = min(Decimal(100), max(Decimal(0), margin * 100 / 30))
                reason = "scenario-contribution"
                if contribution <= 0:
                    blockers.append("nonpositive-contribution")
        elif criterion in by_criterion:
            review = by_criterion[criterion]
            evidence = review.evidence_ref
            if as_of - _timestamp(review.reviewed_at) > max_age:
                reason = "stale-evidence"
            else:
                score = Decimal(review.score)
                reason = review.rationale
        if score is not None and score == 0 and criterion in ("supplier_reliability", "return_risk"):
            blockers.append("critical-review:" + criterion)
        points = score * weight / 100 if score is not None else None
        components.append(ScoreComponent(criterion, weight, score, points, evidence, reason))
    coverage = sum(c.weight for c in components if c.score is not None)
    total = None
    if coverage == 100 and "stale-observation" not in blockers:
        total = sum((c.points for c in components), Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    status = ScreeningStatus.BLOCKED if blockers else (
        ScreeningStatus.REVIEW_READY if total is not None else ScreeningStatus.INCOMPLETE)
    return ScoreResult(observation.key, RUBRIC_VERSION, as_of, max_age, status, tuple(components),
                       coverage, total, contribution, margin, tuple(blockers))


def rank_review_ready(results: tuple[ScoreResult, ...]) -> tuple[ScoreResult, ...]:
    """Rank complete, non-blocked results from the same rubric, evaluation instant and freshness window."""
    if len(results) > 1000:
        raise ValueError("Ranking limited to 1000 candidates")
    identities = [r.observation_key[:2] for r in results]
    if len(set(identities)) != len(identities):
        raise ValueError("Use one observation per source identity")
    if len({(r.rubric_version, r.as_of, r.max_age) for r in results}) > 1:
        raise ValueError("Rank only a common rubric, evaluation instant and freshness window")
    return tuple(sorted((r for r in results if r.status is ScreeningStatus.REVIEW_READY and r.total is not None),
                        key=lambda r: (-r.total, r.observation_key)))
