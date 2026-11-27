"""Resumable offline prioritization batches, one explicit bounded step at a time."""
import argparse
from contextlib import closing, ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
from .alert_ledger import digest, hex_id, store_id
from .commercial_priority import prioritize
from .dropify_catalog import unique
from .storage import encode, instant, ref

APP_ID=0x424B4436
MAX_RUNS=50
MAX_PAGES=2000
MAX_PAGE_BYTES=1048576
MAX_BATCH=10
ZERO="0"*64


def cursor(value,empty=False):
    if not isinstance(value,str) or not ((empty and value=="") or re.fullmatch(r"[1-9][0-9]{0,29}",value)):
        raise ValueError("Invalid product cursor")
    return value


def decode(raw,sha):
    if not isinstance(raw,str) or len(raw.encode("utf-8"))>MAX_PAGE_BYTES:
        raise ValueError("Invalid batch record size")
    value=json.loads(raw,object_pairs_hook=unique)
    if not isinstance(value,dict) or digest(value)!=sha:
        raise ValueError("Batch record digest mismatch")
    return value


class BatchRuns:
    def __init__(self,db):
        if db.in_transaction:
            raise ValueError("Independent batch database required")
        self.db=db
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        with db:
            db.execute("BEGIN IMMEDIATE")
            app=db.execute("PRAGMA application_id").fetchone()[0]
            version=db.execute("PRAGMA user_version").fetchone()[0]
            if (app,version)==(0,0):
                if db.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
                    raise ValueError("Unrecognized batch database")
                db.execute("CREATE TABLE runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,digest TEXT NOT NULL)")
                db.execute("""CREATE TABLE pages (
                    run_id TEXT NOT NULL REFERENCES runs(id), seq INTEGER NOT NULL,
                    payload TEXT NOT NULL,digest TEXT NOT NULL,
                    PRIMARY KEY(run_id,seq))""")
                for table in ("runs","pages"):
                    for action in ("UPDATE","DELETE"):
                        db.execute(f"""CREATE TRIGGER immutable_{table}_{action.lower()}
                            BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Append-only batch archive'); END""")
                db.execute(f"PRAGMA application_id={APP_ID}")
                db.execute("PRAGMA user_version=1")
            elif (app,version)!=(APP_ID,1):
                raise ValueError("Unsupported batch database")
            cap=128*1024*1024//db.execute("PRAGMA page_size").fetchone()[0]
            if db.execute(f"PRAGMA max_page_count={cap}").fetchone()[0]>cap:
                raise ValueError("Batch archive storage budget exceeded")

    def create(self,run_id,*,archive_ref,store,threshold,min_score_bps,min_margin_bps,batch_size,source_ref,now):
        run_id,archive_ref,source_ref=map(ref,(run_id,archive_ref,source_ref))
        store_id(store)
        now=instant(now)
        if any(type(x) is not int or not 1<=x<=10000 for x in (threshold,min_score_bps,min_margin_bps)) or type(batch_size) is not int or not 1<=batch_size<=MAX_BATCH:
            raise ValueError("Explicit bounded batch policy required")
        data={"schema":"bakata-batch-run-v1","id":run_id,"archive_ref":archive_ref,"source_ref":source_ref,
              "store":store,"threshold":threshold,"min_score_bps":min_score_bps,"min_margin_bps":min_margin_bps,
              "batch_size":batch_size,"created_at":now.isoformat()}
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            existing=self.db.execute("SELECT payload,digest FROM runs WHERE id=?",(run_id,)).fetchone()
            if existing:
                old=decode(*existing)
                if {k:v for k,v in old.items() if k!="created_at"}!={k:v for k,v in data.items() if k!="created_at"}:
                    raise ValueError("Conflicting run identity")
                return False
            if self.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]>=MAX_RUNS:
                raise ValueError("Run capacity reached")
            self.db.execute("INSERT INTO runs VALUES (?,?,?)",(run_id,encode(data),digest(data)))
            return True

    def _run(self,run_id):
        row=self.db.execute("SELECT payload,digest FROM runs WHERE id=?",(ref(run_id),)).fetchone()
        if row is None:
            raise ValueError("Unknown batch run")
        data=decode(*row)
        if data["id"]!=run_id:
            raise ValueError("Run identity mismatch")
        return data,row[1]

    def _page(self,run_id,seq,run_sha):
        row=self.db.execute("SELECT payload,digest FROM pages WHERE run_id=? AND seq=?",(run_id,seq)).fetchone()
        if row is None:
            raise ValueError("Unknown batch page")
        data=decode(*row)
        if data["run_id"]!=run_id or data["sequence"]!=seq or data["run_sha256"]!=run_sha:
            raise ValueError("Page identity mismatch")
        return data,row[1]

    def status(self,run_id):
        run,run_sha=self._run(run_id)
        count,last=self.db.execute("SELECT COUNT(*),MAX(seq) FROM pages WHERE run_id=?",(run_id,)).fetchone()
        if count!=(last or 0) or count>MAX_PAGES:
            raise ValueError("Batch sequence mismatch")
        if count:
            page,sha=self._page(run_id,last,run_sha)
            if last==1:
                if page["previous_sha256"]!=ZERO or page["after"]!="":
                    raise ValueError("Invalid initial checkpoint")
            else:
                previous,prev_sha=self._page(run_id,last-1,run_sha)
                if page["previous_sha256"]!=prev_sha or previous["next_after"]!=page["after"]:
                    raise ValueError("Checkpoint chain mismatch")
            after=page["next_after"]
        else:
            sha=ZERO
            after=""
        return {"run":run,"run_sha256":run_sha,"pages":count,"checkpoint_sha256":sha,
                "next_after":after,"state":"completed" if after is None else "pending",
                "global_snapshot":False}

    def page(self,run_id,seq):
        if type(seq) is not int or not 1<=seq<=MAX_PAGES:
            raise ValueError("Invalid page sequence")
        _,run_sha=self._run(run_id)
        data,sha=self._page(run_id,seq,run_sha)
        return dict(data,sha256=sha)

    def step(self,alerts,bridge,commercial,*,run_id,source_ref,expected_checkpoint_sha256,now):
        """Process one page; a failed or killed transaction leaves the prior cursor."""
        now=instant(now)
        hex_id(expected_checkpoint_sha256)
        ref(source_ref)
        if len({id(self.db),id(alerts),id(bridge),id(commercial)})!=4 or self.db.in_transaction:
            raise ValueError("Independent archive connections required")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            h=self.status(run_id)
            run=h["run"]
            if h["checkpoint_sha256"]!=expected_checkpoint_sha256:
                raise ValueError("Checkpoint changed; reload run status")
            if run["source_ref"]!=source_ref:
                raise ValueError("Source binding differs")
            if h["state"]=="completed":
                raise ValueError("Run already completed")
            last_at=instant(datetime.fromisoformat(run["created_at"]))
            if h["pages"]:
                last_at=instant(datetime.fromisoformat(self.page(run_id,h["pages"])["as_of"]))
            if now<last_at:
                raise ValueError("Batch clock precedes checkpoint")
            if self.db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]>=MAX_PAGES:
                raise ValueError("Batch page capacity reached")
            after=cursor(h["next_after"],empty=True)
            report=prioritize(alerts,bridge,commercial,archive_ref=run["archive_ref"],
                threshold=run["threshold"],store=run["store"],min_score_bps=run["min_score_bps"],
                min_margin_bps=run["min_margin_bps"],after=after,limit=run["batch_size"],now=now)
            following=report["next_after"]
            if following is not None and cursor(following)<=after:
                raise ValueError("Non-progressing batch cursor")
            if report["scanned_products"]>run["batch_size"] or len(report["items"])>run["batch_size"]:
                raise ValueError("Batch exceeds policy")
            data={"schema":"bakata-batch-page-v1","run_id":run_id,"run_sha256":h["run_sha256"],
                  "sequence":h["pages"]+1,"previous_sha256":expected_checkpoint_sha256,
                  "after":after,"next_after":following,"as_of":now.isoformat(),"report":report}
            raw=encode(data)
            if len(raw.encode("utf-8"))>MAX_PAGE_BYTES:
                raise ValueError("Batch page exceeds byte budget")
            sha=digest(data)
            self.db.execute("INSERT INTO pages VALUES (?,?,?,?)",(run_id,data["sequence"],raw,sha))
            return {"run_id":run_id,"sequence":data["sequence"],"checkpoint_sha256":sha,
                    "next_after":following,"state":"completed" if following is None else "pending",
                    "scanned_products":report["scanned_products"],"counts":report["counts"],
                    "global_snapshot":False,"provider_queries":0,"woo_mutation":False}


