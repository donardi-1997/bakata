import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from intelligence.dropify_bridge import BridgeArchive
from intelligence.dropify_capture import capture,policy,approval
from intelligence.dropify_census import audit


class CensusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.archive=BridgeArchive(self.db)
        self.now=1795748400
        self.calls=0

    def pause(self,n):
        self.now+=n

    def window(self,first,last,total=9999,overlap=False):
        self.db.execute("PRAGMA query_only=OFF")
        run=f"fixture-{first}"
        directory=self.root/run
        plan=policy(run,"7",first,last,self.now+1800,"fixture","fixture-files")
        def fetch(run,store,page):
            self.calls+=1
            start=(page-1)*10+1
            if overlap: start-=10
            rows=[{"external_id":str(i),"sku":str(i),"title":"Fixture","type":"simple",
                "base_price":"7000.25","suggested_price":None,"simple_stock":i%2,
                "categories":[],"warehouse":"Fixture"} for i in range(start,min(start+10,total+1))]
            return json.dumps({"schema":"bakata-dropify-bridge-v1",
                "captured_at":datetime.fromtimestamp(self.now,timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "store_id":store,"page":page,"page_size":10,"offset":(page-1)*10,
                "possible_next":len(rows)==10,"approval_ref":approval(run,page),
                "query_sha256":hashlib.sha256(b"").hexdigest(),"rows":rows}).encode()
        capture(directory,self.archive,plan,fetch,clock=lambda:self.now,pause=self.pause)
        self.now+=10
        return directory

    def audit(self,windows):
        return audit(self.db,windows,now=datetime.fromtimestamp(self.now,timezone.utc))

    def test_9999_synthetic_products_across_100_windows(self):
        windows=[self.window(first,first+9) for first in range(1,1001,10)]
        r=self.audit(windows)
        self.assertEqual(r["unique_products_observed"],9999)
        self.assertEqual(r["pages_archived"],1000)
        self.assertEqual(self.calls,1000)
        self.assertEqual(r["state"],"terminal-page-observed")
        self.assertFalse(r["coverage_verified"])
        self.assertEqual(r["stock_reported_positive"],5000)
        self.assertEqual(r["stock_reported_zero"],4999)
        self.assertEqual(self.db.execute("PRAGMA query_only").fetchone()[0],1)

    def test_incomplete_and_duplicate_between_windows(self):
        first=self.window(1,1)
        self.assertEqual(self.audit([first])["next_page"],2)
        second=self.window(2,2,overlap=True)
        with self.assertRaisesRegex(ValueError,"Cross-window"):
            self.audit([first,second])

    def test_gap(self):
        first=self.window(1,1)
        third=self.window(3,3)
        with self.assertRaisesRegex(ValueError,"continuity"):
            self.audit([first,third])

    def test_archive_missing(self):
        first=self.window(1,1)
        self.db.execute("DELETE FROM page_rows")
        self.db.commit()
        with self.assertRaisesRegex(ValueError,"observations differ"):
            self.audit([first])
