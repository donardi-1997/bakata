"""Read-only profitability dossier for an explicitly linked Dropify observation.

No cost inference from Dropify prices, no supplier traffic, no approval or write.
Both archives are opened independently in read-only transactions.
"""
import argparse
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .dropify_bridge import APP_ID, decode
from .dropify_catalog import unique
from .models import Observation
from .scoring import CriterionReview, UnitEconomics, evaluate
from .storage import APPLICATION_ID, SCHEMA_VERSION, encode, instant, ref


def bounded_object(raw, limit):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > limit:
        raise ValueError("Invalid archived payload")
    data = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(data, dict):
        raise ValueError("Expected archived object")
    return data


def begin_read(db, application_id, version):
    if db.in_transaction:
        raise ValueError("Independent archive connection required")
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    if (db.execute("PRAGMA application_id").fetchone()[0],
        db.execute("PRAGMA user_version").fetchone()[0]) != (application_id, version):
        raise ValueError("Unexpected archive schema")


def timestamp(value):
    at = instant(datetime.fromisoformat(value))
    if at.isoformat() != value:
        raise ValueError("Expected canonical UTC archive timestamp")
    return at


def get_dossier(bridge, commercial, link_id, *, now):
    """Revalidate the linked review at its evaluation instant and current time.

    Expired or superseded evidence is rejected rather than displayed as ready.
    The dossier is informational and never grants permission to sell.
    """
    now = instant(now)
    link_id = ref(link_id)
    if bridge is commercial or bridge.in_transaction or commercial.in_transaction:
        raise ValueError("Independent archives required")
    try:
        begin_read(bridge, APP_ID, 1)
        begin_read(commercial, APPLICATION_ID, SCHEMA_VERSION)
        link = bridge.execute("""SELECT store,product_id,at,evaluation_id,evaluation_sha,payload
            FROM score_links WHERE id=?""",(link_id,)).fetchone()
        if link is None:
            raise ValueError("Unknown score link")
        store, product, at, evaluation_id, expected_sha, link_raw = link
        linked = bounded_object(link_raw, 8192)
        if set(linked) != {"mapping_ref","cost_ref","actor_ref","reviewed_cost_minor",
                           "linked_at","score","rubric","mode"} or linked["mode"]!="review-reference-only":
            raise ValueError("Unknown score link contract")
        for name in ("mapping_ref","cost_ref","actor_ref"):
            ref(linked[name])
        ref(evaluation_id)
        captured = timestamp(at)
        linked_at = timestamp(linked["linked_at"])
        if not captured <= linked_at <= now or now-captured > timedelta(days=1):
            raise ValueError("Stale or future connector evidence")
        current = bridge.execute("""SELECT at,payload FROM observations
            WHERE store=? AND id=? ORDER BY at DESC LIMIT 1""",(store,product)).fetchone()
        if current is None or current[0] != at:
            raise ValueError("Connector observation missing or superseded")
        row = bounded_object(current[1], 32768)
        # Reuse the existing bridge contract rather than infer values.
        sample = {"schema":"bakata-dropify-bridge-v1","captured_at":captured.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "store_id":store,"page":1,"page_size":1,"offset":0,"possible_next":True,
                  "rows":[row],"approval_ref":"contract-check","query_sha256":"0"*64}
        decode(json.dumps(sample,ensure_ascii=False).encode("utf-8"),now)
        if row["external_id"]!=product or row["type"]!="simple" or not row["simple_stock"]:
            raise ValueError("Positive reported simple stock required")
        review = commercial.execute("""SELECT source,external_id,observed_at,as_of,actor_ref,payload,sha256
            FROM evaluations WHERE id=?""",(evaluation_id,)).fetchone()
        if review is None:
            raise ValueError("Linked evaluation missing")
        source,eid,observed_at,as_of,actor,raw,stored_sha=review
        payload=bounded_object(raw,32768)
        if not re.fullmatch(r"[0-9a-f]{64}",expected_sha) or expected_sha!=stored_sha or hashlib.sha256(raw.encode("utf-8")).hexdigest()!=stored_sha:
            raise ValueError("Linked evaluation digest mismatch")
        ref(actor)
        if set(payload)!={"economics","reviews","result"} or not isinstance(payload["economics"],dict) or not isinstance(payload["reviews"],list):
            raise ValueError("Incomplete evaluation")
        if len(payload["reviews"])!=6:
            raise ValueError("Complete criterion reviews required")
        source_at=timestamp(observed_at)
        evaluated=timestamp(as_of)
        if not source_at<=evaluated<=linked_at:
            raise ValueError("Invalid evaluation chronology")
        obs_row=commercial.execute("""SELECT title,url,currency,price_minor FROM observations
            WHERE source=? AND external_id=? AND observed_at=?""",(source,eid,observed_at)).fetchone()
        if obs_row is None:
            raise ValueError("Commercial observation missing")
        title,url,currency,price=obs_row
        observation=Observation(source,eid,title,url,source_at,currency,price)
        def restore(data):
            value=dict(data)
            value["observation_key"]=tuple(value["observation_key"])
            value["reviewed_at"]=timestamp(value["reviewed_at"])
            return value
        economics=UnitEconomics(**restore(payload["economics"]))
        reviews=tuple(CriterionReview(**restore(r)) for r in payload["reviews"])
        age_us=payload["result"]["max_age"]
        if type(age_us) is not int or not 0<age_us<=30*86400*1000000:
            raise ValueError("Invalid evaluation freshness window")
        age=timedelta(microseconds=age_us)
        original=evaluate(observation,economics,reviews,as_of=evaluated,max_age=age)
        if json.loads(encode(asdict(original)))!=payload["result"]:
            raise ValueError("Stored result does not match the scoring engine")
        if (original.status.value!="review-ready" or original.coverage_pct!=100 or original.blockers
            or original.total is None or linked["score"]!=str(original.total)
            or linked["rubric"]!=original.rubric_version
            or economics.currency!="COP" or economics.evidence_ref!=linked["cost_ref"]
            or type(linked["reviewed_cost_minor"]) is not int
            or economics.supplier_cost_minor!=linked["reviewed_cost_minor"]):
            raise ValueError("Link does not match reviewed cost or complete evaluation")
        if now-evaluated>age:
            raise ValueError("Expired evaluation")
        fresh=evaluate(observation,economics,reviews,as_of=now,max_age=age)
        if fresh.status.value!="review-ready" or fresh.total!=original.total or fresh.blockers:
            raise ValueError("Evaluation evidence no longer review-ready")
        valid_until=min(captured+timedelta(days=1),evaluated+age,source_at+age,
                        economics.reviewed_at+age,*(r.reviewed_at+age for r in reviews))
        amounts={k:getattr(economics,k) for k in ("sale_price_minor","supplier_cost_minor","shipping_minor",
                 "fixed_fee_minor","return_reserve_minor","other_cost_minor","variable_deduction_bps")}
        return {"schema":"bakata-linked-profitability-v1","mode":"review-reference-only",
                "as_of":now.isoformat(),"valid_until":valid_until.isoformat(),
                "catalog":{"store_id":store,"external_id":product,"captured_at":at,"sku":row["sku"],
                           "title":row["title"],"simple_stock_reported":row["simple_stock"],
                           "base_price_reported":row["base_price"],"suggested_price_reported":row["suggested_price"]},
                "link":{"id":link_id,"mapping_ref":linked["mapping_ref"],"cost_ref":linked["cost_ref"],
                        "actor_ref":linked["actor_ref"],"linked_at":linked["linked_at"]},
                "evaluation":{"id":evaluation_id,"sha256":stored_sha,"actor_ref":actor,"as_of":as_of,
                              "rubric":original.rubric_version,"status":"review-ready",
                              "score":str(original.total),"coverage_pct":original.coverage_pct,
                              "commercial_observation":{"source":source,"external_id":eid,"observed_at":observed_at},
                              "currency":"COP","economics":amounts,"contribution_minor":fresh.contribution_minor,
                              "margin_pct":str(fresh.margin_pct.quantize(Decimal("0.01"))),
                              "components":[{"criterion":c.criterion,"weight":c.weight,
                                  "score":str(c.score),"points":str(c.points),"evidence_ref":c.evidence_ref}
                                  for c in fresh.components]},
                "approval_granted":False,"woo_mutation":False}
    finally:
        bridge.rollback()
        commercial.rollback()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",required=True,type=Path)
    parser.add_argument("--commercial",required=True,type=Path)
    parser.add_argument("--link-id",required=True)
    args=parser.parse_args()
    if not args.db.is_file() or not args.commercial.is_file() or args.db.samefile(args.commercial):
        parser.error("Two existing distinct archives required")
    try:
        with closing(sqlite3.connect(args.db.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as bridge, closing(sqlite3.connect(args.commercial.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as commercial:
            print(encode(get_dossier(bridge,commercial,args.link_id,now=datetime.now(timezone.utc))))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,sqlite3.Error):
        parser.exit(1,"Dossier unavailable: review archive integrity, link and evidence freshness.\n")


if __name__=="__main__":
    main()
