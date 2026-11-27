"""Versioned local commercial archive. Trusted operator API, no network or Woo writes."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
import re
import sqlite3

from .commercial import Capture, import_capture
from .sources import SourceKind
from .matching import approve_pair, compare
from .models import Observation
from .normalization import normalize_product
from .references import ref
from .scoring import evaluate

APPLICATION_ID = 0x424B4931
SCHEMA_VERSION = 2
MAX_DB_BYTES = 320 * 1024 * 1024
MAX_CAPTURES = 10000
MAX_OBSERVATIONS = 100000
MAX_REVIEWS = 20000
MAX_REVIEW_BYTES = 32768

SCHEMA = (
    """CREATE TABLE sources (
        source TEXT PRIMARY KEY, host TEXT NOT NULL, adapter TEXT NOT NULL
    )""",
    """CREATE TABLE captures (
        id TEXT PRIMARY KEY, source TEXT NOT NULL REFERENCES sources(source),
        url TEXT NOT NULL, observed_at TEXT NOT NULL, sha256 TEXT NOT NULL,
        approval_ref TEXT NOT NULL, approved_until TEXT NOT NULL,
        external_id TEXT, row_count INTEGER NOT NULL,
        body_bytes INTEGER NOT NULL, manifest_sha256 TEXT,
        UNIQUE(source,url,observed_at)
    )""",
    """CREATE TABLE products (
        source TEXT NOT NULL REFERENCES sources(source), external_id TEXT NOT NULL,
        PRIMARY KEY(source,external_id)
    )""",
    """CREATE TABLE observations (
        source TEXT NOT NULL, external_id TEXT NOT NULL, observed_at TEXT NOT NULL,
        title TEXT NOT NULL, url TEXT NOT NULL, currency TEXT NOT NULL,
        price_minor INTEGER CHECK(price_minor IS NULL OR price_minor BETWEEN 0 AND 1000000000000000),
        PRIMARY KEY(source,external_id,observed_at),
        FOREIGN KEY(source,external_id) REFERENCES products(source,external_id)
    )""",
    """CREATE TABLE capture_observations (
        capture_id TEXT NOT NULL REFERENCES captures(id),
        source TEXT NOT NULL, external_id TEXT NOT NULL, observed_at TEXT NOT NULL,
        PRIMARY KEY(capture_id,source,external_id,observed_at),
        FOREIGN KEY(source,external_id,observed_at) REFERENCES observations(source,external_id,observed_at)
    )""",
    """CREATE TABLE evaluations (
        id TEXT PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL,
        observed_at TEXT NOT NULL, as_of TEXT NOT NULL, actor_ref TEXT NOT NULL,
        payload TEXT NOT NULL, sha256 TEXT NOT NULL,
        FOREIGN KEY(source,external_id,observed_at) REFERENCES observations(source,external_id,observed_at)
    )""",
    """CREATE TABLE equivalences (
        id TEXT PRIMARY KEY, left_source TEXT NOT NULL, left_id TEXT NOT NULL, left_at TEXT NOT NULL,
        right_source TEXT NOT NULL, right_id TEXT NOT NULL, right_at TEXT NOT NULL,
        reviewed_at TEXT NOT NULL, actor_ref TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
        FOREIGN KEY(left_source,left_id,left_at) REFERENCES observations(source,external_id,observed_at),
        FOREIGN KEY(right_source,right_id,right_at) REFERENCES observations(source,external_id,observed_at)
    )""",
    "CREATE INDEX evaluations_history ON evaluations(source,external_id,observed_at,as_of,id)",
    "CREATE INDEX captures_source_time ON captures(source,observed_at,id)",
    "CREATE INDEX capture_observation_lookup ON capture_observations(source,external_id,observed_at)",
)

# Migration v1 -> v2: prospective evaluation cohorts and aggregate outcomes.
SCHEMA_V2 = (
    """CREATE TABLE calibration_cohorts (
        id TEXT PRIMARY KEY, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
        created_at TEXT NOT NULL, minimum_orders INTEGER NOT NULL,
        exposure_ref TEXT NOT NULL, actor_ref TEXT NOT NULL
    )""",
    """CREATE TABLE calibration_members (
        cohort_id TEXT NOT NULL REFERENCES calibration_cohorts(id),
        product_group TEXT NOT NULL, evaluation_id TEXT NOT NULL REFERENCES evaluations(id),
        source TEXT NOT NULL, external_id TEXT NOT NULL, enrolled_at TEXT NOT NULL,
        evaluation_sha256 TEXT NOT NULL,
        PRIMARY KEY(cohort_id,product_group),
        UNIQUE(cohort_id,source,external_id), UNIQUE(cohort_id,evaluation_id)
    )""",
    """CREATE TABLE calibration_outcomes (
        cohort_id TEXT NOT NULL, product_group TEXT NOT NULL, recorded_at TEXT NOT NULL,
        fulfilled_orders INTEGER NOT NULL, returned_orders INTEGER NOT NULL,
        gross_minor INTEGER NOT NULL, contribution_minor INTEGER NOT NULL,
        evidence_ref TEXT NOT NULL, actor_ref TEXT NOT NULL,
        PRIMARY KEY(cohort_id,product_group),
        FOREIGN KEY(cohort_id,product_group) REFERENCES calibration_members(cohort_id,product_group)
    )""",
)


def instant(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Expected timezone-aware timestamp")
    return value.astimezone(timezone.utc)


def encode(value):
    def convert(item):
        if isinstance(item,datetime):
            return instant(item).isoformat()
        if isinstance(item,Decimal):
            return str(item)
        if isinstance(item,timedelta):
            return (item.days*86400+item.seconds)*1000000+item.microseconds
        if isinstance(item,Enum):
            return item.value
        raise TypeError("Unsupported archive value")
    return json.dumps(value,default=convert,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CommercialStore:
    def __init__(self, db: sqlite3.Connection):
        if db.in_transaction:
            raise ValueError("Use an independent archive connection")
        self.db=db
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        if db.execute("PRAGMA foreign_keys").fetchone()[0]!=1:
            raise ValueError("Foreign key enforcement unavailable")
        page_size=db.execute("PRAGMA page_size").fetchone()[0]
        limit=MAX_DB_BYTES//page_size
        if db.execute("PRAGMA page_count").fetchone()[0]>limit:
            raise ValueError("Archive exceeds storage budget")
        if db.execute(f"PRAGMA max_page_count={limit}").fetchone()[0]>limit:
            raise ValueError("Cannot enforce archive budget")
        with self.transaction():
            version=db.execute("PRAGMA user_version").fetchone()[0]
            app=db.execute("PRAGMA application_id").fetchone()[0]
            if version==0 and app==0:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
                    raise ValueError("Refusing unrecognized database")
                for statement in SCHEMA:
                    db.execute(statement)
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                db.execute("PRAGMA user_version=1")
                app,version=APPLICATION_ID,1
            if app!=APPLICATION_ID or version not in (1,SCHEMA_VERSION):
                raise ValueError("Unsupported commercial archive schema")
            if version==1:
                for statement in SCHEMA_V2:
                    db.execute(statement)
                db.execute("PRAGMA user_version=2")

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _capacity(self, table, limit, added=1):
        # Table names are exclusively internal constants.
        if self.db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]+added>limit:
            raise ValueError("Archive capacity reached; review retention policy")

    def ingest(self, registry, capture: Capture, *, now: datetime, external_id=None, manifest_sha256=None):
        """Reparse the reviewed capture, store metadata/hash, never raw response bytes."""
        now=instant(now)
        if manifest_sha256 is not None and (not isinstance(manifest_sha256,str) or not re.fullmatch(r"[0-9a-f]{64}",manifest_sha256)):
            raise ValueError("Invalid manifest digest")
        batch=import_capture(registry,capture,now=now,external_id=external_id)
        spec=registry.get(capture.source,now)
        if spec.kind is not SourceKind.JSON_LD and external_id is not None:
            raise ValueError("External ID override is only allowed for JSON-LD")
        ev=batch.evidence
        at=instant(ev.observed_at).isoformat()
        expiry=instant(spec.approved_until).isoformat()
        key=digest(encode([ev.source,ev.url,at]))
        values=(key,ev.source,ev.url,at,ev.sha256,ev.approval_ref,expiry,external_id,len(batch.observations),len(capture.body),manifest_sha256)
        with self.transaction():
            source=self.db.execute("SELECT host,adapter FROM sources WHERE source=?",(ev.source,)).fetchone()
            if source is None:
                self.db.execute("INSERT INTO sources VALUES (?,?,?)",(ev.source,spec.host,ev.adapter))
            elif source!=(spec.host,ev.adapter):
                raise ValueError("Source identity cannot change host or adapter")
            old=self.db.execute("SELECT * FROM captures WHERE id=?",(key,)).fetchone()
            if old is not None:
                if old!=values:
                    raise ValueError("Conflicting capture at same source, URL and time")
                return key,0
            self._capacity("captures",MAX_CAPTURES)
            self.db.execute("INSERT INTO captures VALUES (?,?,?,?,?,?,?,?,?,?,?)",values)
            inserted=0
            available=MAX_OBSERVATIONS-self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            for row in batch.observations:
                self.db.execute("INSERT OR IGNORE INTO products VALUES (?,?)",row.key[:2])
                payload=(row.title,row.url,row.currency,row.price_minor)
                old=self.db.execute("""SELECT title,url,currency,price_minor FROM observations
                    WHERE source=? AND external_id=? AND observed_at=?""",row.key).fetchone()
                if old is not None and old!=payload:
                    raise ValueError("Conflicting observation")
                if old is None:
                    if inserted>=available:
                        raise ValueError("Archive observation capacity reached")
                    self.db.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?)",row.key+payload)
                    inserted+=1
                self.db.execute("INSERT INTO capture_observations VALUES (?,?,?,?)",(key,)+row.key)
            return key,inserted

    def observation(self,key):
        row=self.db.execute("SELECT * FROM observations WHERE source=? AND external_id=? AND observed_at=?",key).fetchone()
        if row is None:
            raise ValueError("Unknown observation")
        return self._observation(row)

    @staticmethod
    def _observation(row):
        source,external_id,at,title,url,currency,price=row
        return Observation(source,external_id,title,url,datetime.fromisoformat(at),currency,price)

    def history(self,source,external_id,*,start: datetime,end: datetime,limit=1000):
        start,end=instant(start),instant(end)
        if start>=end or type(limit) is not int or not 1<=limit<=1000:
            raise ValueError("Invalid history window or limit")
        rows=self.db.execute("""SELECT * FROM observations WHERE source=? AND external_id=?
            AND observed_at>=? AND observed_at<? ORDER BY observed_at LIMIT ?""",
            (source,external_id,start.isoformat(),end.isoformat(),limit+1)).fetchall()
        if len(rows)>limit:
            raise ValueError("History exceeds limit; narrow the window")
        return tuple(map(self._observation,rows))

    def provenance(self,key):
        cursor=self.db.execute("""SELECT c.* FROM captures c JOIN capture_observations l ON c.id=l.capture_id
            WHERE l.source=? AND l.external_id=? AND l.observed_at=? ORDER BY c.id LIMIT 1001""",key)
        fields=[col[0] for col in cursor.description]
        rows=cursor.fetchall()
        if len(rows)>1000:
            raise ValueError("Provenance exceeds limit")
        return tuple(dict(zip(fields,row)) for row in rows)

    def _review(self,table,review_id,values,payload):
        ref(review_id)
        encoded=encode(payload)
        if len(encoded.encode("utf-8"))>MAX_REVIEW_BYTES:
            raise ValueError("Review payload exceeds limit")
        row=(review_id,)+values+(encoded,digest(encoded))
        with self.transaction():
            previous=self.db.execute("SELECT * FROM "+table+" WHERE id=?",(review_id,)).fetchone()
            if previous is not None:
                if previous!=row:
                    raise ValueError("Review ID conflict; append a new review")
                return False
            self._capacity(table,MAX_REVIEWS)
            self.db.execute("INSERT INTO "+table+" VALUES ("+",".join("?" for _ in row)+")",row)
            return True

    def record_evaluation(self,review_id,key,economics,reviews,*,actor_ref,as_of,max_age,now):
        actor_ref=ref(actor_ref)
        as_of=instant(as_of)
        if as_of>instant(now):
            raise ValueError("Future evaluation")
        row=self.observation(key)
        result=evaluate(row,economics,reviews,as_of=as_of,max_age=max_age)
        payload={"economics":asdict(economics) if economics else None,
                 "reviews":[asdict(r) for r in sorted(reviews,key=lambda r:r.criterion)],
                 "result":asdict(result)}
        return self._review("evaluations",review_id,row.key+(as_of.isoformat(),actor_ref),payload)

    def record_equivalence(self,review_id,left_key,right_key,left_attributes,right_attributes,*,
                           actor_ref,review_ref,reviewed_at,now,variant_equivalence_confirmed):
        actor_ref,review_ref=ref(actor_ref),ref(review_ref)
        at=instant(reviewed_at)
        left,right=self.observation(left_key),self.observation(right_key)
        if not max(left.observed_at,right.observed_at)<=at<=instant(now):
            raise ValueError("Invalid review timestamp")
        if right.key<left.key:
            left,right=right,left
            left_attributes,right_attributes=right_attributes,left_attributes
        proposal=compare(normalize_product(left,left_attributes),normalize_product(right,right_attributes))
        link=approve_pair(proposal,review_ref,variant_equivalence_confirmed=variant_equivalence_confirmed)
        payload={"left_attributes":asdict(left_attributes) if left_attributes else None,
                 "right_attributes":asdict(right_attributes) if right_attributes else None,
                 "kind":proposal.kind.value,"reasons":proposal.reasons,"link":asdict(link),
                 "variant_equivalence_confirmed":True}
        return self._review("equivalences",review_id,left.key+right.key+(at.isoformat(),actor_ref),payload)

    def review(self,kind,review_id):
        table={"evaluation":"evaluations","equivalence":"equivalences"}.get(kind)
        if table is None:
            raise ValueError("Unknown review kind")
        cursor=self.db.execute("SELECT * FROM "+table+" WHERE id=?",(ref(review_id),))
        row=cursor.fetchone()
        if row is None:
            return None
        record=dict(zip((col[0] for col in cursor.description),row))
        if digest(record["payload"])!=record["sha256"]:
            raise ValueError("Review integrity check failed")
        record["payload"]=json.loads(record["payload"])
        return record
