"""Integrate real isolated WP-CLI worker with Moto persistence; hosted CI only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import boto3
from botocore.config import Config
from moto import mock_aws
from intelligence.dropify_capture import policy
from intelligence.research_receipts import ResearchReceipts
from intelligence.research_worker import coordinate


def main():
    if os.environ.get("GITHUB_ACTIONS")!="true" or os.environ.get("RUNNER_ENVIRONMENT")!="github-hosted":
        raise RuntimeError("Disposable hosted CI required")
    exchange,db,image,worker=sys.argv[1:]
    run="fixture-persistent-ci"
    until=int(time.time())+300
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
        command=["docker","run","--name",worker,"--pull=never","--network","container:"+db,
            "--read-only","--tmpfs","/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777","--memory","768m","--cpus",".75",
            "--pids-limit","64","--cap-drop","ALL","--security-opt","no-new-privileges",
            "-v",exchange+":/exchange","-e","BAKATA_RESEARCH_FIXTURE=1","-e","BAKATA_RESEARCH_PERSIST=1",
            "-e","BAKATA_RESEARCH_RUN="+run,"-e","BAKATA_RESEARCH_UNTIL="+str(until),image]
        process=subprocess.Popen(command)
        try:
            result=coordinate(exchange,r,plan)
            assert result=={"state":"terminal-page-observed","pages":2,"rows":13,"coverage_verified":False,"provider_queries":0}
            assert process.wait(timeout=30)==0
            for page in (1,2):
                receipt=r.status(plan,page)["page"]
                assert receipt["state"]=="archived"
                raw,digest,version=r._read_evidence(receipt["object_key"],receipt["attempt"],receipt["version_id"])
                assert b"canary" not in raw and digest==receipt["sha256"] and version==receipt["version_id"]
            assert r.status(plan,3)["page"] is None
            assert len(s3.list_object_versions(Bucket=bucket)["Versions"])==2
            try:
                coordinate(exchange,r,plan)
            except ValueError:
                pass
            else:
                raise AssertionError("Duplicate coordinator accepted")
            assert len(s3.list_object_versions(Bucket=bucket)["Versions"])==2
            print("Persistent fixture: two reserved pages, 13 products, versioned evidence, no third request.")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__=="__main__":
    main()
