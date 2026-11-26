"""One explicitly approved Store API pilot; no scheduler or configured live source."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import re
import sqlite3

from .commercial import Capture, import_capture
from .sources import SourceKind, SourceRegistry, SourceSpec
from .transport import SourcePolicy, PolicyError, FetchError, https_get

PATH = "/wp-json/wc/store/v1/products"
MAX_MANIFEST = 65536
FIELDS = {"version","enabled","source","host","expected_ip","reviewed_at","approved_until",
          "robots_valid_until","robots_text","owner_permission_ref","terms_ref","robots_ref","egress_ref"}


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Expected UTC timestamp")
    at = datetime.fromisoformat(value)
    if at.utcoffset() != timedelta(0):
        raise ValueError("Expected UTC timestamp")
    return at.astimezone(timezone.utc)


def reference(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
        raise ValueError("Missing review reference")
    return value


def utcnow():
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Pilot:
    enabled: bool
    source: str
    host: str
    ip: str
    reviewed_at: datetime
    approved_until: datetime
    robots_valid_until: datetime
    robots_text: str
    permission: str
    digest: str

    @property
    def url(self):
        return "https://" + self.host + PATH

    def validate(self, now):
        if not self.reviewed_at <= now < min(self.approved_until,self.robots_valid_until):
            raise PolicyError("Pilot review not current")
        if not self.reviewed_at < self.approved_until <= self.reviewed_at + timedelta(days=7):
            raise PolicyError("Approval window exceeds seven days")
        if not self.reviewed_at < self.robots_valid_until <= self.reviewed_at + timedelta(hours=24):
            raise PolicyError("Robots review window exceeds 24 hours")
        policy = SourcePolicy(self.host, True, self.robots_text, self.robots_valid_until)
        policy.validate(self.url)
        # A single GET with no retries; refuse unusual crawl policies rather than
        # assuming RobotFileParser covers every robots directive.
        if policy.interval() > 86400:
            raise PolicyError("Crawl policy outside pilot scope")


def load_manifest(raw: bytes, *, now=None):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_MANIFEST:
        raise ValueError("Invalid manifest size")
    def unique(pairs):
        result = {}
        for key,value in pairs:
            if key in result:
                raise ValueError("Duplicate manifest field")
            result[key] = value
        return result
    data = json.loads(raw,object_pairs_hook=unique)
    if not isinstance(data,dict) or set(data) != FIELDS or data["version"] != "int11-v1" or type(data["enabled"]) is not bool:
        raise ValueError("Invalid pilot manifest contract")
    host = data["host"]
    if not isinstance(host,str) or len(host)>253 or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",host):
        raise ValueError("Expected exact public DNS hostname")
    if host.endswith((".invalid",".localhost",".test",".example",".local")):
        raise ValueError("Reserved hostname")
    source = data["source"]
    if not isinstance(source,str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}",source) or source.startswith("fixture"):
        raise ValueError("Expected non-fixture source ID")
    if not isinstance(data["expected_ip"],str):
        raise ValueError("Expected approved public IPv4")
    ip = ipaddress.IPv4Address(data["expected_ip"])
    if not ip.is_global or ip.is_multicast or ip.is_reserved:
        raise ValueError("Expected approved public IPv4")
    refs = [reference(data[key]) for key in ("owner_permission_ref","terms_ref","robots_ref","egress_ref")]
    robots = data["robots_text"]
    if not isinstance(robots,str) or not robots.strip() or len(robots.encode("utf-8"))>32768:
        raise ValueError("Missing or oversized reviewed robots policy")
    pilot = Pilot(data["enabled"],source,host,str(ip),timestamp(data["reviewed_at"]),
                  timestamp(data["approved_until"]),timestamp(data["robots_valid_until"]),
                  robots,refs[0],hashlib.sha256(raw).hexdigest())
    pilot.validate(now or utcnow())
    return pilot


class PilotLedger:
    """Single-use host receipt, local trusted SQLite. Never reset automatically."""
    def __init__(self, db):
        self.db = db
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("""CREATE TABLE IF NOT EXISTS int_pilot_receipts (
            host TEXT PRIMARY KEY, digest TEXT NOT NULL, started TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('reserved','succeeded','failed-review')),
            capture_sha256 TEXT
        )""")
        db.commit()

    def reserve(self,pilot,now):
        with self.db:
            try:
                self.db.execute("INSERT INTO int_pilot_receipts VALUES (?,?,?,'reserved',NULL)",
                                (pilot.host,pilot.digest,now.isoformat()))
            except sqlite3.IntegrityError as exc:
                raise PolicyError("Host pilot already reserved; manual review required") from exc

    def finish(self,pilot,state,capture_sha256=None):
        with self.db:
            cursor = self.db.execute("""UPDATE int_pilot_receipts SET state=?,capture_sha256=?
                WHERE host=? AND digest=? AND state='reserved'""",
                (state,capture_sha256,pilot.host,pilot.digest))
            if cursor.rowcount != 1:
                raise PolicyError("Pilot receipt changed; manual review required")


def execute(raw, confirmation, ledger, *, transport=https_get):
    """One GET only, no redirects/retries. Trusted local operator; no remote endpoint."""
    import hmac
    pilot = load_manifest(raw)
    if not pilot.enabled or not isinstance(confirmation,str) or not hmac.compare_digest(pilot.digest,confirmation):
        raise PolicyError("Explicit enabled manifest and matching digest required")
    ledger.reserve(pilot,utcnow())
    try:
        pilot.validate(utcnow())
        response = transport(pilot.url,pilot.host,10.0,524288,
                             accept="application/json",expected_ip=pilot.ip)
        if response.status != 200:
            raise FetchError("Pilot HTTP status rejected; no retry")
        mime = response.headers.get("content-type","").split(";",1)[0].strip().lower()
        if mime != "application/json":
            raise FetchError("Expected Store API JSON")
        at = utcnow()
        pilot.validate(at)
        spec = SourceSpec(pilot.source,pilot.host,SourceKind.STORE_API,pilot.permission,pilot.approved_until)
        batch = import_capture(SourceRegistry((spec,)),Capture(pilot.source,pilot.url,at,response.body),now=at)
        ledger.finish(pilot,"succeeded",batch.evidence.sha256)
        return {"mode":"authorized-pilot","manifest_sha256":pilot.digest,"evidence":asdict(batch.evidence),
                "observations":[asdict(row) for row in batch.observations]}
    except Exception:
        ledger.finish(pilot,"failed-review")
        raise


def main():
    import argparse
    from contextlib import closing
    import os
    from pathlib import Path
    import signal

    parser = argparse.ArgumentParser(description="One-shot authorized Store API pilot")
    parser.add_argument("command",choices=("plan","execute"))
    parser.add_argument("--manifest",required=True,type=Path)
    parser.add_argument("--ledger",type=Path)
    parser.add_argument("--confirm")
    args=parser.parse_args()
    os.umask(0o077)
    with args.manifest.open("rb") as handle:
        raw=handle.read(MAX_MANIFEST+1)
    pilot=load_manifest(raw)
    if args.command=="plan":
        print(json.dumps({"mode":"plan","enabled":pilot.enabled,"url":pilot.url,"approved_ip":pilot.ip,
                          "manifest_sha256":pilot.digest,"approved_until":pilot.approved_until.isoformat()}))
        return
    if args.ledger is None or args.confirm is None:
        parser.error("execute requires --ledger and --confirm")
    if not pilot.enabled or args.confirm != pilot.digest:
        parser.error("execute requires enabled manifest and matching digest")
    # Linux one-shot process deadline includes DNS, TLS and body. A killed
    # process leaves a reserved receipt, never an automatic retry.
    signal.alarm(30)
    with closing(sqlite3.connect(args.ledger,timeout=5)) as db:
        result=execute(raw,args.confirm,PilotLedger(db))
    signal.alarm(0)
    print(json.dumps(result,ensure_ascii=False,default=lambda value:value.isoformat()))


if __name__=="__main__":
    main()
