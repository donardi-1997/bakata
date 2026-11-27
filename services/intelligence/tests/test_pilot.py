import hashlib
import json
import sqlite3
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

from intelligence.pilot import execute, load_manifest, PilotLedger, utcnow, PATH
from intelligence.transport import Response, FetchError, PolicyError, https_get


class PilotTests(unittest.TestCase):
    def setUp(self):
        now=utcnow()
        self.data={"version":"int11-v1","enabled":True,"source":"pilot-store",
                   "host":"catalog.example.com","expected_ip":"8.8.8.8",
                   "reviewed_at":(now-timedelta(minutes=1)).isoformat(),
                   "approved_until":(now+timedelta(days=1)).isoformat(),
                   "robots_valid_until":(now+timedelta(hours=1)).isoformat(),
                   "robots_text":"User-agent: *\nDisallow: /private",
                   "owner_permission_ref":"synthetic-owner","terms_ref":"synthetic-terms",
                   "robots_ref":"synthetic-robots","egress_ref":"synthetic-egress"}
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.ledger=PilotLedger(self.db)
        self.item={"id":7,"name":"Synthetic product","type":"simple","is_password_protected":False,
                   "permalink":"https://catalog.example.com/product/demo",
                   "prices":{"currency_code":"COP","currency_minor_unit":2,"price":"4990000","price_range":None}}
        self.body=json.dumps([self.item]).encode()
        self.transport=Mock(return_value=Response(200,{"content-type":"application/json"},self.body))

    def raw(self,**changes):
        return json.dumps(dict(self.data,**changes)).encode()

    def run_pilot(self,raw=None,confirm=None):
        raw=raw if raw is not None else self.raw()
        return execute(raw,confirm if confirm is not None else hashlib.sha256(raw).hexdigest(),self.ledger,transport=self.transport)

    def test_plan_validates_without_network_or_receipt(self):
        raw=self.raw(enabled=False)
        plan=load_manifest(raw)
        self.assertFalse(plan.enabled)
        self.assertEqual(plan.url,"https://catalog.example.com"+PATH)
        self.assertEqual(plan.digest,hashlib.sha256(raw).hexdigest())
        self.transport.assert_not_called()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM int_pilot_receipts").fetchone()[0],0)

    def test_disabled_and_digest_mismatch(self):
        for raw,confirm in ((self.raw(enabled=False),None),(self.raw(),"0"*64)):
            with self.assertRaises(PolicyError):
                self.run_pilot(raw,confirm)
        self.transport.assert_not_called()

    def test_invalid_review_and_ip(self):
        for fields in ({"owner_permission_ref":""},{"expected_ip":"127.0.0.1"},
                       {"expected_ip":"169.254.169.254"},{"host":"127.0.0.1"},
                       {"host":"catalog.invalid"},{"host":"catalog.example.com:443"},
                       {"approved_until":(utcnow()-timedelta(seconds=1)).isoformat()},
                       {"robots_valid_until":(utcnow()+timedelta(days=2)).isoformat()}):
            with self.subTest(fields=fields),self.assertRaises((ValueError,PolicyError)):
                self.run_pilot(self.raw(**fields))
        self.transport.assert_not_called()

    def test_robots_conservative_veto(self):
        for robots in ("User-agent: *\nDisallow: /wp-json/",
                       "User-agent: *\nDisallow: /*.php$",
                       "User-agent: *\nDisallow: /private\nUnknown: yes",
                       "Sitemap: https://catalog.example.com/sitemap.xml",
                       "User-agent: *\nCrawl-delay: 1.5"):
            with self.subTest(robots=robots),self.assertRaises(PolicyError):
                self.run_pilot(self.raw(robots_text=robots))
        self.transport.assert_not_called()

    def test_single_get_and_evidence(self):
        result=self.run_pilot()
        self.transport.assert_called_once_with("https://catalog.example.com"+PATH,
            "catalog.example.com",10.0,524288,accept="application/json",expected_ip="8.8.8.8")
        self.assertEqual(result["observations"][0]["price_minor"],4990000)
        self.assertEqual(result["evidence"]["sha256"],hashlib.sha256(self.body).hexdigest())
        self.assertEqual(self.db.execute("SELECT state FROM int_pilot_receipts").fetchone()[0],"succeeded")
        with self.assertRaises(PolicyError):
            self.run_pilot(self.raw(source="other-source"))
        self.assertEqual(self.transport.call_count,1)

    def test_redirect_and_retry_never_followed(self):
        self.transport.return_value=Response(302,{"location":"https://other.example.com"},b"")
        with self.assertRaises(FetchError):
            self.run_pilot()
        self.assertEqual(self.db.execute("SELECT state FROM int_pilot_receipts").fetchone()[0],"failed-review")
        with self.assertRaises(PolicyError):
            self.run_pilot()
        self.assertEqual(self.transport.call_count,1)

    def test_wrong_mime_or_bad_rows_fail(self):
        self.transport.return_value=Response(200,{"content-type":"application/json"},b'{"orders":[]}')
        with self.assertRaises(ValueError):
            self.run_pilot()
        self.assertEqual(self.db.execute("SELECT state FROM int_pilot_receipts").fetchone()[0],"failed-review")

    def test_receipt_survives_interruption(self):
        pilot=load_manifest(self.raw())
        self.ledger.reserve(pilot,utcnow())
        with self.assertRaises(PolicyError):
            self.run_pilot()
        self.transport.assert_not_called()

    def test_dns_mismatch_before_socket(self):
        with patch("intelligence.transport.public_ip",return_value="8.8.4.4"),patch("intelligence.transport.PinnedHTTPS") as conn:
            with self.assertRaises(PolicyError):
                https_get("https://catalog.example.com"+PATH,"catalog.example.com",10,524288,
                          accept="application/json",expected_ip="8.8.8.8")
            conn.assert_not_called()
