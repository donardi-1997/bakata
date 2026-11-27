import hashlib
import json
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from intelligence.admin_export import fixture_snapshot
from intelligence.commercial import Capture, import_capture
from intelligence.jobs import JobQueue, MAX_DB_BYTES
from intelligence.matching import approve_pair, compare
from intelligence.normalization import ReviewedAttributes, normalize_product
from intelligence.prices import Quote, ReviewedPriceContext, market_comparison, price_history
from intelligence.repository import ObservationStore
from intelligence.scheduler import run_once
from intelligence.scoring import UnitEconomics, CriterionReview, REVIEW_CRITERIA, evaluate, ScreeningStatus
from intelligence.sources import SourceKind, SourceRegistry, SourceSpec


class ReleaseTests(unittest.TestCase):
    def test_capture_normalization_prices_and_scoring(self):
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        now = at + timedelta(hours=1)
        specs = tuple(SourceSpec("fixture-"+key, key+".invalid", SourceKind.AUTHORIZED_CSV,
                                 "synthetic-approval", now+timedelta(days=1)) for key in ("a","b"))
        registry = SourceRegistry(specs)
        rows = []
        with closing(sqlite3.connect(":memory:")) as db:
            store = ObservationStore(db)
            for spec, amount in zip(specs,(4990000,4500000)):
                body = ("external_id,title,url,currency,price_minor\n"
                        f"001,Fixture,https://{spec.host}/item,COP,{amount}\n").encode()
                batch = import_capture(registry,Capture(spec.source,f"https://{spec.host}/export",at,body),now=now)
                self.assertEqual(batch.evidence.sha256,hashlib.sha256(body).hexdigest())
                self.assertEqual(store.ingest(batch.observations),1)
                self.assertEqual(store.ingest(batch.observations),0)
                row = store.history_rows(spec.source,"001")[0]
                self.assertEqual(price_history((row,),as_of=now).stats.minimum_minor,amount)
                rows.append(row)
            normalized = [normalize_product(row,ReviewedAttributes(row.key,"fixture-gtin",gtin="036000291452")) for row in rows]
            link = approve_pair(compare(*normalized),"fixture-link",variant_equivalence_confirmed=True)
            quotes = tuple(Quote(row,ReviewedPriceContext(row.key,"fixture-cost","CO:bogota","retail","new",True,0,0)) for row in rows)
            market = market_comparison(quotes,(link,),as_of=now,max_age=timedelta(days=1),max_skew=timedelta(0))
            self.assertEqual(market.stats.minimum_minor,4500000)
            row = rows[0]
            economics = UnitEconomics(row.key,"fixture-cost",now,"COP",5700000,2500000,1200000,100000,200000,0,400)
            reviews = tuple(CriterionReview(row.key,k,75,"fixture-"+k,now,"Synthetic evidence") for k in REVIEW_CRITERIA)
            score = evaluate(row,economics,reviews,as_of=now,max_age=timedelta(days=1))
            self.assertEqual(score.status,ScreeningStatus.REVIEW_READY)
            self.assertEqual(str(score.total),"77.77")
            self.assertEqual(store.count(),2)

    def test_queue_backup_restore_and_budget(self):
        with TemporaryDirectory() as directory:
            source = str(Path(directory)/"queue.sqlite")
            backup = str(Path(directory)/"backup.sqlite")
            with closing(sqlite3.connect(source)) as db:
                queue = JobQueue(db)
                page_size = db.execute("PRAGMA page_size").fetchone()[0]
                self.assertLessEqual(db.execute("PRAGMA max_page_count").fetchone()[0]*page_size,MAX_DB_BYTES)
                queue.enqueue("fixture-backup",0,0)
                run_once(queue,lambda:1)
                with closing(sqlite3.connect(backup)) as target:
                    db.backup(target)
                    self.assertEqual(target.execute("PRAGMA integrity_check").fetchone()[0],"ok")
            with closing(sqlite3.connect(backup)) as db:
                restored = JobQueue(db)
                self.assertEqual(restored.result("fixture-backup"),fixture_snapshot())
                self.assertEqual(restored.list_jobs()[0]["status"],"succeeded")
                self.assertEqual([e["event"] for e in restored.events("fixture-backup")],["queued","claimed","succeeded"])
                self.assertIsNone(restored.claim(2))
