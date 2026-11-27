"""Bounded, explicitly authorized recurring Store API captures; no installed timer."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import hmac
import re
import sqlite3

from .pilot import load_manifest, reference, utcnow, MAX_MANIFEST
from .commercial import Capture
from .sources import SourceSpec, SourceKind, SourceRegistry
from .transport import https_get, PolicyError, FetchError

MIN_INTERVAL = 21600
MAX_INTERVAL = 86400
MAX_ATTEMPTS = 4
MAX_SCHEDULES = 10
INSPECT_MAX_CANDIDATES = 100
INSPECT_VM_STEPS = 1000000


def inspect_interrupted(db, archive):
    """Report local candidates only; this does not reconcile either database."""
    if db.in_transaction or archive.in_transaction or db is archive:
        raise ValueError("Separate idle ledger and archive connections required")
    limits=[]
    def make_budget():
        steps=0
        def budget():
            nonlocal steps
            steps+=1000
            return steps>INSPECT_VM_STEPS
        return budget
    try:
        for connection in (db,archive):
            limits.append(connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,1048576))
            connection.set_progress_handler(make_budget(),1000)
        return _inspect_interrupted(db,archive)
    except (sqlite3.Error, ValueError, TypeError, OverflowError):
        raise ValueError("Inspection failed: invalid, unsupported or oversized local evidence") from None
    finally:
        for connection,limit in zip((db,archive),limits):
            connection.set_progress_handler(None,0)
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,limit)


def _inspect_interrupted(db, archive):
    from .storage import APPLICATION_ID, SCHEMA_VERSION
    if (db.execute("PRAGMA application_id").fetchone()[0],
        db.execute("PRAGMA user_version").fetchone()[0])!=(0,0):
        raise ValueError("Unsupported ledger")
    app=archive.execute("PRAGMA application_id").fetchone()[0]
    version=archive.execute("PRAGMA user_version").fetchone()[0]
    if app!=APPLICATION_ID or version not in (1,SCHEMA_VERSION):
        raise ValueError("Unsupported archive")
    db.execute("SELECT host,digest,state,capture_sha256 FROM int_pilot_receipts LIMIT 0")
    db.execute("SELECT host,source,digest,remaining,last_attempt,state FROM int_recurring LIMIT 0")
    db.execute("SELECT host,attempt,started,state FROM int_recurring_events LIMIT 0")
    archive.execute("SELECT source,host,adapter FROM sources LIMIT 0")
    archive.execute("SELECT id,source,observed_at,sha256,manifest_sha256 FROM captures LIMIT 0")
    rows=db.execute("""SELECT s.host,s.source,s.digest,s.remaining,s.last_attempt,
        e.attempt,e.started FROM int_recurring s LEFT JOIN int_recurring_events e
        ON e.host=s.host AND e.state='reserved'
        WHERE s.state='running' LIMIT ?""",(MAX_SCHEDULES+1,)).fetchall()
    result=[]
    for host,source,digest,remaining,last_attempt,attempt,started in rows[:MAX_SCHEDULES]:
        if not isinstance(host,str) or len(host)>253 or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",host):
            raise ValueError("Invalid host")
        if not isinstance(source,str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}",source):
            raise ValueError("Invalid source")
        if not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest):
            raise ValueError("Invalid digest")
        if type(remaining) is not int or not 0<=remaining<=MAX_ATTEMPTS:
            raise ValueError("Invalid remaining")
        if attempt is not None and (type(attempt) is not int or not 1<=attempt<=MAX_ATTEMPTS):
            raise ValueError("Invalid attempt")
        entry={"manifest_sha256":digest,
               "remaining":remaining,"last_attempt":last_attempt,
               "attempt":attempt,"started":started,"candidates":[]}
        for value in (last_attempt,started):
            if value is not None:
                _inspect_time(value)
        history=db.execute("""SELECT attempt,started,state FROM int_recurring_events
            WHERE host=? ORDER BY attempt LIMIT ?""",(host,MAX_ATTEMPTS+1)).fetchall()
        coherent=len(history)<=MAX_ATTEMPTS and len(history)>0
        if attempt is not None and remaining+attempt>MAX_ATTEMPTS:
            coherent=False
        previous=None
        for index,(number,when,state) in enumerate(history,1):
            if type(number) is not int or number!=index or state not in ("reserved","succeeded","failed-review"):
                coherent=False
            try:
                at=_inspect_time(when)
                if previous is not None and at<previous:
                    coherent=False
                previous=at
            except (ValueError,TypeError,OverflowError):
                coherent=False
            if index<len(history) and state!="succeeded":
                coherent=False
        if (started is None or started != last_attempt or sum(row[0]==host for row in rows)!=1
                or not coherent or history[-1]!=(attempt,started,"reserved")):
            entry["evidence"]="inconsistent"
        else:
            start=_inspect_time(started)
            candidates=archive.execute("""SELECT c.id,c.observed_at,c.sha256
                FROM captures c JOIN sources s ON s.source=c.source
                WHERE s.host=? AND s.adapter=? AND c.source=? AND c.manifest_sha256=?
                LIMIT ?""",
                (host,SourceKind.STORE_API.value,source,digest,INSPECT_MAX_CANDIDATES+1)).fetchall()
            for cid,observed,sha in candidates[:INSPECT_MAX_CANDIDATES]:
                if any(not isinstance(v,str) or not re.fullmatch(r"[0-9a-f]{64}",v) for v in (cid,sha)):
                    raise ValueError("Invalid capture digest")
                at=_inspect_time(observed)
                if at>=start:
                    entry["candidates"].append({"capture_id":cid,"observed_at":observed,
                                                "sha256":sha})
            count=len(entry["candidates"])
            entry["evidence"]=("truncated" if len(candidates)>INSPECT_MAX_CANDIDATES else
                               "absent" if count==0 else "unique" if count==1 else "ambiguous")
        result.append(entry)
    if len(rows)>MAX_SCHEDULES:
        for entry in result:
            entry["evidence"]="truncated"
        result.append({"evidence":"truncated"})
    return result


def _inspect_time(value):
    if not isinstance(value,str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?\+00:00",value):
        raise ValueError("Invalid timestamp")
    return datetime.fromisoformat(value)


class RecurringCapture:
    """Use the same trusted local ledger as the completed INT-11 pilot."""
    def __init__(self, db, archive):
        self.db, self.archive = db, archive
        if db.in_transaction or db is archive.db:
            raise ValueError("Separate idle ledger and archive connections required")
        db.execute("PRAGMA busy_timeout=5000")
        with self.transaction():
            # Do not silently bootstrap a new pilot ledger.
            db.execute("SELECT host,digest,state,capture_sha256 FROM int_pilot_receipts LIMIT 0")
            db.execute("""CREATE TABLE IF NOT EXISTS int_recurring (
                host TEXT PRIMARY KEY, source TEXT NOT NULL, digest TEXT NOT NULL,
                approval_ref TEXT NOT NULL, interval_seconds INTEGER NOT NULL,
                next_due TEXT NOT NULL, remaining INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('enabled','running','disabled','exhausted','blocked')),
                last_attempt TEXT, capture_id TEXT
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS int_recurring_events (
                host TEXT NOT NULL, attempt INTEGER NOT NULL, started TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('reserved','succeeded','failed-review')),
                capture_id TEXT, PRIMARY KEY(host,attempt)
            )""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS int_recurring_one_running
                ON int_recurring(state) WHERE state='running'""")

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _pilot_evidence(self,pilot):
        receipt=self.db.execute("""SELECT digest,capture_sha256 FROM int_pilot_receipts
            WHERE host=? AND state='succeeded'""",(pilot.host,)).fetchone()
        if not receipt or not receipt[1]:
            raise PolicyError("Successful archived one-shot pilot required")
        # Match the prior receipt to an actual committed capture in the archive.
        evidence=self.archive.db.execute("""SELECT 1 FROM captures c JOIN sources s ON s.source=c.source
            WHERE s.host=? AND c.source=? AND s.adapter=? AND c.manifest_sha256=? AND c.sha256=? LIMIT 1""",
            (pilot.host,pilot.source,SourceKind.STORE_API.value,*receipt)).fetchone()
        if evidence is None:
            raise PolicyError("Pilot receipt has no matching archive evidence")

    @staticmethod
    def _policy(pilot,interval):
        if type(interval) is not int or not MIN_INTERVAL<=interval<=MAX_INTERVAL:
            raise ValueError("Interval must be 6–24 hours")
        # Honor the strictest declared delay/rate across every robots group.
        for line in pilot.robots_text.splitlines():
            key,_,value=line.split("#",1)[0].partition(":")
            key,value=key.strip().lower(),value.strip()
            if key=="crawl-delay" and int(value)>interval:
                raise PolicyError("Interval violates crawl delay")
            if key=="request-rate":
                count,seconds=map(int,value.split("/"))
                if seconds>interval*count:
                    raise PolicyError("Interval violates request rate")

    def configure(self,raw,confirmation,*,approval_ref,interval,attempts):
        pilot=load_manifest(raw)
        if not pilot.enabled or not isinstance(confirmation,str) or not hmac.compare_digest(pilot.digest,confirmation):
            raise PolicyError("Explicit enabled manifest confirmation required")
        reference(approval_ref)
        if type(attempts) is not int or not 1<=attempts<=MAX_ATTEMPTS:
            raise ValueError("Maximum four attempts per authorization")
        self._policy(pilot,interval)
        self._pilot_evidence(pilot)
        now=utcnow()
        pilot.validate(now)
        # Wait a full interval after registration, even after an old pilot.
        due=now+timedelta(seconds=interval)
        if due>=min(pilot.approved_until,pilot.robots_valid_until):
            raise PolicyError("No scheduled slot within reviewed authorization")
        with self.transaction():
            if self.db.execute("SELECT COUNT(*) FROM int_recurring").fetchone()[0]>=MAX_SCHEDULES:
                raise ValueError("Schedule capacity reached")
            if self.db.execute("SELECT 1 FROM int_recurring WHERE host=?",(pilot.host,)).fetchone():
                raise PolicyError("Host schedule already registered; renewal not implemented")
            self.db.execute("""INSERT INTO int_recurring VALUES (?,?,?,?,?,?,?,'enabled',NULL,NULL)""",
                (pilot.host,pilot.source,pilot.digest,approval_ref,interval,due.isoformat(),attempts))

    def disable(self,host):
        with self.transaction():
            if self.db.execute("SELECT state FROM int_recurring WHERE host=?",(host,)).fetchone()==("running",):
                raise PolicyError("Running or uncertain capture requires manual reconciliation")
            self.db.execute("UPDATE int_recurring SET state='disabled' WHERE host=? AND state='enabled'",(host,))

    def tick(self,raw,*,transport=https_get):
        # Invalid or expired manifests fail before reservation or network.
        pilot=load_manifest(raw)
        if not pilot.enabled:
            raise PolicyError("Source disabled")
        self._pilot_evidence(pilot)
        now=utcnow()
        pilot.validate(now)
        with self.transaction():
            schedule=self.db.execute("""SELECT digest,interval_seconds,next_due,remaining,state
                FROM int_recurring WHERE host=?""",(pilot.host,)).fetchone()
            if not schedule or schedule[0]!=pilot.digest:
                raise PolicyError("Exact approved schedule required")
            _,interval,due,remaining,state=schedule
            self._policy(pilot,interval)
            if state!="enabled" or remaining<=0:
                return None
            if now<datetime.fromisoformat(due):
                return None
            if self.db.execute("SELECT 1 FROM int_recurring WHERE state='running'").fetchone():
                raise PolicyError("Another capture is running or uncertain")
            attempt=self.db.execute("SELECT COUNT(*) FROM int_recurring_events WHERE host=?",(pilot.host,)).fetchone()[0]+1
            self.db.execute("INSERT INTO int_recurring_events VALUES (?,?,?,'reserved',NULL)",(pilot.host,attempt,now.isoformat()))
            self.db.execute("""UPDATE int_recurring SET state='running',remaining=remaining-1,last_attempt=?
                WHERE host=?""",(now.isoformat(),pilot.host))
        try:
            pilot.validate(utcnow())
            response=transport(pilot.url,pilot.host,10.0,524288,accept="application/json",expected_ip=pilot.ip)
            if response.status!=200 or response.headers.get("content-type","").split(";",1)[0].strip().lower()!="application/json":
                raise FetchError("Capture rejected; manual review required")
            at=utcnow()
            pilot.validate(at)
            spec=SourceSpec(pilot.source,pilot.host,SourceKind.STORE_API,pilot.permission,pilot.approved_until)
            cid,count=self.archive.ingest(SourceRegistry((spec,)),Capture(pilot.source,pilot.url,at,response.body),
                                          now=at,manifest_sha256=pilot.digest)
            due=at+timedelta(seconds=interval)
            state="enabled" if remaining>1 and due<min(pilot.approved_until,pilot.robots_valid_until) else "exhausted"
            self._finish(pilot.host,attempt,"succeeded",state,cid,due.isoformat())
            return {"capture_id":cid,"new_observations":count,"state":state}
        except Exception:
            self._finish(pilot.host,attempt,"failed-review","blocked",None,now.isoformat())
            raise

    def _finish(self,host,attempt,event,state,cid,due):
        with self.transaction():
            changed=self.db.execute("""UPDATE int_recurring_events SET state=?,capture_id=?
                WHERE host=? AND attempt=? AND state='reserved'""",(event,cid,host,attempt)).rowcount
            if changed!=1:
                raise PolicyError("Capture reservation changed")
            if self.db.execute("""UPDATE int_recurring SET state=?,capture_id=?,next_due=?
                WHERE host=? AND state='running'""",(state,cid,due,host)).rowcount!=1:
                raise PolicyError("Schedule reservation changed")

    def list(self):
        cursor=self.db.execute("SELECT * FROM int_recurring ORDER BY host")
        return [dict(zip((c[0] for c in cursor.description),row)) for row in cursor.fetchall()]


def main():
    import argparse
    from contextlib import closing
    import json
    import os
    from pathlib import Path
    import signal
    from .storage import CommercialStore

    parser=argparse.ArgumentParser(description="Explicit recurring commercial capture")
    parser.add_argument("--ledger",required=True,type=Path)
    parser.add_argument("--archive",required=True,type=Path)
    commands=parser.add_subparsers(dest="command",required=True)
    configure=commands.add_parser("configure")
    configure.add_argument("--manifest",required=True,type=Path)
    configure.add_argument("--confirm",required=True)
    configure.add_argument("--approval-ref",required=True)
    configure.add_argument("--interval",required=True,type=int)
    configure.add_argument("--attempts",required=True,type=int)
    tick=commands.add_parser("tick")
    tick.add_argument("--manifest",required=True,type=Path)
    disable=commands.add_parser("disable")
    disable.add_argument("host")
    commands.add_parser("list")
    commands.add_parser("inspect")
    args=parser.parse_args()
    os.umask(0o077)
    if args.command=="inspect":
        try:
            if not args.ledger.is_file() or not args.archive.is_file() or args.ledger.samefile(args.archive):
                raise ValueError("Invalid databases")
            # Never initialize, migrate or open either database for writing.
            with closing(sqlite3.connect(args.ledger.resolve().as_uri()+"?mode=ro",uri=True)) as db, \
                 closing(sqlite3.connect(args.archive.resolve().as_uri()+"?mode=ro",uri=True)) as archive:
                result=inspect_interrupted(db,archive)
        except (OSError,sqlite3.Error,ValueError):
            parser.exit(1,"Inspection failed: invalid, unsupported or oversized local evidence\n")
        print(json.dumps(result,ensure_ascii=False))
        return
    if not args.ledger.is_file() or not args.archive.is_file() or args.ledger.samefile(args.archive):
        parser.error("Existing distinct pilot ledger and archive required")
    signal.alarm(45)
    with closing(sqlite3.connect(args.ledger,timeout=5)) as db, closing(sqlite3.connect(args.archive,timeout=5)) as archive:
        scheduler=RecurringCapture(db,CommercialStore(archive))
        if args.command in ("configure","tick"):
            with args.manifest.open("rb") as handle:
                raw=handle.read(MAX_MANIFEST+1)
            if args.command=="configure":
                scheduler.configure(raw,args.confirm,approval_ref=args.approval_ref,interval=args.interval,attempts=args.attempts)
                result={"configured":True}
            else:
                result=scheduler.tick(raw)
        elif args.command=="disable":
            scheduler.disable(args.host)
            result={"disabled":True}
        else:
            result=scheduler.list()
    signal.alarm(0)
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    main()
