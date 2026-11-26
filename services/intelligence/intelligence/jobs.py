"""Durable offline queue. One fixed fixture job type; no arbitrary commands or network."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import secrets
import sqlite3
import re

MAX_JOBS = 1000
MAX_DB_BYTES = 320 * 1024 * 1024
MAX_ATTEMPTS = 3
LEASE_SECONDS = 60
MAX_RESULT_BYTES = 262144
MAX_EPOCH = 253402300000
JOB_KIND = "fixture-snapshot"


def epoch(value: int) -> int:
    if type(value) is not int or not 0 <= value <= MAX_EPOCH:
        raise ValueError("Expected bounded UTC epoch seconds")
    return value


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value):
        raise ValueError("Invalid job identifier")
    return value


@dataclass(frozen=True, slots=True)
class Claim:
    job_id: str
    token: str
    attempt: int
    lease_until: int


class JobQueue:
    def __init__(self, db: sqlite3.Connection):
        if db.in_transaction:
            raise ValueError("Queue requires an independent connection")
        self.db = db
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("PRAGMA foreign_keys=ON")
        # Bound the main SQLite file, not journal/temp/backup disk usage.
        page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
        page_limit = MAX_DB_BYTES // page_size
        if self.db.execute("PRAGMA page_count").fetchone()[0] > page_limit:
            raise ValueError("Queue database exceeds storage budget")
        actual = self.db.execute(f"PRAGMA max_page_count={page_limit}").fetchone()[0]
        if actual > page_limit:
            raise ValueError("Cannot enforce queue storage budget")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS int_jobs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind='fixture-snapshot'),
            due INTEGER NOT NULL, original_due INTEGER NOT NULL, schedule_id TEXT, status TEXT NOT NULL CHECK(status IN
                ('queued','running','succeeded','failed')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
            token TEXT, lease_until INTEGER, result TEXT, error TEXT,
            created INTEGER NOT NULL, updated INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS int_jobs_due ON int_jobs(status,due,id);
        CREATE UNIQUE INDEX IF NOT EXISTS int_jobs_one_running ON int_jobs(status)
            WHERE status='running';
        CREATE TABLE IF NOT EXISTS int_schedules (
            id TEXT PRIMARY KEY, interval_seconds INTEGER NOT NULL,
            next_due INTEGER NOT NULL, enabled INTEGER NOT NULL CHECK(enabled IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS int_job_events (
            id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES int_jobs(id),
            at INTEGER NOT NULL, event TEXT NOT NULL, attempt INTEGER NOT NULL
        );
        """)

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _event(self, job_id, now, event, attempt):
        self.db.execute("INSERT INTO int_job_events(job_id,at,event,attempt) VALUES (?,?,?,?)",
                        (job_id, now, event, attempt))

    def _enqueue(self, job_id, due, now, schedule_id=None):
        existing = self.db.execute("SELECT original_due,kind FROM int_jobs WHERE id=?", (job_id,)).fetchone()
        if existing:
            if existing != (due, JOB_KIND):
                raise ValueError("Conflicting job identity")
            return False
        if self.db.execute("SELECT COUNT(*) FROM int_jobs").fetchone()[0] >= MAX_JOBS:
            raise ValueError("Queue capacity reached; explicit retention required")
        self.db.execute("""INSERT INTO int_jobs(id,kind,due,original_due,schedule_id,status,created,updated)
            VALUES (?,?,?,?,?,'queued',?,?)""", (job_id, JOB_KIND, due, due, schedule_id, now, now))
        self._event(job_id, now, "queued", 0)
        return True

    def enqueue(self, job_id: str, due: int, now: int) -> bool:
        identifier(job_id)
        if job_id.startswith("schedule-"):
            raise ValueError("Reserved schedule job namespace")
        with self._transaction():
            return self._enqueue(job_id, epoch(due), epoch(now))

    def configure_schedule(self, schedule_id: str, interval: int, first_due: int):
        identifier(schedule_id)
        if len(schedule_id) > 48 or type(interval) is not int or not 300 <= interval <= 86400:
            raise ValueError("Schedule interval must be 5 minutes to 24 hours")
        epoch(first_due)
        with self._transaction():
            if self.db.execute("SELECT COUNT(*) FROM int_schedules").fetchone()[0] >= 10:
                raise ValueError("Schedule capacity reached")
            self.db.execute("INSERT INTO int_schedules VALUES (?,?,?,1)", (schedule_id, interval, first_due))

    def disable_schedule(self, schedule_id: str):
        with self._transaction():
            self.db.execute("UPDATE int_schedules SET enabled=0 WHERE id=?", (identifier(schedule_id),))

    def tick(self, now: int) -> int:
        """Coalesce missed slots into the most recent due slot; no catch-up storm."""
        epoch(now)
        count = 0
        with self._transaction():
            for schedule_id, interval, due in self.db.execute(
                "SELECT id,interval_seconds,next_due FROM int_schedules WHERE enabled=1 AND next_due<=? ORDER BY id", (now,)
            ).fetchall():
                slot = due + ((now - due) // interval) * interval
                # Do not accumulate pending instances for a single schedule.
                pending = self.db.execute("""SELECT 1 FROM int_jobs
                    WHERE schedule_id=? AND status IN ('queued','running') LIMIT 1""",
                    (schedule_id,)).fetchone()
                if not pending:
                    count += self._enqueue(f"schedule-{schedule_id}_{slot}", slot, now, schedule_id)
                self.db.execute("UPDATE int_schedules SET next_due=? WHERE id=?", (epoch(slot + interval), schedule_id))
        return count

    def claim(self, now: int) -> Claim | None:
        epoch(now)
        with self._transaction():
            expired = self.db.execute("""SELECT id,attempts FROM int_jobs
                WHERE status='running' AND lease_until<=?""", (now,)).fetchall()
            for job_id, attempt in expired:
                self._retry(job_id, attempt, now, "lease-expired")
            if self.db.execute("SELECT 1 FROM int_jobs WHERE status='running'").fetchone():
                return None
            row = self.db.execute("""SELECT id,attempts FROM int_jobs WHERE status='queued'
                AND due<=? ORDER BY due,id LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            job_id, previous = row
            token = secrets.token_hex(24)
            deadline = epoch(now + LEASE_SECONDS)
            attempt = previous + 1
            self.db.execute("""UPDATE int_jobs SET status='running', attempts=?,token=?,
                lease_until=?,updated=?,error=NULL WHERE id=?""", (attempt,token,deadline,now,job_id))
            self._event(job_id, now, "claimed", attempt)
            return Claim(job_id, token, attempt, deadline)

    def _owned(self, claim, now):
        row = self.db.execute("SELECT status,token,lease_until,attempts FROM int_jobs WHERE id=?",
                              (claim.job_id,)).fetchone()
        if row != ("running",claim.token,claim.lease_until,claim.attempt) or now >= claim.lease_until:
            raise ValueError("Stale or invalid claim")

    def _retry(self, job_id, attempt, now, reason):
        failed = attempt >= MAX_ATTEMPTS
        status = "failed" if failed else "queued"
        due = now if failed else epoch(now + 30 * 2 ** (attempt-1))
        self.db.execute("""UPDATE int_jobs SET status=?,due=?,token=NULL,lease_until=NULL,
            error=?,updated=? WHERE id=?""", (status,due,reason,now,job_id))
        self._event(job_id, now, "failed" if failed else "retry:"+reason, attempt)

    def fail(self, claim: Claim, now: int):
        epoch(now)
        with self._transaction():
            self._owned(claim,now)
            self._retry(claim.job_id,claim.attempt,now,"fixture-error")

    def succeed(self, claim: Claim, result: dict, now: int):
        epoch(now)
        if not isinstance(result, dict) or result.get("mode") != "fixture" or result.get("schema") != "bakata-intelligence-preview-v1":
            raise ValueError("Only fixture snapshot result is supported")
        payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(payload.encode("utf-8")) > MAX_RESULT_BYTES:
            raise ValueError("Result too large")
        with self._transaction():
            self._owned(claim,now)
            self.db.execute("""UPDATE int_jobs SET status='succeeded',result=?,token=NULL,
                lease_until=NULL,updated=? WHERE id=?""", (payload,now,claim.job_id))
            self._event(claim.job_id,now,"succeeded",claim.attempt)

    def list_jobs(self) -> list[dict]:
        cursor = self.db.execute("SELECT id,kind,due,status,attempts,error,created,updated FROM int_jobs ORDER BY created,id")
        fields = [column[0] for column in cursor.description]
        return [dict(zip(fields,row)) for row in cursor.fetchall()]

    def result(self, job_id: str) -> dict | None:
        row = self.db.execute("SELECT result FROM int_jobs WHERE id=? AND status='succeeded'", (identifier(job_id),)).fetchone()
        return json.loads(row[0]) if row else None

    def events(self, job_id: str) -> list[dict]:
        return [dict(at=at,event=event,attempt=attempt) for at,event,attempt in self.db.execute(
            "SELECT at,event,attempt FROM int_job_events WHERE job_id=? ORDER BY id", (identifier(job_id),))]
