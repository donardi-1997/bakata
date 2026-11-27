"""AWS service emulator integration tests. Never use real AWS credentials."""
from datetime import datetime,timezone
import hashlib
import json
import unittest
from unittest.mock import patch

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from moto import mock_aws
from intelligence.dropify_capture import policy,approval
from intelligence.research_receipts import ResearchReceipts


class ReceiptsTests(unittest.TestCase):
    def setUp(self):
        self.mock=mock_aws()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        args={"region_name":"us-east-1","aws_access_key_id":"fixture","aws_secret_access_key":"fixture",
              "aws_session_token":"fixture","config":Config(retries={"total_max_attempts":1})}
        self.ddb=boto3.client("dynamodb",**args)
        self.s3=boto3.client("s3",**args)
        self.table="fixture-ledger"
        self.bucket="fixture-research-evidence"
        self.ddb.create_table(TableName=self.table,BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName":"pk","AttributeType":"S"},{"AttributeName":"sk","AttributeType":"S"}],
            KeySchema=[{"AttributeName":"pk","KeyType":"HASH"},{"AttributeName":"sk","KeyType":"RANGE"}])
        self.s3.create_bucket(Bucket=self.bucket)
        self.s3.put_bucket_versioning(Bucket=self.bucket,VersioningConfiguration={"Status":"Enabled"})
        self.now=1795748400
        self.plan=policy("fixture-first","7",1,3,self.now+600,"ci-reviewer","fixture-artifact")
        self.r=self.worker()
        self.r.register(self.plan,now=self.now)

    def worker(self):
        return ResearchReceipts(self.ddb,self.s3,table=self.table,bucket=self.bucket)

    def page(self,n,*,count=10,start=None,plan=None,at=None):
        plan=plan or self.plan
        start=start if start is not None else (n-1)*10+1
        rows=[{"external_id":str(i),"sku":str(i),"title":"Synthetic product","type":"simple",
               "base_price":"7000","suggested_price":"17000","simple_stock":5,"categories":[],"warehouse":"Fixture"}
              for i in range(start,start+count)]
        return json.dumps({"schema":"bakata-dropify-bridge-v1","store_id":plan["store"],"page":n,
            "page_size":10,"offset":(n-1)*10,"possible_next":count==10,"rows":rows,
            "captured_at":datetime.fromtimestamp(at if at is not None else self.now,timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "approval_ref":approval(plan["run"],n),"query_sha256":hashlib.sha256(b"").hexdigest()}).encode()

    def reserve(self,n):
        return self.r.reserve(self.plan,n,now=self.now)["attempt"]

    def test_normal_progress_cooldown_and_partial(self):
        attempt=self.reserve(1)
        result=self.r.persist(self.plan,1,attempt,self.page(1),now=self.now)
        self.assertEqual((result["state"],result["next_page"],result["rows"]),("open",2,10))
        with self.assertRaises(ValueError):
            self.worker().reserve(self.plan,2,now=self.now+9)
        self.now+=10
        attempt=self.reserve(2)
        result=self.worker().persist(self.plan,2,attempt,self.page(2,count=3),now=self.now)
        self.assertEqual(result["state"],"terminal-page-observed")
        self.assertFalse(result["coverage_verified"])
        self.assertEqual(result["rows"],3)
        with self.assertRaises(ValueError):
            self.r.reserve(self.plan,3,now=self.now+10)
        receipt=self.r.status(self.plan,2)["page"]
        self.assertEqual(receipt["state"],"archived")
        self.assertEqual(receipt["version_id"],result["version_id"])
        self.assertEqual(receipt["sha256"],hashlib.sha256(self.page(2,count=3)).hexdigest())

    def test_uncertain_reservation_blocks_all_other_windows(self):
        attempt=self.reserve(1)
        other=policy("fixture-other","7",2,2,self.now+1800,"ci-reviewer","fixture-artifact")
        self.r.register(other,now=self.now)
        with self.assertRaises(ValueError):
            self.worker().reserve(other,2,now=self.now+900)
        self.assertTrue(self.worker().status(self.plan,1)["requires_reconciliation"])
        with self.assertRaises(ClientError):
            self.worker().recover(self.plan,1,attempt,now=self.now+900)
        self.assertTrue(self.r.status(self.plan,1)["requires_reconciliation"])
        with self.assertRaises(ValueError):
            self.worker().reserve(self.plan,1,now=self.now+1)

    def test_recovery_after_s3_write_and_before_commit(self):
        attempt=self.reserve(1)
        raw=self.page(1)
        with patch.object(self.r,"_finish",side_effect=RuntimeError("Synthetic task interruption")):
            with self.assertRaises(RuntimeError):
                self.r.persist(self.plan,1,attempt,raw,now=self.now)
        self.assertTrue(self.worker().status(self.plan,1)["requires_reconciliation"])
        result=self.worker().recover(self.plan,1,attempt,now=self.now+700)
        self.assertEqual(result["sha256"],hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["provider_queries"],0)
        self.assertFalse(self.r.status(self.plan,1)["requires_reconciliation"])
        versions=self.s3.list_object_versions(Bucket=self.bucket)["Versions"]
        self.assertEqual(len(versions),1)

    def test_transaction_conflict_is_atomic(self):
        control,run,page=self.r._keys(self.plan,1)
        before=self.r._read(run)
        self.reserve(1)
        # Simulate a stale claimant that read the store before the winner.
        second=self.r._key("7","PAGE#fixture-other#0001")
        with self.assertRaises(ClientError):
            self.r._txn(self.r._check(run,before),self.r._put(control,None,{"state":"idle","not_before":0}),
                        self.r._put(second,None,{"state":"reserved"}))
        self.assertIsNone(self.r._read(second))
        self.assertEqual(self.r._read(page)["state"],"reserved")

    def test_existing_evidence_is_not_overwritten(self):
        attempt=self.reserve(1)
        with patch.object(self.r,"_finish",side_effect=RuntimeError("Interrupted")):
            with self.assertRaises(RuntimeError):
                self.r.persist(self.plan,1,attempt,self.page(1),now=self.now)
        with self.assertRaises(ClientError):
            self.worker().persist(self.plan,1,attempt,self.page(1,count=5),now=self.now)
        self.assertEqual(len(self.s3.list_object_versions(Bucket=self.bucket)["Versions"]),1)

    def test_duplicate_or_wrong_scope_stays_blocked(self):
        first=self.reserve(1)
        self.r.persist(self.plan,1,first,self.page(1),now=self.now)
        self.now+=10
        second=self.reserve(2)
        with self.assertRaisesRegex(ValueError,"scope"):
            self.r.persist(self.plan,2,second,self.page(1),now=self.now)
        with self.assertRaisesRegex(ValueError,"Non-increasing"):
            self.r.persist(self.plan,2,second,self.page(2,start=5),now=self.now)
        self.assertTrue(self.r.status(self.plan,2)["requires_reconciliation"])
        self.assertEqual(len(self.s3.list_object_versions(Bucket=self.bucket)["Versions"]),1)

    def test_live_plan_and_expired_authorization_rejected(self):
        live=policy("live","7",1,3,self.now+600,"operator","fixture-artifact")
        with self.assertRaisesRegex(ValueError,"Fixture-only"):
            self.r.register(live,now=self.now)
        with self.assertRaises(ValueError):
            self.r.reserve(self.plan,1,now=self.plan["until"])
        self.assertIsNone(self.r.status(self.plan,1)["page"])
        with self.assertRaises(ClientError):
            self.r.register(self.plan,now=self.now)


if __name__=="__main__":
    unittest.main()
