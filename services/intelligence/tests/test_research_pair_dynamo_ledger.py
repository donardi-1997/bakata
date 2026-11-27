"""DynamoDB pair ledger with Moto: no network, fictitious credentials, no AWS."""
import json
import os
from pathlib import Path
import unittest

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
    from moto import mock_aws
except ImportError:  # the intelligence image has no AWS SDK
    boto3 = None

from intelligence.research_pair_contract import replay
from intelligence.research_pair_ledger import Conflict

TEMPLATE = Path(__file__).resolve().parents[3] / "infra" / "research-aws" / "pair-controller.json"
TABLE = "bakata-research-ci-pair-ledger"
NONCE = "0" * 32


def auth(nonce=NONCE):
    from test_research_pair_controller import NOW, UNTIL
    return {"type": "authorize", "run": "fixture-ci", "at": NOW, "until": UNTIL, "nonce": nonce}


@unittest.skipIf(boto3 is None, "boto3/moto not installed")
class DynamoLedgerTests(unittest.TestCase):
    def setUp(self):
        from intelligence.research_pair_dynamo_ledger import DynamoLedger
        self.DynamoLedger = DynamoLedger
        os.environ.update(AWS_ACCESS_KEY_ID="fixture", AWS_SECRET_ACCESS_KEY="fixture",
                          AWS_SESSION_TOKEN="fixture", AWS_DEFAULT_REGION="us-east-1",
                          AWS_EC2_METADATA_DISABLED="true")
        self.mock = mock_aws()
        self.mock.start()
        self.client = boto3.client("dynamodb", region_name="us-east-1",
                                   config=Config(retries={"total_max_attempts": 1}))
        props = json.loads(TEMPLATE.read_text())["Resources"]["PairLedger"]["Properties"]
        self.client.create_table(TableName=TABLE, BillingMode="PAY_PER_REQUEST",
                                 AttributeDefinitions=props["AttributeDefinitions"], KeySchema=props["KeySchema"])
        self.ledger = DynamoLedger.initialize(self.client, TABLE, auth())

    def tearDown(self):
        self.mock.stop()

    def put_raw(self, sk, event, **extra):
        self.client.put_item(TableName=TABLE, Item={"pk": {"S": "PAIR#" + NONCE}, "sk": {"S": sk},
                                                    "event": {"S": event}, **extra})

    def test_initialize_occupies_slot_forever(self):
        self.assertEqual(self.ledger.snapshot()[0], 1)
        from intelligence.research_pair_dynamo_ledger import SlotOccupied
        other_deadline = dict(auth(), until=auth()["until"] - 1)
        for authorization in (auth("1" * 32), other_deadline):
            with self.subTest(authorization), self.assertRaises(SlotOccupied):
                self.DynamoLedger.initialize(self.client, TABLE, authorization)
        # The exact same authorization (lost response, operator retry) is recognised, not recreated.
        self.assertEqual(self.DynamoLedger.initialize(self.client, TABLE, auth()).snapshot()[0], 1)
        claim = {"type": "claim-launch", "role": "proxy", "at": auth()["at"]}
        self.ledger.append(1, claim)
        self.assertEqual(self.DynamoLedger.initialize(self.client, TABLE, auth()).snapshot()[0], 2)

    def test_initialize_cancelled_for_other_reasons_is_uncertain_not_occupied(self):
        from intelligence.research_pair_dynamo_ledger import SlotOccupied
        props = json.loads(TEMPLATE.read_text())["Resources"]["PairLedger"]["Properties"]
        self.client.create_table(TableName="other-pair-ledger", BillingMode="PAY_PER_REQUEST",
                                 AttributeDefinitions=props["AttributeDefinitions"], KeySchema=props["KeySchema"])

        def conflicted(**kw):
            raise ClientError({"Error": {"Code": "TransactionCanceledException", "Message": "x"},
                               "CancellationReasons": [{"Code": "TransactionConflict"}, {"Code": "None"}]},
                              "TransactWriteItems")
        self.client.transact_write_items = conflicted
        with self.assertRaises(ClientError) as raised:
            self.DynamoLedger.initialize(self.client, "other-pair-ledger", auth())
        self.assertNotIsInstance(raised.exception, SlotOccupied)
        self.assertNotIn("Item", self.client.get_item(TableName="other-pair-ledger",
            Key={"pk": {"S": "PAIR#SLOT"}, "sk": {"S": "ACTIVE"}}))
        with self.assertRaisesRegex(ValueError, "Slot does not belong"):
            self.DynamoLedger(self.client, TABLE, "1" * 32)
        self.assertEqual(self.DynamoLedger(self.client, TABLE, NONCE).snapshot()[0], 1)

    def test_append_and_stale_revision(self):
        claim = {"type": "claim-launch", "role": "proxy", "at": auth()["at"]}
        self.assertEqual(self.ledger.append(1, claim), 2)
        with self.assertRaises(Conflict):
            self.ledger.append(1, claim)
        with self.assertRaises(ValueError):  # reducer refuses a second claim
            self.ledger.append(2, claim)
        self.assertEqual(self.ledger.snapshot()[0], 2)

    def test_identical_events_from_two_controllers_conflict(self):
        # Two writers read revision 1 and append the *same* event: only one may win,
        # otherwise both would perform the side effect.
        other = self.DynamoLedger(self.client, TABLE, NONCE)
        claim = {"type": "claim-launch", "role": "proxy", "at": auth()["at"]}
        original = other._read
        other._read = lambda: original()[:1]  # stale snapshot taken before A's write
        self.assertEqual(self.ledger.append(1, claim), 2)
        with self.assertRaises(Conflict):
            other.append(1, claim)
        self.assertEqual(self.ledger.snapshot()[0], 2)

    def test_retried_own_write_is_not_a_false_conflict(self):
        claim = {"type": "claim-launch", "role": "proxy", "at": auth()["at"]}
        real_put = self.client.put_item

        def put_then_retry(**kw):
            real_put(**kw)       # first attempt lands, response lost
            return real_put(**kw)  # SDK-style retry fails the condition
        self.client.put_item = put_then_retry
        self.assertEqual(self.ledger.append(1, claim), 2)
        self.assertEqual(self.ledger.snapshot()[0], 2)

    def test_non_conditional_errors_are_not_conflict(self):
        def throttled(**kw):
            raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException", "Message": "x"}}, "PutItem")
        self.client.put_item = throttled
        with self.assertRaises(ClientError) as raised:
            self.ledger.append(1, {"type": "claim-launch", "role": "proxy", "at": auth()["at"]})
        self.assertRegex(raised.exception.bakata_writer, r"^[0-9a-f]{32}$")  # for later reconciliation

    def test_failed_verification_read_is_uncertain_with_token(self):
        claim = {"type": "claim-launch", "role": "proxy", "at": auth()["at"]}
        real_put, real_get = self.client.put_item, self.client.get_item

        def put_then_retry(**kw):
            real_put(**kw)
            return real_put(**kw)

        def get_fails_after_put(**kw):
            if kw["Key"]["sk"] == {"S": "REV#0002"}:
                raise ClientError({"Error": {"Code": "InternalServerError", "Message": "x"}}, "GetItem")
            return real_get(**kw)
        self.client.put_item, self.client.get_item = put_then_retry, get_fails_after_put
        with self.assertRaises(ClientError) as raised:
            self.ledger.append(1, claim)
        self.assertNotIsInstance(raised.exception, Conflict)
        token = raised.exception.bakata_writer
        self.client.get_item = real_get
        stored = real_get(TableName=TABLE, Key={"pk": {"S": "PAIR#" + NONCE}, "sk": {"S": "REV#0002"}})["Item"]
        self.assertEqual(stored["writer"], {"S": token})  # the reconciler can prove the write is ours

    def test_corrupted_partition_fails_closed(self):
        claim = json.dumps({"type": "claim-launch", "role": "proxy", "at": auth()["at"]},
                           sort_keys=True, separators=(",", ":"))
        cases = {
            "gap": lambda: self.put_raw("REV#0003", claim, writer={"S": "a" * 32}),
            "noncanonical": lambda: self.put_raw("REV#0002", claim.replace(",", ", "), writer={"S": "a" * 32}),
            "extra attribute": lambda: self.put_raw("REV#0002", claim, writer={"S": "a" * 32}, x={"S": "1"}),
            "missing writer": lambda: self.put_raw("REV#0002", claim),
            "writer on first revision": lambda: self.client.update_item(
                TableName=TABLE, Key={"pk": {"S": "PAIR#" + NONCE}, "sk": {"S": "REV#0001"}},
                UpdateExpression="SET writer = :w", ExpressionAttributeValues={":w": {"N": "7"}}),
            "invalid event": lambda: self.put_raw("REV#0002", '{"type":"bind"}', writer={"S": "a" * 32}),
        }
        for name, corrupt in cases.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                corrupt()
                with self.assertRaises(ValueError):
                    self.ledger.snapshot()

    def test_too_many_items_fails_closed(self):
        for revision in range(2, 35):
            self.put_raw("REV#%04d" % revision, "{}", writer={"S": "a" * 32})
        with self.assertRaisesRegex(ValueError, "revisions"):
            self.ledger.snapshot()

    def test_pair_controller_lifecycle_on_dynamodb(self):
        from test_research_pair_controller import FakeECS, UNTIL, config
        from intelligence.research_pair_controller import PairController
        ecs, now = FakeECS(), [auth()["at"]]
        ctl = PairController(self.ledger, ecs, config(), clock=lambda: now[0], enabled=True)
        proxy, worker = ctl.launch("proxy"), ctl.launch("worker")
        now[0] = UNTIL
        self.assertEqual(sorted(ctl.supervise()["requested"]), ["proxy", "worker"])
        for arn in (proxy, worker):
            ecs.tasks[arn]["lastStatus"] = ecs.tasks[arn]["desiredStatus"] = "STOPPED"
        self.assertEqual(ctl.supervise(), {"state": "both-stopped"})
        self.assertTrue(replay(self.ledger.snapshot()[1]).both_stopped)
        self.assertEqual(ecs.count("run"), 2)


if __name__ == "__main__":
    unittest.main()