def source_binding(paths):
    # Bind an operator run to the same local files, not to their changing contents.
    # No path or inode is disclosed in output; replacement requires a new run.
    return hashlib.sha256(encode([[str(p.resolve()),p.stat().st_dev,p.stat().st_ino] for p in paths]).encode()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",required=True,type=Path)
    sub=p.add_subparsers(dest="command",required=True)
    create=sub.add_parser("create")
    step=sub.add_parser("step")
    for cmd in (create,step):
        for name in ("alerts","bridge","commercial"):
            cmd.add_argument("--"+name,required=True,type=Path)
    for name in ("archive-ref","store"):
        create.add_argument("--"+name,required=True)
    for name in ("price-threshold-bps","min-score-bps","min-margin-bps","batch-size"):
        create.add_argument("--"+name,required=True,type=int)
    step.add_argument("--expected-checkpoint-sha256",required=True)
    status=sub.add_parser("status")
    page=sub.add_parser("page")
    page.add_argument("--sequence",required=True,type=int)
    for cmd in (create,step,status,page):
        cmd.add_argument("--run-id",required=True)
    a=p.parse_args()
    if a.db.is_symlink() or (a.command!="create" and not a.db.is_file()):
        p.error("Private batch archive required")
    sources=(a.alerts,a.bridge,a.commercial) if a.command in ("create","step") else ()
    paths=(a.db,*sources)
    if not all(x.is_file() and not x.is_symlink() for x in sources) or len({x.resolve() for x in paths})!=len(paths):
        p.error("Distinct existing evidence archives required")
    existing=[x for x in paths if x.exists()]
    if any(x.samefile(y) for i,x in enumerate(existing) for y in existing[i+1:]):
        p.error("Archive paths alias")
    os.umask(0o077)
    # Linux one-shot worker. Default SIGALRM terminates the process; SQLite
    # rolls back uncommitted pages, and no external action can be repeated.
    if a.command=="step":
        signal.alarm(45)
    try:
        with ExitStack() as stack:
            db=stack.enter_context(closing(sqlite3.connect(a.db,timeout=5)))
            runs=BatchRuns(db)
            now=datetime.now(timezone.utc)
            if a.command=="create":
                result={"created":runs.create(a.run_id,archive_ref=a.archive_ref,store=a.store,
                    threshold=a.price_threshold_bps,min_score_bps=a.min_score_bps,min_margin_bps=a.min_margin_bps,
                    batch_size=a.batch_size,source_ref=source_binding(sources),now=now)}
            elif a.command=="step":
                binding=source_binding(sources)
                connections=[stack.enter_context(closing(sqlite3.connect(x.resolve().as_uri()+"?mode=ro",uri=True,timeout=5))) for x in sources]
                if source_binding(sources)!=binding:
                    raise ValueError("Source changed while opening")
                result=runs.step(*connections,run_id=a.run_id,source_ref=binding,
                    expected_checkpoint_sha256=a.expected_checkpoint_sha256,now=now)
            elif a.command=="status":
                result=runs.status(a.run_id)
            else:
                result=runs.page(a.run_id,a.sequence)
            print(encode(result))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,sqlite3.Error,OSError):
        p.exit(1,"Batch blocked: verify checkpoint, source binding and resource budget privately.\n")
    finally:
        if a.command=="step":
            signal.alarm(0)


if __name__=="__main__":
    main()
