"""Versioned synthetic dashboard export. No network or commercial data."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from .adapters import FixtureAdapter
from .scoring import UnitEconomics, CriterionReview, REVIEW_CRITERIA, evaluate


def hundredths(value):
    return None if value is None else int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fixture_snapshot():
    rows = FixtureAdapter().collect()
    at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    output = []
    for index, row in enumerate(rows):
        economics = UnitEconomics(row.key, "fixture-cost", at, row.currency,
                                  5700000, 2500000, 1200000, 100000, 200000, 0, 400) if index == 0 else None
        reviews = tuple(CriterionReview(row.key, key, 75, "fixture-" + key, at,
                                        "Evaluación sintética; no representa evidencia real.")
                        for key in REVIEW_CRITERIA) if index == 0 else ()
        result = evaluate(row, economics, reviews, as_of=at, max_age=timedelta(days=2))
        output.append({
            "source": row.source, "external_id": row.external_id, "title": row.title,
            "url": row.url, "observed_at": row.observed_at.isoformat(),
            "currency": row.currency, "price_minor": row.price_minor,
            "status": result.status.value, "coverage_pct": result.coverage_pct,
            "score_bp": hundredths(result.total), "blockers": list(result.blockers),
            "components": [{
                "criterion": c.criterion, "weight": c.weight, "score_bp": hundredths(c.score),
                "points_bp": hundredths(c.points), "evidence_ref": c.evidence_ref, "reason": c.reason,
            } for c in result.components],
        })
    return {"schema": "bakata-intelligence-preview-v1", "mode": "fixture",
            "rubric": "int06-v1", "as_of": at.isoformat(), "rows": output}


if __name__ == "__main__":
    print(json.dumps(fixture_snapshot(), ensure_ascii=False))
