"""Integrate real isolated WP-CLI worker with Moto persistence; hosted CI only."""
import json
import os
from pathlib import Path
import sys
import time

import boto3
from botocore.config import Config
from moto import mock_aws
from intelligence.dropify_capture import policy
from intelligence.research_receipts import ResearchReceipts
from intelligence.research_worker import coordinate
from intelligence.research_credentials import SecretBinding,SCHEMA
from intelligence.research_fixture_gate import FixtureCredentialGate


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true" or os.environ.get("RUNNER_ENVIRONMENT")!="github-hosted":
        raise RuntimeError("Disposable hosted CI required")
    if (os.getuid(),os.getgid())!=(33,33):
        raise RuntimeError("Coordinator must match worker UID/GID")
    exchange,run,expiry=sys.argv[1:]
    until=int(expiry)
    directory=Path(exchange)
    if directory.is_symlink() or directory.stat().st_uid!=33 or directory.stat().st_gid!=33 or directory.stat().st_mode & 0o077:
        raise RuntimeError("Exchange must be owned by UID/GID 33 and private")
    plan=policy(run,"7",1,3,until,"ci-research","fixture-task-v1")
    with mock_aws():
        config=Config(retries={"total_max_attempts":1})
        options=dict(region_name="us-east-1",aws_access_key_id="fixture",aws_secret_access_key="fixture",aws_session_token="fixture",config=config)
        ddb=boto3.client("dynamodb",**options)
        s3=boto3.client("s3",**options)
        table="fixture-ledger"
        bucket="fixture-persistent-evidence"
        ddb.create_table(TableName=table,BillingMode="PAY_PER_REQUEST",AttributeDefinitions=[{"AttributeName":"pk","AttributeType":"S"},{"AttributeName":"sk","AttributeType":"S"}],KeySchema=[{"AttributeName":"pk","KeyType":"HASH"},{"AttributeName":"sk","KeyType":"RANGE"}])
        s3.create_bucket(Bucket=bucket)
        s3.put_bucket_versioning(Bucket=bucket,VersioningConfiguration={"Status":"Enabled"})
        r=ResearchReceipts(ddb,s3,table=table,bucket=bucket)
        sm=boto3.client("secretsmanager",**options)
        secret=sm.create_secret(Name="bakata/research/dropify/fixture-ci",
            SecretString=json.dumps({"schema":SCHEMA,"store_id":"7","token":"ci-only-token-canary"}))
        arn=secret["ARN"]
        gate=FixtureCredentialGate(sm,SecretBinding(arn,secret["VersionId"],arn.split(":")[4],"7"))
        result=coordinate(exchange,r,plan,credential_gate=gate)
        assert result=={"state":"terminal-page-observed","pages":2,"rows":13,"coverage_verified":False,"provider_queries":0}
        for page in (1,2):
            receipt=r.status(plan,page)["page"]
            assert receipt["state"]=="archived"
            raw,digest,version=r._read_evidence(receipt["object_key"],receipt["attempt"],receipt["version_id"])
            assert b"canary" not in raw and digest==receipt["sha256"] and version==receipt["version_id"]
        assert r.status(plan,3)["page"] is None
        for file in Path(exchange).glob("*.json"):
            assert b"ci-only-token-canary" not in file.read_bytes()
        assert len(s3.list_object_versions(Bucket=bucket)["Versions"])==2
        try:
            coordinate(exchange,r,plan)
        except ValueError:
            pass
        else:
            raise AssertionError("Duplicate coordinator accepted")
        assert len(s3.list_object_versions(Bucket=bucket)["Versions"])==2
        print("Persistent fixture: two reserved pages, 13 products, versioned evidence, no third request.")



if __name__=="__main__":
    main()
