"""Build a real ledger-derived but entirely synthetic CI draft plan."""
import os
from contextlib import ExitStack
from datetime import datetime, timezone
from test_approved_draft import fixture
from intelligence.approved_draft import prepare
from intelligence.storage import encode

if os.environ.get("BAKATA_CI_FIXTURES")!="1":
    raise SystemExit("CI fixture required")
now=datetime.now(timezone.utc).replace(microsecond=0)
with ExitStack() as stack:
    ledger,bridge,commercial,event=fixture(stack,now)
    print(encode(prepare(ledger,bridge,commercial,"7","96",decision_sha256=event["sha256"],
        reviewer_id=int(os.environ["BAKATA_DRAFT_REVIEWER"]),category_id=int(os.environ["BAKATA_DRAFT_CATEGORY"]),
        mapping_ref="map",title="CI Approved Draft",target_bps=2500,step_minor=100000,
        ceiling_minor=20000000,now=now)))
