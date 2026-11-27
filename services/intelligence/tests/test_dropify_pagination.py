import hashlib
import json
from datetime import datetime, timezone
import unittest

from intelligence.dropify_pagination import compare


class PaginationTests(unittest.TestCase):
    now=datetime(2026,11,26,22,tzinfo=timezone.utc)

    def raw(self,page,ids,**overrides):
        rows=[{"external_id":str(i),"sku":str(i),"title":"Fixture","type":"simple",
               "base_price":"7000.25","suggested_price":None,"simple_stock":5,
               "categories":[],"warehouse":""} for i in ids]
        return json.dumps(dict({"schema":"bakata-dropify-bridge-v1",
            "captured_at":f"2026-11-26T21:{page:02}:00Z","store_id":"7","page":page,
            "page_size":10,"offset":(page-1)*10,"possible_next":len(rows)==10,
            "approval_ref":f"fixture-{page}","query_sha256":hashlib.sha256(b"").hexdigest(),"rows":rows},**overrides)).encode()

    def test_clean_is_not_coverage(self):
        report=compare([self.raw(2,range(20,30)),self.raw(1,range(1,11))],now=self.now)
        self.assertEqual(report["status"],"no-observed-anomaly")
        self.assertEqual(report["unique_ids"],20)
        self.assertFalse(report["coverage_verified"])
        self.assertFalse(report["provider_offset_semantics_verified"])

    def test_overlap_and_order(self):
        report=compare([self.raw(1,[1,3,2]),self.raw(2,[2,5])],now=self.now)
        self.assertEqual(report["status"],"requires-review")
        self.assertEqual({x["issue"] for x in report["issues"]},
            {"unexpected-id-order","partial-page-before-next","overlap","non-increasing-boundary"})

    def test_mixed_scope_or_reused_approval(self):
        for second in (self.raw(3,[20]),self.raw(2,[20],store_id="8"),
                       self.raw(2,[20],approval_ref="fixture-1"),
                       self.raw(2,[20],query_sha256="a"*64),
                       self.raw(2,[20],captured_at="2026-11-26T21:40:00Z")):
            with self.assertRaises(ValueError):
                compare([self.raw(1,range(1,11)),second],now=self.now)
