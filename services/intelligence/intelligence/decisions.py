"""Append-only offline commercial decisions; no WooCommerce or supplier actions."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from .linked_review import get_dossier
from .storage import encode, instant, ref

APP_ID = 0x424B4433
MAX_EVENTS = 20000
MAX_HISTORY = 100
ACTIONS = ("approve-for-draft-review", "reject", "defer")
ZERO = "0" * 64


def sha(value):
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def dossier_digest(dossier):
    # Export time changes on every revalidation; all other evidence remains bound.
    return sha({k:v for k,v in dossier.items() if k != "as_of"})


def require_digest(value):
    if not isinstance(value,str) or not re.fullmatch(r"[0-9a-f]{64}",value):
        raise ValueError("Explicit SHA-256 required")
    return value


def identity(dossier):
    c=dossier["catalog"]
    return c["store_id"],c["external_id"]


def key(store,product):
    if not isinstance(store,str) or not re.fullmatch(r"[1-9][0-9]{0,9}",store) or not isinstance(product,str) or not re.fullmatch(r"[1-9][0-9]{0,29}",product):
        raise ValueError("Invalid catalog identity")
    return store,product


class DecisionLedger:
    def __init__(self,db,archive_ref):
        self.db=db
        self.archive_ref=ref(archive_ref)
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
                    raise ValueError("Unrecognized decision database")
                db.execute("CREATE TABLE scope (archive_ref TEXT PRIMARY KEY)")
                db.execute("INSERT INTO scope VALUES (?)",(self.archive_ref,))
                db.execute("""CREATE TABLE decisions (
                    seq INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE,
                    store TEXT NOT NULL, product TEXT NOT NULL,
                    payload TEXT NOT NULL, digest TEXT NOT NULL UNIQUE)""")
                db.execute("CREATE INDEX decision_identity ON decisions(store,product,seq)")
                db.execute("""CREATE TRIGGER no_decision_update BEFORE UPDATE ON decisions
                    BEGIN SELECT RAISE(ABORT,'Append-only decision ledger'); END""")
                db.execute("""CREATE TRIGGER no_decision_delete BEFORE DELETE ON decisions
                    BEGIN SELECT RAISE(ABORT,'Append-only decision ledger'); END""")
                db.execute(f"PRAGMA application_id={APP_ID}")
                db.execute("PRAGMA user_version=1")
            elif (app,version)!=(APP_ID,1):
                raise ValueError("Unsupported decision database")
            if db.execute("SELECT archive_ref FROM scope").fetchall()!=[(self.archive_ref,)]:
                raise ValueError("Ledger archive scope differs")
            cap=128*1024*1024//db.execute("PRAGMA page_size").fetchone()[0]
            if db.execute(f"PRAGMA max_page_count={cap}").fetchone()[0]>cap:
                raise ValueError("Ledger storage budget exceeded")

    def history(self,store,product):
        store,product=key(store,product)
        records=self.db.execute("""SELECT id,payload,digest FROM decisions
            WHERE store=? AND product=? ORDER BY seq LIMIT ?""",(store,product,MAX_HISTORY+1)).fetchall()
        if len(records)>MAX_HISTORY:
            raise ValueError("Decision history capacity exceeded")
        result=[]
        previous=ZERO
        last_at=None
        for event_id,raw,digest in records:
            if len(raw.encode("utf-8"))>32768:
                raise ValueError("Decision record too large")
            event=json.loads(raw)
            if (sha(event)!=digest or event["id"]!=event_id or event["previous_sha256"]!=previous
                or event["archive_ref"]!=self.archive_ref or (event["store_id"],event["external_id"])!=(store,product)):
                raise ValueError("Decision chain integrity failure")
            at=instant(datetime.fromisoformat(event["decided_at"]))
            if last_at is not None and at<last_at:
                raise ValueError("Decision chronology failure")
            result.append(dict(event,sha256=digest))
            previous=digest
            last_at=at
        return result

    def preview(self,bridge,commercial,link_id,*,now):
        if self.db is bridge or self.db is commercial:
            raise ValueError("Independent decision ledger required")
        dossier=get_dossier(bridge,commercial,link_id,now=now)
        history=self.history(*identity(dossier))
        return {"schema":"bakata-decision-preview-v1","archive_ref":self.archive_ref,
                "dossier":dossier,"dossier_sha256":dossier_digest(dossier),
                "previous_sha256":history[-1]["sha256"] if history else ZERO,
                "publication_authorized":False}

    def record(self,bridge,commercial,link_id,*,event_id,action,actor_ref,reason_ref,
               expected_dossier_sha256,expected_previous_sha256,now):
        event_id,actor_ref,reason_ref=map(ref,(event_id,actor_ref,reason_ref))
        if action not in ACTIONS:
            raise ValueError("Unsupported decision")
        require_digest(expected_dossier_sha256)
        require_digest(expected_previous_sha256)
        now=instant(now)
        if self.db is bridge or self.db is commercial:
            raise ValueError("Independent decision ledger required")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            # No mutation of either evidence archive. Revalidate from original sources
            # rather than trusting an uploaded or client-generated JSON dossier.
            dossier=get_dossier(bridge,commercial,link_id,now=now)
            if dossier_digest(dossier)!=expected_dossier_sha256:
                raise ValueError("Evidence differs from reviewed preview")
            if now>=instant(datetime.fromisoformat(dossier["valid_until"])):
                raise ValueError("Evidence validity exhausted")
            store,product=identity(dossier)
            history=self.history(store,product)
            previous=history[-1]["sha256"] if history else ZERO
            if previous!=expected_previous_sha256:
                raise ValueError("Decision changed; review latest history")
            if history and now<instant(datetime.fromisoformat(history[-1]["decided_at"])):
                raise ValueError("Decision time precedes history")
            if len(history)>=MAX_HISTORY or self.db.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]>=MAX_EVENTS:
                raise ValueError("Ledger capacity reached")
            if self.db.execute("SELECT 1 FROM decisions WHERE id=?",(event_id,)).fetchone():
                raise ValueError("Decision ID already used; inspect history")
            e=dossier["evaluation"]
            event={"schema":"bakata-commercial-decision-v1","id":event_id,
                   "archive_ref":self.archive_ref,"store_id":store,"external_id":product,
                   "captured_at":dossier["catalog"]["captured_at"],"link_id":dossier["link"]["id"],
                   "evaluation_id":e["id"],"evaluation_sha256":e["sha256"],
                   "dossier_sha256":expected_dossier_sha256,"previous_sha256":previous,
                   "actor_ref":actor_ref,"reason_ref":reason_ref,"action":action,
                   "decided_at":now.isoformat(),"valid_until":dossier["valid_until"],
                   "score":e["score"],"contribution_minor":e["contribution_minor"],
                   "currency":e["currency"],"publication_authorized":False,"woo_mutation":False}
            digest=sha(event)
            self.db.execute("INSERT INTO decisions(id,store,product,payload,digest) VALUES (?,?,?,?,?)",
                            (event_id,store,product,encode(event),digest))
            return dict(event,sha256=digest)

    def status(self,bridge,commercial,store,product,*,now):
        now=instant(now)
        history=self.history(store,product)
        if not history:
            return {"state":"undecided","draft_review_eligible":False,"publication_authorized":False}
        latest=history[-1]
        result={"state":latest["action"],"decision":latest,"draft_review_eligible":False,"publication_authorized":False}
        if latest["action"]!="approve-for-draft-review":
            return result
        try:
            if not instant(datetime.fromisoformat(latest["decided_at"]))<=now<instant(datetime.fromisoformat(latest["valid_until"])):
                raise ValueError("Expired decision")
            dossier=get_dossier(bridge,commercial,latest["link_id"],now=now)
            if identity(dossier)!=(store,product) or dossier_digest(dossier)!=latest["dossier_sha256"]:
                raise ValueError("Changed evidence")
        except (ValueError,TypeError,KeyError,AttributeError,OverflowError,sqlite3.Error):
            result["state"]="requires-revalidation"
            return result
        result["draft_review_eligible"]=True
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger",type=Path,required=True)
    parser.add_argument("--archive-ref",required=True)
    parser.add_argument("--bridge",type=Path,required=True)
    parser.add_argument("--commercial",type=Path,required=True)
    sub=parser.add_subparsers(dest="command",required=True)
    preview=sub.add_parser("preview")
    record=sub.add_parser("record")
    for command in (preview,record):
        command.add_argument("--link-id",required=True)
    record.add_argument("--event-id",required=True)
    record.add_argument("--action",required=True,choices=ACTIONS)
    record.add_argument("--actor-ref",required=True)
    record.add_argument("--reason-ref",required=True)
    record.add_argument("--expected-dossier-sha256",required=True)
    record.add_argument("--expected-previous-sha256",required=True)
    for command in (sub.add_parser("history"),sub.add_parser("status")):
        command.add_argument("--store",required=True)
        command.add_argument("--product-id",required=True)
    args=parser.parse_args()
    paths=(args.ledger,args.bridge,args.commercial)
    if not args.bridge.is_file() or not args.commercial.is_file() or len({p.resolve() for p in paths})!=3 or any(p.is_symlink() for p in paths):
        parser.error("Three distinct private archive paths required; evidence must exist")
    existing=[p for p in paths if p.exists()]
    if any(p.samefile(q) for i,p in enumerate(existing) for q in existing[i+1:]):
        parser.error("Archive paths alias each other")
    os.umask(0o077)
    now=datetime.now(timezone.utc)
    try:
        with closing(sqlite3.connect(args.ledger,timeout=5)) as db, closing(sqlite3.connect(args.bridge.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as bridge, closing(sqlite3.connect(args.commercial.resolve().as_uri()+"?mode=ro",uri=True,timeout=5)) as commercial:
            ledger=DecisionLedger(db,args.archive_ref)
            if args.command=="preview":
                result=ledger.preview(bridge,commercial,args.link_id,now=now)
            elif args.command=="record":
                result=ledger.record(bridge,commercial,args.link_id,event_id=args.event_id,action=args.action,
                    actor_ref=args.actor_ref,reason_ref=args.reason_ref,expected_dossier_sha256=args.expected_dossier_sha256,
                    expected_previous_sha256=args.expected_previous_sha256,now=now)
            elif args.command=="history":
                result=ledger.history(args.store,args.product_id)
            else:
                result=ledger.status(bridge,commercial,args.store,args.product_id,now=now)
            print(encode(result))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,sqlite3.Error):
        parser.exit(1,"Decision blocked: review archive, current evidence, history and supplied references privately.\n")


if __name__=="__main__":
    main()
