"""Offline radar of observed catalog changes, not a supplier monitor or profit forecast."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .dropify_bridge import APP_ID, decode, MAX_CATALOG_PAGE
from .dropify_catalog import unique
from .storage import encode, instant

SCHEMA = "bakata-opportunity-radar-v1"
MAX_BATCH = 100
PRIORITY = {"review-first": 0, "review": 1, "informational": 2}


def timestamp(value):
    at = instant(datetime.fromisoformat(value))
    if at.isoformat() != value or at.microsecond:
        raise ValueError("Invalid observation timestamp")
    return at


def row_data(store, product, at, raw, now):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 32768:
        raise ValueError("Invalid observation payload")
    row = json.loads(raw, object_pairs_hook=unique)
    # Validate with the existing projection contract. Future observations are
    # classified separately; the synthetic page must never be used as provenance.
    sample = {"schema":"bakata-dropify-bridge-v1", "captured_at":at.strftime("%Y-%m-%dT%H:%M:%SZ"),
              "store_id":store,"page":1,"page_size":1,"offset":0,"possible_next":True,
              "rows":[row],"approval_ref":"contract-check","query_sha256":"0"*64}
    decode(encode(sample).encode("utf-8"),max(now,at))
    if row["external_id"] != product:
        raise ValueError("Observation identity mismatch")
    return row


def page_refs(db, store, product, at):
    rows=db.execute("""SELECT p.sha,p.approval_ref,p.query_sha256,p.page,p.size,p.at,p.store
        FROM page_rows r JOIN pages p ON p.sha=r.sha WHERE r.store=? AND r.id=? AND r.at=?
        ORDER BY p.sha LIMIT 21""",(store,product,at)).fetchall()
    if not 1<=len(rows)<=20:
        raise ValueError("Missing or excessive observation provenance")
    result=[]
    for sha,approval,query,page,size,p_at,p_store in rows:
        if (p_at,p_store)!=(at,store) or not re.fullmatch(r"[0-9a-f]{64}",sha) or not re.fullmatch(r"[0-9a-f]{64}",query) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}",approval) or type(page) is not int or not 1<=page<=MAX_CATALOG_PAGE or type(size) is not int or not 1<=size<=20:
            raise ValueError("Inconsistent page provenance")
        result.append({"page_sha256":sha,"approval_ref":approval,"query_sha256":query,"page":page,"page_size":size})
    return result


def price_change(old,new,threshold):
    if old is None or new is None:
        if old==new:
            return None
        return ("price-reported" if new is not None else "price-unknown",None)
    a,b=Decimal(old),Decimal(new)
    if a==b:
        return None
    if a==0:
        return ("price-from-zero",None)
    # Exact threshold comparison; percent is descriptive and rounded only for display.
    if abs(b-a)*10000<a*threshold:
        return None
    pct=((b-a)*100/a).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
    return ("price-increased" if b>a else "price-decreased",str(pct))


def scan(db, *, store, now, price_threshold_bps, after="", limit=MAX_BATCH):
    """Scan one deterministic batch of identities, comparing the latest two observations.

    Missing products on later pages are not delistings. Changes are between
    observed instants, not continuous history. No score or cost is inferred.
    """
    now=instant(now)
    if not isinstance(store,str) or not re.fullmatch(r"[1-9][0-9]{0,9}",store):
        raise ValueError("Select an exact local store")
    if not isinstance(after,str) or (after and not re.fullmatch(r"[1-9][0-9]{0,29}",after)):
        raise ValueError("Invalid cursor")
    if type(limit) is not int or not 1<=limit<=MAX_BATCH or type(price_threshold_bps) is not int or not 1<=price_threshold_bps<=10000:
        raise ValueError("Explicit bounded threshold and batch size required")
    if db.in_transaction:
        raise ValueError("Independent read connection required")
    db.execute("PRAGMA query_only=ON")
    db.execute("BEGIN")
    try:
        if (db.execute("PRAGMA application_id").fetchone()[0],db.execute("PRAGMA user_version").fetchone()[0])!=(APP_ID,1):
            raise ValueError("Unknown bridge archive")
        ids=[r[0] for r in db.execute("""SELECT DISTINCT id FROM observations
            WHERE store=? AND id>? ORDER BY id LIMIT ?""",(store,after,limit+1))]
        has_more=len(ids)>limit
        ids=ids[:limit]
        signals=[]
        counts={"scanned":len(ids),"single_observation":0,"comparable_pairs":0,
                "stale_or_future":0,"identity_changed":0,"baseline_too_old":0}
        for product in ids:
            records=db.execute("""SELECT at,payload FROM observations
                WHERE store=? AND id=? ORDER BY at DESC LIMIT 2""",(store,product)).fetchall()
            current_at=timestamp(records[0][0])
            current=row_data(store,product,current_at,records[0][1],now)
            prior_at=timestamp(records[1][0]) if len(records)==2 else None
            prior=row_data(store,product,prior_at,records[1][1],now) if prior_at else None
            if prior_at is not None and prior_at>=current_at:
                raise ValueError("Non-increasing observation chronology")
            current_pages=page_refs(db,store,product,records[0][0])
            prior_pages=page_refs(db,store,product,records[1][0]) if prior_at else []
            def emit(code,priority,field=None,old=None,new=None,pct=None):
                signal_key=[SCHEMA,store,product,current_at.isoformat(),prior_at.isoformat() if prior_at else None,code,field]
                signals.append({"signal_id":hashlib.sha256(encode(signal_key).encode()).hexdigest(),
                    "store_id":store,"external_id":product,"sku":current["sku"],"title":current["title"],
                    "code":code,"priority":priority,"field":field,"previous":old,"current":new,
                    "change_pct":pct,"captured_at":current_at.isoformat(),
                    "previous_at":prior_at.isoformat() if prior_at else None,
                    "current_pages":current_pages,"previous_pages":prior_pages})
            if not timedelta(0)<=now-current_at<=timedelta(hours=24):
                counts["stale_or_future"]+=1
                emit("capture-future" if current_at>now else "capture-stale","review-first")
                continue
            # A historical link is not a current, revalidated commercial evaluation.
            has_current_link=db.execute("""SELECT 1 FROM score_links
                WHERE store=? AND product_id=? AND at=? LIMIT 1""",(store,product,records[0][0])).fetchone()
            has_old_link=db.execute("""SELECT 1 FROM score_links
                WHERE store=? AND product_id=? AND at<? LIMIT 1""",(store,product,records[0][0])).fetchone()
            if has_old_link and not has_current_link:
                emit("evaluation-observation-superseded","review-first")
            if not prior_at:
                counts["single_observation"]+=1
                emit("first-observation","informational")
                continue
            if current_at-prior_at>timedelta(days=30):
                counts["baseline_too_old"]+=1
                emit("baseline-too-old","review")
                continue
            changed=[field for field in ("sku","type","warehouse") if prior[field]!=current[field]]
            if changed:
                counts["identity_changed"]+=1
                for field in changed:
                    emit("comparison-scope-changed","review-first",field,prior[field],current[field])
                continue
            counts["comparable_pairs"]+=1
            for field in ("base_price","suggested_price"):
                change=price_change(prior[field],current[field],price_threshold_bps)
                if change:
                    code,pct=change
                    emit(code,"review-first" if code in ("price-increased","price-unknown","price-from-zero") else "review",
                         field,prior[field],current[field],pct)
            old,new=prior["simple_stock"],current["simple_stock"]
            if old!=new:
                if new is None:
                    emit("stock-unknown","review-first","simple_stock",old,new)
                elif old is None:
                    emit("stock-reported","review","simple_stock",old,new)
                elif new==0:
                    emit("stock-zero","review-first","simple_stock",old,new)
                elif old==0:
                    emit("stock-reappeared","review","simple_stock",old,new)
                else:
                    emit("stock-changed","informational","simple_stock",old,new)
        signals.sort(key=lambda s:(PRIORITY[s["priority"]],s["external_id"],s["code"],s["field"] or ""))
        return {"schema":SCHEMA,"as_of":now.isoformat(),"store_id":store,
                "price_threshold_bps":price_threshold_bps,"counts":counts,"signals":signals,
                "next_after":ids[-1] if has_more else None,"coverage_verified":False,
                "supplier_cost_verified":False,"profitability_verified":False,
                "availability_verified":False,"provider_queries":0,"woo_mutation":False}
    finally:
        db.rollback()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",required=True,type=Path)
    p.add_argument("--store",required=True)
    p.add_argument("--price-threshold-bps",required=True,type=int)
    p.add_argument("--after",default="")
    p.add_argument("--limit",default=MAX_BATCH,type=int)
    a=p.parse_args()
    if not a.db.is_file():
        p.error("Existing bridge archive required")
    try:
        with closing(sqlite3.connect(a.db.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
            print(encode(scan(db,store=a.store,now=datetime.now(timezone.utc),
                price_threshold_bps=a.price_threshold_bps,after=a.after,limit=a.limit)))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,sqlite3.Error):
        p.exit(1,"Radar blocked: review archived observations and provenance privately.\n")


if __name__=="__main__":
    main()
