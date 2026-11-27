"""Bounded read-only export of an alert ledger page for WordPress review."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from .alert_ledger import AlertLedger, STATES
from .storage import encode, instant

MAX_BYTES=262144


def export(db, *, archive_ref, threshold, store, now, after="", limit=20):
    if type(limit) is not int or not 1<=limit<=20:
        raise ValueError("Dashboard accepts at most 20 alerts")
    now=instant(now)
    ledger=AlertLedger.reader(db,archive_ref,threshold)
    page=ledger.list(store=store,after=after,limit=limit)
    counts=dict.fromkeys(STATES,0)
    rows=[]
    for item in page["items"]:
        alert=item["alert"]
        s=alert["signal"]
        counts[item["state"]]+=1
        rows.append({"signal_id":s["signal_id"],"external_id":s["external_id"],
            "sku":s["sku"],"title":s["title"],"code":s["code"],"priority":s["priority"],
            "field":s["field"],"previous":s["previous"],"current":s["current"],
            "change_pct":s["change_pct"],"captured_at":s["captured_at"],"previous_at":s["previous_at"],
            "first_seen":alert["first_seen"],"state":item["state"],
            "alert_sha256":item["alert_sha256"],"latest_event_sha256":item["latest_event_sha256"],
            "current_pages":[p["page_sha256"] for p in s["current_pages"]],
            "previous_pages":[p["page_sha256"] for p in s["previous_pages"]]})
    result={"schema":"bakata-alert-dashboard-v1","mode":"historical-read-only",
            "archive_ref":archive_ref,"store_id":store,"price_threshold_bps":threshold,
            "exported_at":now.isoformat(),"counts":counts,"rows":rows,"next_after":page["next_after"],
            "delivery_enabled":False,"woo_mutation":False}
    raw=encode(result)
    if len(raw.encode("utf-8"))>MAX_BYTES:
        raise ValueError("Dashboard export exceeds size budget")
    return raw


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger",required=True,type=Path)
    p.add_argument("--archive-ref",required=True)
    p.add_argument("--price-threshold-bps",required=True,type=int)
    p.add_argument("--store",required=True)
    p.add_argument("--after",default="")
    p.add_argument("--limit",type=int,default=20)
    a=p.parse_args()
    if not a.ledger.is_file() or a.ledger.is_symlink():
        p.error("Existing private alert ledger required")
    try:
        with closing(sqlite3.connect(a.ledger.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as db:
            print(export(db,archive_ref=a.archive_ref,threshold=a.price_threshold_bps,
                store=a.store,now=datetime.now(timezone.utc),after=a.after,limit=a.limit))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,sqlite3.Error):
        p.exit(1,"Alert export blocked: review ledger integrity and scope.\n")


if __name__=="__main__":
    main()
