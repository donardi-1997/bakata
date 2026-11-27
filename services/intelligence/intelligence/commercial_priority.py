"""Prioritize human review of archived alerts using revalidated commercial evidence."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import re
import sqlite3

from .alert_ledger import AlertLedger
from .dropify_bridge import APP_ID
from .linked_review import get_dossier
from .opportunity_radar import row_data, page_refs, timestamp
from .storage import APPLICATION_ID, SCHEMA_VERSION, encode, instant

MAX_PRODUCTS=25
MAX_ALERTS_PER_PRODUCT=100
ORDER={"urgent-review":0,"historical-risk-review":1,"evidence-review":2,
       "candidate-for-review":3,"below-policy":4,"monitor":5}


def validate_archive(db, app, version):
    if db.in_transaction:
        raise ValueError("Independent read connection required")
    db.execute("PRAGMA query_only=ON")
    if (db.execute("PRAGMA application_id").fetchone()[0],db.execute("PRAGMA user_version").fetchone()[0])!=(app,version):
        raise ValueError("Unexpected evidence archive schema")


def prioritize(alerts,bridge,commercial,*,archive_ref,threshold,store,now,
               min_score_bps,min_margin_bps,after="",limit=MAX_PRODUCTS):
    """One bounded page of candidate identities with unresolved archived alerts.

    Policy thresholds are explicit; no commercial approval or purchasing decision
    is issued. Multiple current links require operator selection, not best-score picking.
    """
    now=instant(now)
    if len({id(alerts),id(bridge),id(commercial)})!=3:
        raise ValueError("Three independent archives required")
    if not isinstance(store,str) or not re.fullmatch(r"[1-9][0-9]{0,9}",store):
        raise ValueError("Invalid store")
    if not isinstance(after,str) or (after and not re.fullmatch(r"[1-9][0-9]{0,29}",after)):
        raise ValueError("Invalid product cursor")
    if type(limit) is not int or not 1<=limit<=MAX_PRODUCTS:
        raise ValueError("Invalid batch limit")
    if type(min_score_bps) is not int or not 1<=min_score_bps<=10000 or type(min_margin_bps) is not int or not 1<=min_margin_bps<=10000:
        raise ValueError("Explicit score and contribution thresholds required")
    ledger=AlertLedger.reader(alerts,archive_ref,threshold)
    validate_archive(bridge,APP_ID,1)
    validate_archive(commercial,APPLICATION_ID,SCHEMA_VERSION)
    alerts.execute("BEGIN")
    try:
        ids=[r[0] for r in alerts.execute("""SELECT DISTINCT product FROM alerts
            WHERE store=? AND product>? ORDER BY product LIMIT ?""",(store,after,limit+1))]
        more=len(ids)>limit
        ids=ids[:limit]
        items=[]
        for product in ids:
            records=alerts.execute("SELECT id FROM alerts WHERE store=? AND product=? ORDER BY id LIMIT ?",
                                   (store,product,MAX_ALERTS_PER_PRODUCT+1)).fetchall()
            if len(records)>MAX_ALERTS_PER_PRODUCT:
                raise ValueError("Product alert history exceeds review budget")
            histories=[ledger.history(sid) for sid, in records]
            unresolved=[]
            for h in histories:
                if h["state"]=="resolved":
                    continue
                s=h["alert"]["signal"]
                if s["store_id"]!=store or s["external_id"]!=product:
                    raise ValueError("Alert identity mismatch")
                if instant(datetime.fromisoformat(h["alert"]["first_seen"]))>now or any(instant(datetime.fromisoformat(e["at"]))>now for e in h["events"]):
                    raise ValueError("Future alert history")
                unresolved.append({"signal_id":s["signal_id"],"code":s["code"],"priority":s["priority"],
                    "field":s["field"],"captured_at":s["captured_at"],"previous_at":s["previous_at"],
                    "state":h["state"],"alert_sha256":h["alert_sha256"],
                    "latest_event_sha256":h["latest_event_sha256"]})
            if not unresolved:
                continue
            # Establish current local observation and its preceding observation,
            # including source page provenance. A later capture supersedes a signal
            # for ranking, but never silently closes its historical alert.
            bridge.execute("BEGIN")
            try:
                recent=bridge.execute("""SELECT at,payload FROM observations WHERE store=? AND id=?
                    ORDER BY at DESC LIMIT 2""",(store,product)).fetchall()
                if not recent:
                    raise ValueError("Alert observation absent from evidence archive")
                at=timestamp(recent[0][0])
                row=row_data(store,product,at,recent[0][1],now)
                pages=page_refs(bridge,store,product,recent[0][0])
                if len(recent)==2:
                    previous_at=timestamp(recent[1][0]).isoformat()
                    row_data(store,product,timestamp(recent[1][0]),recent[1][1],now)
                    page_refs(bridge,store,product,recent[1][0])
                else:
                    previous_at=None
                links=[x[0] for x in bridge.execute("""SELECT id FROM score_links
                    WHERE store=? AND product_id=? AND at=? ORDER BY id LIMIT 2""",(store,product,at.isoformat()))]
            finally:
                bridge.rollback()
            for s in unresolved:
                s["current_pair"]=(s["captured_at"],s["previous_at"])==(at.isoformat(),previous_at)
            current=[s for s in unresolved if s["current_pair"]]
            historical=[s for s in unresolved if not s["current_pair"]]
            reasons=[]
            if at>now or now-at>=timedelta(hours=24):
                reasons.append("capture-not-fresh")
            if row["type"]!="simple" or row["simple_stock"] is None or row["simple_stock"]<=0:
                reasons.append("positive-simple-stock-not-reported")
            if any(s["priority"]=="review-first" for s in current):
                reasons.append("unresolved-current-risk")
            historic_risk=any(s["priority"]=="review-first" for s in historical)
            opportunity=any(s["code"]=="stock-reappeared" or
                (s["code"]=="price-decreased" and s["field"]=="base_price") for s in current)
            evaluation=None
            if reasons:
                bucket="urgent-review"
            elif historic_risk:
                bucket="historical-risk-review"
                reasons.append("unresolved-historical-risk")
            elif not current:
                bucket="monitor"
                reasons.append("historical-alerts-only")
            elif len(links)!=1:
                bucket="evidence-review"
                reasons.append("current-evaluation-missing" if not links else "multiple-current-links")
            else:
                try:
                    d=get_dossier(bridge,commercial,links[0],now=now)
                    c=d["catalog"]
                    if (c["store_id"],c["external_id"],c["captured_at"],c["sku"],c["title"],
                        c["simple_stock_reported"],c["base_price_reported"],c["suggested_price_reported"])!=(
                        store,product,at.isoformat(),row["sku"],row["title"],row["simple_stock"],row["base_price"],row["suggested_price"]):
                        raise ValueError("Current evidence changed")
                    if now>=instant(datetime.fromisoformat(d["valid_until"])):
                        raise ValueError("Dossier expired")
                    e=d["evaluation"]
                    sale=e["economics"]["sale_price_minor"]
                    contribution=e["contribution_minor"]
                    score=Decimal(e["score"])
                    if type(sale) is not int or sale<=0 or type(contribution) is not int or not score.is_finite():
                        raise ValueError("Invalid scenario")
                    # Exact integer ratio for margin gate; rounded display is not
                    # used to promote a candidate over the threshold.
                    margin_pass=contribution*10000>=sale*min_margin_bps
                    score_pass=score*100>=min_score_bps
                    evaluation={"id":e["id"],"sha256":e["sha256"],"link_id":links[0],
                        "score":e["score"],"contribution_minor":contribution,"sale_price_minor":sale,
                        "margin_pct":e["margin_pct"],"currency":e["currency"],"valid_until":d["valid_until"]}
                    if not score_pass or not margin_pass:
                        bucket="below-policy"
                        if not score_pass:
                            reasons.append("score-below-threshold")
                        if not margin_pass:
                            reasons.append("contribution-below-threshold")
                    elif opportunity:
                        bucket="candidate-for-review"
                        reasons.append("current-signal-and-revalidated-scenario")
                    else:
                        bucket="monitor"
                        reasons.append("no-current-opportunity-signal")
                except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
                    bucket="evidence-review"
                    evaluation=None
                    reasons.append("evaluation-not-revalidated")
            items.append({"external_id":product,"sku":row["sku"],"title":row["title"],
                "captured_at":at.isoformat(),"simple_stock_reported":row["simple_stock"],
                "current_page_sha256":[p["page_sha256"] for p in pages],
                "bucket":bucket,"reasons":reasons,"current_opportunity_signal":opportunity,
                "unresolved_alerts":unresolved,"evaluation":evaluation})
        def sort_key(item):
            e=item["evaluation"]
            # Compare scores and exact margin only within the same review bucket.
            # Missing evidence never gets an invented numeric score.
            return (ORDER[item["bucket"]],e is None,
                    -Decimal(e["score"]) if e else Decimal(0),
                    -Decimal(e["contribution_minor"])/Decimal(e["sale_price_minor"]) if e else Decimal(0),
                    item["external_id"])
        items.sort(key=sort_key)
        counts={bucket:sum(i["bucket"]==bucket for i in items) for bucket in ORDER}
        return {"schema":"bakata-commercial-priority-v1","archive_ref":archive_ref,"store_id":store,
                "as_of":now.isoformat(),"policy":{"price_threshold_bps":threshold,
                "min_score_bps":min_score_bps,"min_margin_bps":min_margin_bps},
                "counts":counts,"scanned_products":len(ids),"items":items,
                "next_after":ids[-1] if more else None,"global_ranking":False,
                "approval_granted":False,"availability_verified":False,
                "provider_queries":0,"woo_mutation":False}
    finally:
        alerts.rollback()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("alerts","bridge","commercial"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--archive-ref",required=True)
    p.add_argument("--store",required=True)
    for name in ("price-threshold-bps","min-score-bps","min-margin-bps"):
        p.add_argument("--"+name,type=int,required=True)
    p.add_argument("--after",default="")
    p.add_argument("--limit",type=int,default=MAX_PRODUCTS)
    a=p.parse_args()
    paths=(a.alerts,a.bridge,a.commercial)
    if not all(x.is_file() and not x.is_symlink() for x in paths) or any(x.samefile(y) for i,x in enumerate(paths) for y in paths[i+1:]):
        p.error("Three existing distinct private archives required")
    try:
        with closing(sqlite3.connect(a.alerts.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as alerts, closing(sqlite3.connect(a.bridge.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as bridge, closing(sqlite3.connect(a.commercial.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as commercial:
            result=prioritize(alerts,bridge,commercial,archive_ref=a.archive_ref,threshold=a.price_threshold_bps,
                store=a.store,now=datetime.now(timezone.utc),min_score_bps=a.min_score_bps,
                min_margin_bps=a.min_margin_bps,after=a.after,limit=a.limit)
            print(encode(result))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,sqlite3.Error):
        p.exit(1,"Prioritization blocked: review archive integrity, scope and policy privately.\n")


if __name__=="__main__":
    main()
