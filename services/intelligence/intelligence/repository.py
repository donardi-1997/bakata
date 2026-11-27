"""Local SQLite reference store; separate from WooCommerce and customer data."""
import sqlite3
from dataclasses import asdict
from datetime import datetime
from .models import Observation


class ObservationStore:
    def __init__(self, connection: sqlite3.Connection):
        self.db = connection
        self.db.execute("""CREATE TABLE IF NOT EXISTS observations (
            source TEXT NOT NULL, external_id TEXT NOT NULL, observed_at TEXT NOT NULL,
            title TEXT NOT NULL, url TEXT NOT NULL, currency TEXT NOT NULL, price_minor INTEGER,
            PRIMARY KEY(source, external_id, observed_at)
        )""")

    def ingest(self, batch: tuple[Observation, ...]) -> int:
        if len(batch) > 1000:
            raise ValueError("Batch exceeds 1000 observations")
        inserted = 0
        with self.db:
            for item in batch:
                row = asdict(item)
                row["observed_at"] = item.key[2]
                previous = self.db.execute(
                    "SELECT title,url,currency,price_minor FROM observations WHERE source=? AND external_id=? AND observed_at=?",
                    item.key,
                ).fetchone()
                if previous is not None:
                    if tuple(previous) != (item.title, item.url, item.currency, item.price_minor):
                        raise ValueError("Conflicting observation at the same identity and timestamp")
                    continue
                self.db.execute("""INSERT INTO observations
                    (source,external_id,observed_at,title,url,currency,price_minor)
                    VALUES (:source,:external_id,:observed_at,:title,:url,:currency,:price_minor)""", row)
                inserted += 1
        return inserted

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    def history_rows(self, source: str, external_id: str) -> tuple[Observation, ...]:
        """Return complete bounded history for one source identity; never truncate silently."""
        rows = self.db.execute("""SELECT source,external_id,title,url,observed_at,currency,price_minor
            FROM observations WHERE source=? AND external_id=?
            ORDER BY observed_at LIMIT 1001""", (source, external_id)).fetchall()
        if len(rows) > 1000:
            raise ValueError("History exceeds 1000 observations; use an explicit window in a future reader")
        return tuple(Observation(source, external_id, title, url, datetime.fromisoformat(at), currency, amount)
                     for source, external_id, title, url, at, currency, amount in rows)
