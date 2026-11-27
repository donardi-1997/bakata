"""Synthetic contract fixture for the existing catalog browser QA, never live."""
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from intelligence.models import Observation
from intelligence.scoring import UnitEconomics, CriterionReview, REVIEW_CRITERIA, evaluate
from intelligence.storage import encode

if os.environ.get("BAKATA_CI_FIXTURES")!="1":
    raise SystemExit("CI fixture required")
page=json.loads(Path("/tmp/bakata-catalog-review.json").read_text())["snapshot"]
row=page["rows"][0]
captured=datetime.fromisoformat(page["captured_at"].replace("Z","+00:00"))
now=datetime.now(timezone.utc).replace(microsecond=0)
obs=Observation("fixture-a","001","Fixture","https://a.invalid/item",captured,"COP",4990000)
econ=UnitEconomics(obs.key,"fixture-cost",now,"COP",5700000,2500000,1200000,100000,200000,0,400)
reviews=tuple(CriterionReview(obs.key,k,75,"fixture-"+k,now,"Synthetic fixture") for k in REVIEW_CRITERIA)
result=evaluate(obs,econ,reviews,as_of=now,max_age=timedelta(days=1))
amounts={k:getattr(econ,k) for k in ("sale_price_minor","supplier_cost_minor","shipping_minor","fixed_fee_minor","return_reserve_minor","other_cost_minor","variable_deduction_bps")}
d={"schema":"bakata-linked-profitability-v1","mode":"review-reference-only","as_of":now.isoformat(),
   "valid_until":(captured+timedelta(days=1)).isoformat(),
   "catalog":{"store_id":page["store_id"],"external_id":row["external_id"],"captured_at":captured.isoformat(),
       "sku":row["sku"],"title":row["title"],"simple_stock_reported":row["simple_stock"],
       "base_price_reported":row["base_price"],"suggested_price_reported":row["suggested_price"]},
   "link":{"id":"fixture-link","mapping_ref":"fixture-map","cost_ref":"fixture-cost","actor_ref":"fixture-actor","linked_at":now.isoformat()},
   "evaluation":{"id":"fixture-evaluation","sha256":"a"*64,"actor_ref":"fixture-actor","as_of":now.isoformat(),
       "rubric":result.rubric_version,"status":result.status.value,"score":str(result.total),"coverage_pct":result.coverage_pct,
       "commercial_observation":{"source":obs.source,"external_id":obs.external_id,"observed_at":captured.isoformat()},
       "currency":"COP","economics":amounts,"contribution_minor":result.contribution_minor,
       "margin_pct":str(result.margin_pct.quantize(Decimal("0.01"))),
       "components":[{"criterion":c.criterion,"weight":c.weight,"score":str(c.score),"points":str(c.points),"evidence_ref":c.evidence_ref} for c in result.components]},
   "approval_granted":False,"woo_mutation":False}
print(encode(d))
