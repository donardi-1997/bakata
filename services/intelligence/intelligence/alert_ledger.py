"""Persist radar signals and explicit human triage. No delivery or supplier actions."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from .opportunity_radar import scan, PRIORITY
from .storage import encode, instant, ref
from .dropify_catalog import unique

APP_ID = 0x424B4434
MAX_ALERTS = 20000
MAX_EVENTS = 100000
MAX_HISTORY = 100
ZERO = "0"*64
STATES = ("open","acknowledged","resolved")
TRANSITIONS = {"open":("acknowledged","resolved"),"acknowledged":("open","resolved"),"resolved":("open",)}


def digest(data):
    return hashlib.sha256(encode(data).encode("utf-8")).hexdigest()


def hex_id(value):
    if not isinstance(value,str) or not re.fullmatch(r"[0-9a-f]{64}",value):
        raise ValueError("Expected SHA-256")
    return value


def store_id(value):
    if not isinstance(value,str) or not re.fullmatch(r"[1-9][0-9]{0,9}",value):
        raise ValueError("Invalid local store")
    return value


def read_payload(raw,sha):
    if not isinstance(raw,str) or len(raw.encode("utf-8"))>32768:
        raise ValueError("Invalid record size")
    data=json.loads(raw,object_pairs_hook=unique)
    if not isinstance(data,dict) or digest(data)!=sha:
        raise ValueError("Record integrity failure")
    return data


def signal_core(signal):
    # Additional archived page references may be discovered on replay.
    # Preserve the original evidence snapshot, not a mutable union.
    return {k:v for k,v in signal.items() if k not in ("current_pages","previous_pages")}


class AlertLedger:
    def __init__(self,db,archive_ref,threshold):
        self.db=db
        self.archive_ref=ref(archive_ref)
        if type(threshold) is not int or not 1<=threshold<=10000:
            raise ValueError("Explicit price threshold required")
        self.threshold=threshold
        if db.in_transaction:
            raise ValueError("Independent ledger connection required")
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        with db:
            db.execute("BEGIN IMMEDIATE")
            app=db.execute("PRAGMA application_id").fetchone()[0]
            version=db.execute("PRAGMA user_version").fetchone()[0]
            if (app,version)==(0,0):
                if db.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
                    raise ValueError("Unrecognized alert database")
                db.execute("CREATE TABLE scope (archive_ref TEXT PRIMARY KEY, threshold INTEGER NOT NULL)")
                db.execute("INSERT INTO scope VALUES (?,?)",(self.archive_ref,threshold))
                db.execute("""CREATE TABLE alerts (
                    id TEXT PRIMARY KEY, store TEXT NOT NULL, product TEXT NOT NULL,
                    priority INTEGER NOT NULL, first_seen TEXT NOT NULL,
                    payload TEXT NOT NULL, digest TEXT NOT NULL)""")
                db.execute("""CREATE TABLE events (
                    seq INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
                    alert_id TEXT NOT NULL REFERENCES alerts(id),
                    payload TEXT NOT NULL, digest TEXT NOT NULL UNIQUE)""")
                db.execute("CREATE INDEX alerts_store_order ON alerts(store,priority,id)")
                db.execute("CREATE INDEX events_alert_order ON events(alert_id,seq)")
                for table in ("alerts","events","scope"):
                    for action in ("UPDATE","DELETE"):
                        db.execute(f"""CREATE TRIGGER immutable_{table}_{action.lower()}
                            BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Append-only alert ledger'); END""")
                db.execute(f"PRAGMA application_id={APP_ID}")
                db.execute("PRAGMA user_version=1")
            elif (app,version)!=(APP_ID,1):
                raise ValueError("Unknown alert schema")
            if db.execute("SELECT archive_ref,threshold FROM scope").fetchall()!=[(self.archive_ref,threshold)]:
                raise ValueError("Alert scope or threshold differs")
            cap=192*1024*1024//db.execute("PRAGMA page_size").fetchone()[0]
            if db.execute(f"PRAGMA max_page_count={cap}").fetchone()[0]>cap:
                raise ValueError("Alert storage budget exceeded")

    @classmethod
    def reader(cls,db,archive_ref,threshold):
        """Open an existing ledger without initializing or migrating it."""
        archive_ref=ref(archive_ref)
        if db.in_transaction or type(threshold) is not int or not 1<=threshold<=10000:
            raise ValueError("Independent reader and explicit threshold required")
        db.execute("PRAGMA query_only=ON")
        if (db.execute("PRAGMA application_id").fetchone()[0],db.execute("PRAGMA user_version").fetchone()[0])!=(APP_ID,1):
            raise ValueError("Unknown alert schema")
        if db.execute("SELECT archive_ref,threshold FROM scope").fetchall()!=[(archive_ref,threshold)]:
            raise ValueError("Alert scope or threshold differs")
        instance=cls.__new__(cls)
        instance.db=db
        instance.archive_ref=archive_ref
        instance.threshold=threshold
        return instance

    def collect(self,bridge,*,store,now,after="",limit=100):
        """Generate signals directly from the archive, never trust uploaded reports."""
        if bridge is self.db or self.db.in_transaction:
            raise ValueError("Independent archive and ledger required")
        now=instant(now)
        report=scan(bridge,store=store,now=now,price_threshold_bps=self.threshold,after=after,limit=limit)
        inserted=replayed=0
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            total=self.db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
            for s in report["signals"]:
                sid=hex_id(s["signal_id"])
                old=self.db.execute("SELECT payload,digest,store,product,priority FROM alerts WHERE id=?",(sid,)).fetchone()
                if old is not None:
                    original=read_payload(old[0],old[1])
                    if signal_core(original["signal"])!=signal_core(s) or original["archive_ref"]!=self.archive_ref or old[2:]!=(store,s["external_id"],PRIORITY[s["priority"]]):
                        raise ValueError("Conflicting signal identity")
                    replayed+=1
                    continue
                if total+inserted>=MAX_ALERTS:
                    raise ValueError("Alert capacity reached")
                payload={"schema":"bakata-alert-v1","archive_ref":self.archive_ref,
                         "price_threshold_bps":self.threshold,"first_seen":now.isoformat(),"signal":s}
                raw=encode(payload)
                if len(raw.encode("utf-8"))>32768:
                    raise ValueError("Alert evidence too large")
                self.db.execute("INSERT INTO alerts VALUES (?,?,?,?,?,?,?)",
                    (sid,store,s["external_id"],PRIORITY[s["priority"]],now.isoformat(),raw,digest(payload)))
                inserted+=1
        return {"schema":"bakata-alert-collection-v1","archive_ref":self.archive_ref,
                "inserted":inserted,"replayed":replayed,"counts":report["counts"],
                "next_after":report["next_after"],"provider_queries":0,"notifications_sent":0,"woo_mutation":False}

    def _alert(self,alert_id):
        row=self.db.execute("SELECT store,product,priority,first_seen,payload,digest FROM alerts WHERE id=?",
                            (hex_id(alert_id),)).fetchone()
        if row is None:
            raise ValueError("Unknown alert")
        store,product,priority,first_seen,raw,sha=row
        data=read_payload(raw,sha)
        s=data["signal"]
        if (data["archive_ref"]!=self.archive_ref or data["price_threshold_bps"]!=self.threshold
            or data["first_seen"]!=first_seen or s["signal_id"]!=alert_id or s["store_id"]!=store
            or s["external_id"]!=product or PRIORITY[s["priority"]]!=priority):
            raise ValueError("Alert identity integrity failure")
        return data,sha

    def history(self,alert_id):
        alert,base_sha=self._alert(alert_id)
        rows=self.db.execute("""SELECT event_id,payload,digest FROM events WHERE alert_id=?
            ORDER BY seq LIMIT ?""",(alert_id,MAX_HISTORY+1)).fetchall()
        if len(rows)>MAX_HISTORY:
            raise ValueError("Alert history capacity exceeded")
        state="open"
        previous=ZERO
        at=instant(datetime.fromisoformat(alert["first_seen"]))
        result=[]
        for eid,raw,sha in rows:
            e=read_payload(raw,sha)
            new=e["to"]
            when=instant(datetime.fromisoformat(e["at"]))
            if (e["event_id"]!=eid or e["alert_id"]!=alert_id or e["alert_sha256"]!=base_sha
                or e["previous_sha256"]!=previous or e["from"]!=state or new not in TRANSITIONS[state]
                or when<at or e["archive_ref"]!=self.archive_ref):
                raise ValueError("Alert history integrity failure")
            result.append(dict(e,sha256=sha))
            state,previous,at=new,sha,when
        return {"alert":alert,"alert_sha256":base_sha,"state":state,"latest_event_sha256":previous,"events":result}

    def transition(self,alert_id,*,event_id,to,actor_ref,reason_ref,expected_previous_sha256,now):
        event_id,actor_ref,reason_ref=map(ref,(event_id,actor_ref,reason_ref))
        hex_id(expected_previous_sha256)
        now=instant(now)
        if to not in STATES or self.db.in_transaction:
            raise ValueError("Invalid transition")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            h=self.history(alert_id)
            if h["latest_event_sha256"]!=expected_previous_sha256:
                raise ValueError("Alert state changed; reload history")
            if to not in TRANSITIONS[h["state"]]:
                raise ValueError("Invalid state transition")
            last_at=h["events"][-1]["at"] if h["events"] else h["alert"]["first_seen"]
            if now<instant(datetime.fromisoformat(last_at)):
                raise ValueError("Transition precedes history")
            if len(h["events"])>=MAX_HISTORY or self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]>=MAX_EVENTS:
                raise ValueError("Event capacity reached")
            if self.db.execute("SELECT 1 FROM events WHERE event_id=?",(event_id,)).fetchone():
                raise ValueError("Event ID already used; inspect history")
            e={"schema":"bakata-alert-event-v1","archive_ref":self.archive_ref,"event_id":event_id,
               "alert_id":alert_id,"alert_sha256":h["alert_sha256"],"previous_sha256":expected_previous_sha256,
               "from":h["state"],"to":to,"at":now.isoformat(),"actor_ref":actor_ref,"reason_ref":reason_ref}
            sha=digest(e)
            self.db.execute("INSERT INTO events(event_id,alert_id,payload,digest) VALUES (?,?,?,?)",
                            (event_id,alert_id,encode(e),sha))
            return dict(e,sha256=sha)

    def list(self,*,store,after="",limit=50,state=""):
        store_id(store)
        if after:
            hex_id(after)
        if type(limit) is not int or not 1<=limit<=100 or state not in ("",*STATES):
            raise ValueError("Invalid alert listing")
        # Bounded identity-order page. The state filter applies to this page,
        # not all alerts; empty filtered pages may still have a next cursor.
        if self.db.in_transaction:
            raise ValueError("Independent read transaction required")
        self.db.execute("BEGIN")
        try:
            ids=[r[0] for r in self.db.execute("SELECT id FROM alerts WHERE store=? AND id>? ORDER BY id LIMIT ?",(store,after,limit+1))]
            more=len(ids)>limit
            ids=ids[:limit]
            items=[]
            for sid in ids:
                h=self.history(sid)
                if not state or h["state"]==state:
                    items.append({k:v for k,v in h.items() if k!="events"})
            items.sort(key=lambda h:(PRIORITY[h["alert"]["signal"]["priority"]],h["alert"]["signal"]["signal_id"]))
            return {"schema":"bakata-alert-list-v1","archive_ref":self.archive_ref,
                    "store_id":store,"scanned":len(ids),"items":items,"next_after":ids[-1] if more else None,
                    "delivery_enabled":False}
        finally:
            self.db.rollback()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger",required=True,type=Path)
    p.add_argument("--archive-ref",required=True)
    p.add_argument("--price-threshold-bps",required=True,type=int)
    sub=p.add_subparsers(dest="command",required=True)
    collect=sub.add_parser("collect")
    collect.add_argument("--bridge",required=True,type=Path)
    listing=sub.add_parser("list")
    for cmd in (collect,listing):
        cmd.add_argument("--store",required=True)
        cmd.add_argument("--after",default="")
        cmd.add_argument("--limit",type=int,default=50)
    listing.add_argument("--state",default="",choices=("",*STATES))
    history=sub.add_parser("history")
    change=sub.add_parser("transition")
    for cmd in (history,change):
        cmd.add_argument("--alert-id",required=True)
    change.add_argument("--event-id",required=True)
    change.add_argument("--to",required=True,choices=STATES)
    change.add_argument("--actor-ref",required=True)
    change.add_argument("--reason-ref",required=True)
    change.add_argument("--expected-previous-sha256",required=True)
    a=p.parse_args()
    if a.ledger.is_symlink():
        p.error("Private ledger path required")
    if a.command!="collect" and not a.ledger.is_file():
        p.error("Existing alert ledger required")
    if a.command=="collect" and (not a.bridge.is_file() or a.bridge.is_symlink()
        or a.ledger.resolve()==a.bridge.resolve() or (a.ledger.exists() and a.ledger.samefile(a.bridge))):
        p.error("Existing distinct evidence archive required")
    os.umask(0o077)
    try:
        with closing(sqlite3.connect(a.ledger,timeout=5)) as db:
            ledger=AlertLedger(db,a.archive_ref,a.price_threshold_bps)
            if a.command=="collect":
                with closing(sqlite3.connect(a.bridge.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as bridge:
                    result=ledger.collect(bridge,store=a.store,now=datetime.now(timezone.utc),after=a.after,limit=a.limit)
            elif a.command=="list":
                result=ledger.list(store=a.store,after=a.after,limit=a.limit,state=a.state)
            elif a.command=="history":
                result=ledger.history(a.alert_id)
            else:
                result=ledger.transition(a.alert_id,event_id=a.event_id,to=a.to,actor_ref=a.actor_ref,
                    reason_ref=a.reason_ref,expected_previous_sha256=a.expected_previous_sha256,now=datetime.now(timezone.utc))
            print(encode(result))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,sqlite3.Error):
        p.exit(1,"Alert operation blocked: review ledger, scope, evidence and history privately.\n")


if __name__=="__main__":
    main()
