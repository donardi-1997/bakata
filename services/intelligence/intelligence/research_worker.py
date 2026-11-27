"""One-shot fixture coordinator. Durable reservation precedes every local IPC request."""
import json
import os
from pathlib import Path
import time

from .dropify_capture import durable,policy,read_record
from .dropify_catalog import MAX_BYTES,unique
from .research_receipts import ResearchReceipts,plan_checked
from .storage import encode


def wait_file(path,deadline,*,clock=time.time,sleep=time.sleep):
    while clock()<deadline:
        if path.is_symlink():
            raise ValueError("Unexpected exchange symlink")
        if path.exists():
            return path
        sleep(.25)
    raise ValueError("Fixture exchange timed out")


def coordinate(exchange,receipts,plan,*,clock=time.time,sleep=time.sleep):
    plan_checked(plan)
    if plan["store"]!="7" or (plan["first"],plan["last"])!=(1,3):
        raise ValueError("Only the bounded synthetic fixture is supported")
    exchange=Path(exchange)
    if exchange.is_symlink() or not exchange.is_dir():
        raise ValueError("Private exchange required")
    deadline=min(clock()+180,plan["until"])
    ready=wait_file(exchange/"ready.json",deadline,clock=clock,sleep=sleep)
    if json.loads(read_record(ready,4096),object_pairs_hook=unique)!={"run":plan["run"],"store":"7"}:
        raise ValueError("Worker identity mismatch")
    # Refuse a second coordinator on the same task or a stale exchange.
    durable(exchange/"coordinator.json",encode({"run":plan["run"]}).encode())
    if any(exchange.glob("request-*")) or any(exchange.glob("response-*")) or any(exchange.glob("claim-*")):
        raise ValueError("Nonempty exchange")
    receipts.register(plan,now=int(clock()))
    pages=rows=0
    for page in range(1,4):
        if pages:
            sleep(10)
        if clock()>=deadline:
            raise ValueError("Task deadline reached")
        receipt=receipts.reserve(plan,page,now=int(clock()))
        request={"run":plan["run"],"store":"7","page":page,"attempt":receipt["attempt"],
                 "reserved_at":receipt["reserved_at"],"until":plan["until"]}
        # No output or retry if reservation is ambiguous; durable marker first.
        durable(exchange/f"request-{page:04d}.json",encode(request).encode())
        response=wait_file(exchange/f"response-{page:04d}.json",min(deadline,clock()+45),clock=clock,sleep=sleep)
        result=receipts.persist(plan,page,receipt["attempt"],read_record(response,MAX_BYTES),now=int(clock()))
        pages+=1
        rows+=result["rows"]
        if result["state"]!="open":
            return {"state":result["state"],"pages":pages,"rows":rows,"coverage_verified":False,"provider_queries":0}
    raise ValueError("Fixture did not terminate")


def main():
    # Only the reviewed task environment enables this synthetic path.
    import boto3
    from botocore.config import Config
    if os.environ.get("BAKATA_RESEARCH_FIXTURE")!="1" or os.environ.get("BAKATA_RESEARCH_PERSIST")!="1":
        raise ValueError("Fixture persistence disabled")
    run=os.environ["BAKATA_RESEARCH_RUN"]
    until=int(os.environ["BAKATA_RESEARCH_UNTIL"])
    plan=policy(run,"7",1,3,until,"fixture-worker","fixture-task-v1")
    region=os.environ["AWS_REGION"]
    if region!="us-east-1":
        raise ValueError("Reviewed region required")
    # No endpoint overrides, credentials in arguments, or application retries.
    config=Config(retries={"total_max_attempts":1},connect_timeout=3,read_timeout=10,
                  ignore_configured_endpoint_urls=True)
    receipts=ResearchReceipts(boto3.client("dynamodb",region_name=region,config=config),
        boto3.client("s3",region_name=region,config=config),
        table=os.environ["BAKATA_LEDGER"],bucket=os.environ["BAKATA_EVIDENCE_BUCKET"])
    print(encode(coordinate("/exchange",receipts,plan)))


if __name__=="__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Fixture coordinator blocked; reconcile durable ledger. No automatic retry.")
