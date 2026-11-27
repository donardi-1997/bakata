"""Offline notification intent queue and isolated delivery rehearsal.

No external transport, destination address, supplier request or automatic scheduler.
"""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import os
import re
import sqlite3

from .alert_ledger import digest, hex_id, read_payload, store_id
from .commercial_priority import prioritize
from .storage import encode, instant, ref

APP_ID=0x424B4435
MAX_INTENTS=20000
MAX_BYTES=32768
NOTIFIABLE={"urgent-review":"urgent","historical-risk-review":"high",
            "candidate-for-review":"review"}
RESULTS=("simulated","suppressed","expired")


class Outbox:
    def __init__(self,db,*,archive_ref,threshold,min_score_bps,min_margin_bps,daily_limit):
        self.db=db
        self.archive_ref=ref(archive_ref)
        values=(threshold,min_score_bps,min_margin_bps,daily_limit)
        if any(type(v) is not int for v in values) or not all(1<=v<=10000 for v in values[:3]) or not 1<=daily_limit<=100:
            raise ValueError("Explicit bounded notification policy required")
        self.policy={"threshold":threshold,"min_score_bps":min_score_bps,"min_margin_bps":min_margin_bps}
        self.daily_limit=daily_limit
        if db.in_transaction:
            raise ValueError("Independent outbox required")
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        with db:
            db.execute("BEGIN IMMEDIATE")
            app=db.execute("PRAGMA application_id").fetchone()[0]
            ver=db.execute("PRAGMA user_version").fetchone()[0]
            scope=encode({"archive_ref":self.archive_ref,"policy":self.policy,"daily_limit":daily_limit})
            if (app,ver)==(0,0):
                if db.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
                    raise ValueError("Unrecognized outbox")
                db.execute("CREATE TABLE scope (payload TEXT PRIMARY KEY)")
                db.execute("INSERT INTO scope VALUES (?)",(scope,))
                db.execute("""CREATE TABLE intents (
                    id TEXT PRIMARY KEY, store TEXT NOT NULL, day TEXT NOT NULL,
                    payload TEXT NOT NULL, digest TEXT NOT NULL)""")
                db.execute("CREATE INDEX intents_store_day ON intents(store,day,id)")
                db.execute("""CREATE TABLE receipts (
                    id TEXT PRIMARY KEY REFERENCES intents(id),payload TEXT NOT NULL,digest TEXT NOT NULL)""")
                for table in ("scope","intents","receipts"):
                    for action in ("UPDATE","DELETE"):
                        db.execute(f"""CREATE TRIGGER immutable_{table}_{action.lower()}
                            BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Append-only outbox'); END""")
                db.execute(f"PRAGMA application_id={APP_ID}")
                db.execute("PRAGMA user_version=1")
            elif (app,ver)!=(APP_ID,1):
                raise ValueError("Unsupported outbox")
            if db.execute("SELECT payload FROM scope").fetchall()!=[(scope,)]:
                raise ValueError("Outbox scope or policy differs")
            cap=128*1024*1024//db.execute("PRAGMA page_size").fetchone()[0]
            if db.execute(f"PRAGMA max_page_count={cap}").fetchone()[0]>cap:
                raise ValueError("Outbox storage budget exceeded")

    def report(self,alerts,bridge,commercial,*,store,now,after="",limit=25):
        if any(self.db is x for x in (alerts,bridge,commercial)):
            raise ValueError("Separate outbox required")
        return prioritize(alerts,bridge,commercial,archive_ref=self.archive_ref,
            store=store,now=now,after=after,limit=limit,**self.policy)

    def collect(self,alerts,bridge,commercial,*,store,now,after="",limit=25):
        now=instant(now)
        store_id(store)
        if self.db.in_transaction:
            raise ValueError("Independent write transaction required")
        report=self.report(alerts,bridge,commercial,store=store,now=now,after=after,limit=limit)
        day=now.date().isoformat()
        counts={"inserted":0,"duplicates":0,"rate_limited":0,"not_notifiable":0}
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            total=self.db.execute("SELECT COUNT(*) FROM intents").fetchone()[0]
            today=self.db.execute("SELECT COUNT(*) FROM intents WHERE store=? AND day=?",(store,day)).fetchone()[0]
            for item in report["items"]:
                bucket=item["bucket"]
                if bucket not in NOTIFIABLE:
                    counts["not_notifiable"]+=1
                    continue
                # One intent per observation and review category, irrespective of
                # repeated scans, clock time or an acknowledgement of the same alert.
                key=["bakata-notification-intent-v1",self.archive_ref,store,item["external_id"],item["captured_at"],bucket]
                nid=digest(key)
                if self.db.execute("SELECT 1 FROM intents WHERE id=?",(nid,)).fetchone():
                    self.get(nid)
                    counts["duplicates"]+=1
                    continue
                if today+counts["inserted"]>=self.daily_limit:
                    counts["rate_limited"]+=1
                    continue
                if total+counts["inserted"]>=MAX_INTENTS:
                    raise ValueError("Outbox capacity reached")
                expires=now+timedelta(hours=1)
                if item["evaluation"] is not None:
                    expires=min(expires,instant(datetime.fromisoformat(item["evaluation"]["valid_until"])))
                if expires<=now:
                    raise ValueError("Expired intent evidence")
                # Minimize delivery data. No titles, supplier details, prices,
                # credentials, raw evidence or recipient addresses.
                payload={"schema":"bakata-notification-intent-v1","id":nid,"archive_ref":self.archive_ref,
                    "store_id":store,"external_id":item["external_id"],"captured_at":item["captured_at"],
                    "bucket":bucket,"urgency":NOTIFIABLE[bucket],"evidence_sha256":digest(item),
                    "created_at":now.isoformat(),"expires_at":expires.isoformat(),"delivery_enabled":False}
                raw=encode(payload)
                if len(raw.encode())>MAX_BYTES:
                    raise ValueError("Intent exceeds size limit")
                self.db.execute("INSERT INTO intents VALUES (?,?,?,?,?)",(nid,store,day,raw,digest(payload)))
                counts["inserted"]+=1
        return {"schema":"bakata-outbox-collection-v1","counts":counts,"next_after":report["next_after"],
                "delivery_enabled":False,"notifications_sent":0,"woo_mutation":False}

    def get(self,nid):
        row=self.db.execute("SELECT store,day,payload,digest FROM intents WHERE id=?",(hex_id(nid),)).fetchone()
        if row is None:
            raise ValueError("Unknown intent")
        store,day,raw,sha=row
        p=read_payload(raw,sha)
        key=["bakata-notification-intent-v1",self.archive_ref,store,p["external_id"],p["captured_at"],p["bucket"]]
        if p["id"]!=nid or digest(key)!=nid or p["store_id"]!=store or p["archive_ref"]!=self.archive_ref or p["urgency"]!=NOTIFIABLE[p["bucket"]] or p["delivery_enabled"] is not False or instant(datetime.fromisoformat(p["created_at"])).date().isoformat()!=day:
            raise ValueError("Intent integrity failure")
        receipt=self.db.execute("SELECT payload,digest FROM receipts WHERE id=?",(nid,)).fetchone()
        result=None
        if receipt:
            result=read_payload(*receipt)
            if result["intent_id"]!=nid or result["intent_sha256"]!=sha or result["result"] not in RESULTS or result["external_delivery"] is not False:
                raise ValueError("Receipt integrity failure")
        return {"intent":p,"intent_sha256":sha,"state":result["result"] if result else "pending","receipt":result}

    def list(self,*,store,after="",limit=50):
        store_id(store)
        if after:
            hex_id(after)
        if type(limit) is not int or not 1<=limit<=100 or self.db.in_transaction:
            raise ValueError("Invalid outbox page")
        self.db.execute("BEGIN")
        try:
            ids=[r[0] for r in self.db.execute("SELECT id FROM intents WHERE store=? AND id>? ORDER BY id LIMIT ?",(store,after,limit+1))]
            return {"items":[self.get(nid) for nid in ids[:limit]],
                    "next_after":ids[limit-1] if len(ids)>limit else None,"delivery_enabled":False}
        finally:
            self.db.rollback()

    def rehearse(self,alerts,bridge,commercial,*,nid,now,expected_sha256):
        """Terminal local receipt only. Never send or retry a message."""
        now=instant(now)
        hex_id(expected_sha256)
        if os.environ.get("BAKATA_CI_FIXTURES")!="1" or not self.archive_ref.startswith("fixture-"):
            raise ValueError("Delivery rehearsal restricted to synthetic fixtures")
        if self.db.in_transaction or any(self.db is x for x in (alerts,bridge,commercial)):
            raise ValueError("Independent outbox required")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            h=self.get(nid)
            if h["intent_sha256"]!=expected_sha256 or h["state"]!="pending":
                raise ValueError("Changed or already handled intent")
            p=h["intent"]
            if now<instant(datetime.fromisoformat(p["created_at"])):
                raise ValueError("Rehearsal precedes intent")
            if now>=instant(datetime.fromisoformat(p["expires_at"])):
                result="expired"
            else:
                # Select the exact product with the same lexicographic cursor
                # used by prioritize, rather than accepting an uploaded report.
                from .alert_ledger import AlertLedger
                AlertLedger.reader(alerts,self.archive_ref,self.policy["threshold"])
                prior=alerts.execute("SELECT MAX(product) FROM alerts WHERE store=? AND product<?",
                    (p["store_id"],p["external_id"])).fetchone()[0] or ""
                report=self.report(alerts,bridge,commercial,store=p["store_id"],now=now,after=prior,limit=1)
                items=report["items"]
                result="simulated" if len(items)==1 and items[0]["external_id"]==p["external_id"] and digest(items[0])==p["evidence_sha256"] else "suppressed"
            receipt={"schema":"bakata-notification-rehearsal-v1","intent_id":nid,
                     "intent_sha256":expected_sha256,"result":result,"at":now.isoformat(),"external_delivery":False}
            self.db.execute("INSERT INTO receipts VALUES (?,?,?)",(nid,encode(receipt),digest(receipt)))
            return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--outbox",required=True,type=Path)
    p.add_argument("--archive-ref",required=True)
    for name in ("price-threshold-bps","min-score-bps","min-margin-bps","daily-limit"):
        p.add_argument("--"+name,required=True,type=int)
    sub=p.add_subparsers(dest="command",required=True)
    collect=sub.add_parser("collect")
    listing=sub.add_parser("list")
    rehearse=sub.add_parser("rehearse")
    for cmd in (collect,rehearse):
        for name in ("alerts","bridge","commercial"):
            cmd.add_argument("--"+name,required=True,type=Path)
    for cmd in (collect,listing):
        cmd.add_argument("--store",required=True)
        cmd.add_argument("--after",default="")
        cmd.add_argument("--limit",type=int,default=25)
    rehearse.add_argument("--intent-id",required=True)
    rehearse.add_argument("--expected-sha256",required=True)
    a=p.parse_args()
    if a.outbox.is_symlink() or (a.command!="collect" and not a.outbox.is_file()):
        p.error("Private outbox required")
    sources=() if a.command=="list" else (a.alerts,a.bridge,a.commercial)
    paths=(a.outbox,*sources)
    if not all(x.is_file() and not x.is_symlink() for x in sources) or len({x.resolve() for x in paths})!=len(paths):
        p.error("Distinct private archives required")
    existing=[x for x in paths if x.exists()]
    if any(x.samefile(y) for i,x in enumerate(existing) for y in existing[i+1:]):
        p.error("Archive paths alias")
    os.umask(0o077)
    from contextlib import ExitStack
    try:
        with ExitStack() as stack:
            db=stack.enter_context(closing(sqlite3.connect(a.outbox,timeout=5)))
            outbox=Outbox(db,archive_ref=a.archive_ref,threshold=a.price_threshold_bps,
                min_score_bps=a.min_score_bps,min_margin_bps=a.min_margin_bps,daily_limit=a.daily_limit)
            now=datetime.now(timezone.utc)
            if a.command=="list":
                result=outbox.list(store=a.store,after=a.after,limit=a.limit)
            else:
                connections=[stack.enter_context(closing(sqlite3.connect(x.resolve().as_uri()+"?mode=ro",uri=True,timeout=5))) for x in sources]
                if a.command=="collect":
                    result=outbox.collect(*connections,store=a.store,now=now,after=a.after,limit=a.limit)
                else:
                    result=outbox.rehearse(*connections,nid=a.intent_id,expected_sha256=a.expected_sha256,now=now)
            print(encode(result))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,sqlite3.Error):
        p.exit(1,"Outbox blocked: review policy, evidence and receipts privately.\n")


if __name__=="__main__":
    main()
