"""Prepare an inert draft plan from a revalidated commercial decision.

This module does not write to WooCommerce and its output is not a credential
or authorization token. The PHP consumer is restricted to synthetic CI.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import re

from .decisions import DecisionLedger, dossier_digest, sha, require_digest
from .linked_review import get_dossier
from .storage import encode, instant, ref


def prepare(ledger, bridge, commercial, store, product, *, decision_sha256,
            reviewer_id, category_id, mapping_ref, title, target_bps, step_minor,
            ceiling_minor, now):
    now=instant(now)
    require_digest(decision_sha256)
    mapping_ref=ref(mapping_ref)
    if type(reviewer_id) is not int or not 1<=reviewer_id<=2147483647 or type(category_id) is not int or not 1<=category_id<=2147483647:
        raise ValueError("Explicit reviewer and category required")
    if not isinstance(title,str) or not title.strip() or title!=title.strip() or len(title.encode("utf-8"))>300 or any(ord(c)<32 or ord(c)==127 for c in title) or any(c in title for c in "<>"):
        raise ValueError("Editorial title required")
    if any(type(x) is not int for x in (target_bps,step_minor,ceiling_minor)) or not 1<=target_bps<10000 or not 1<=step_minor<=ceiling_minor<=10**12:
        raise ValueError("Explicit pricing policy required")
    status=ledger.status(bridge,commercial,store,product,now=now)
    if not status["draft_review_eligible"] or status["decision"]["sha256"]!=decision_sha256:
        raise ValueError("Current commercial decision is not eligible")
    event=status["decision"]
    d=get_dossier(bridge,commercial,event["link_id"],now=now)
    if dossier_digest(d)!=event["dossier_sha256"] or d["link"]["mapping_ref"]!=mapping_ref:
        raise ValueError("Decision evidence or mapping changed")
    # Recheck latest decision after the evidence reads. This is still an offline
    # preview, not an atomic cross-database reservation for a WooCommerce write.
    if ledger.history(store,product)[-1]["sha256"]!=decision_sha256:
        raise ValueError("Decision superseded")
    if now>=instant(datetime.fromisoformat(d["valid_until"])):
        raise ValueError("Expired evidence")
    e=d["evaluation"]
    m=e["economics"]
    sale=m["sale_price_minor"]
    bps=m["variable_deduction_bps"]
    if bps+target_bps>=10000 or sale>ceiling_minor or sale%step_minor or e["contribution_minor"]*10000<sale*target_bps:
        raise ValueError("Reviewed scenario does not meet explicit pricing policy")
    # Keep production identities distinct from synthetic CI identities.
    scope=ledger.archive_ref
    supplier=("ci-intelligence-approved-" if scope.startswith("fixture-") else "dropify-")+sha([scope,store])[:32]
    plan={"schema":"bakata-approved-draft-plan-v1","mode":"offline-preview-only",
          "archive_ref":scope,"decision_sha256":decision_sha256,"decision_id":event["id"],
          "dossier_sha256":event["dossier_sha256"],"evaluation_sha256":e["sha256"],
          "mapping_ref":mapping_ref,"reviewer_id":reviewer_id,"category_id":category_id,
          "supplier_id":supplier,"store_id":store,"external_id":product,
          "title":title,"captured_at":d["catalog"]["captured_at"],"valid_until":d["valid_until"],
          "currency":"COP","minor_unit":2,"economics":m,
          "contribution_minor":e["contribution_minor"],
          "policy":{"target_bps":target_bps,"step_minor":step_minor,"ceiling_minor":ceiling_minor},
          "status":"draft","visibility":"hidden","sellable_stock":0,"sale_price_active":False,
          "publication_authorized":False,"woo_mutation":False}
    return {"plan":plan,"plan_sha256":sha(plan)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("ledger","bridge","commercial"):
        p.add_argument("--"+name,type=Path,required=True)
    for name in ("archive-ref","store","product","decision-sha256","mapping-ref","title"):
        p.add_argument("--"+name,required=True)
    for name in ("reviewer-id","category-id","target-bps","step-minor","ceiling-minor"):
        p.add_argument("--"+name,type=int,required=True)
    a=p.parse_args()
    paths=(a.ledger,a.bridge,a.commercial)
    if not all(x.is_file() and not x.is_symlink() for x in paths) or any(x.samefile(y) for i,x in enumerate(paths) for y in paths[i+1:]):
        p.error("Three existing distinct private archives required")
    os.umask(0o077)
    try:
        with closing(sqlite3.connect(a.ledger,timeout=5)) as db, closing(sqlite3.connect(a.bridge.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as bridge, closing(sqlite3.connect(a.commercial.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as commercial:
            ledger=DecisionLedger(db,a.archive_ref)
            print(encode(prepare(ledger,bridge,commercial,a.store,a.product,
                decision_sha256=a.decision_sha256,reviewer_id=a.reviewer_id,category_id=a.category_id,
                mapping_ref=a.mapping_ref,title=a.title,target_bps=a.target_bps,step_minor=a.step_minor,
                ceiling_minor=a.ceiling_minor,now=datetime.now(timezone.utc))))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,sqlite3.Error):
        p.exit(1,"Draft plan blocked: verify current decision, evidence and policy.\n")


if __name__=="__main__":
    main()
