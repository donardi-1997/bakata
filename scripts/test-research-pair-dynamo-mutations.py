"""Mutation check for the DynamoDB pair ledger (on demand; needs boto3 and moto).

Each mutation removes one guarantee in a temporary copy; the Moto tests must fail.
Usage: PYTHONPATH not required. python scripts/test-research-pair-dynamo-mutations.py
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
TARGET = "services/intelligence/intelligence/research_pair_dynamo_ledger.py"
MUTATIONS = {
    "no writer token check": ('stored.get("writer") == {"S": writer} and ', ""),
    "no re-read (false conflict)": ('if stored and stored.get("writer")', 'if False and stored.get("writer")'),
    "all errors are conflict": ('if _error_code(exc) != "ConditionalCheckFailedException":\n',
                                'if False:\n'),
    "unconditional put": ('Item=dict(key, event={"S": raw}, writer={"S": writer}),\n'
                          '                                 ConditionExpression="attribute_not_exists(pk)")',
                          'Item=dict(key, event={"S": raw}, writer={"S": writer}))'),
    "slot reusable": ('"Item": dict(SLOT, pair={"S": pair}),\n                         "ConditionExpression": "attribute_not_exists(pk)"',
                      '"Item": dict(SLOT, pair={"S": pair})'),
    "any cancellation is occupied": ('if "ConditionalCheckFailed" not in reasons:', "if False:"),
    "lost initialize not recognised": ('if slot and slot.get("pair") == {"S": pair} and stored == dict(first, event={"S": raw}):',
                                       "if False:"),
    "foreign authorization recognised": ('if slot and slot.get("pair") == {"S": pair} and stored == dict(first, event={"S": raw}):',
                                         'if slot and slot.get("pair") == {"S": pair}:'),
    "no stale-revision check": ("if len(events) != expected_revision:", "if False:"),
    "no slot ownership check": ('if not slot or slot.get("pair") != {"S": self.pair}:', "if False:"),
    "no item-count limit": ('if page.get("LastEvaluatedKey") or not 1 <= len(items) <= MAX_EVENTS:', "if not items:"),
    "writer allowed on first revision": ('expected = {"pk", "sk", "event"} if revision == 1 else', "expected = set(item) if revision == 1 else"),
    "token not attached on uncertain error": ("                exc.bakata_writer = writer\n", ""),
    "token not attached on failed verification": ("                read_error.bakata_writer = writer\n", ""),
}


def main():
    survived = []
    for name, (old, new) in MUTATIONS.items():
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "r"
            shutil.copytree(REPO / "services", copy / "services", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(REPO / "infra", copy / "infra")
            path = copy / TARGET
            text = path.read_text(encoding="utf-8")
            if old not in text:
                print(f"{name:38} -> STALE (pattern not found)")
                survived.append(name)
                continue
            mutated = text.replace(old, new, 1)
            try:  # a mutation that breaks syntax would "fail" for the wrong reason
                compile(mutated, str(path), "exec")
            except SyntaxError:
                print(f"{name:38} -> INVALID (syntax error)")
                survived.append(name)
                continue
            path.write_text(mutated, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "services/intelligence/tests",
                 "-p", "test_research_pair_dynamo_ledger.py"],
                cwd=copy, capture_output=True, text=True,
                env={**os.environ, "PYTHONPATH": "services/intelligence", "PYTHONDONTWRITEBYTECODE": "1"})
            skipped = "skipped=" in result.stderr
            detected = result.returncode != 0 and not skipped
            print(f"{name:38} -> {'DETECTED' if detected else 'SKIPPED' if skipped else 'SURVIVED'}")
            if not detected:
                survived.append(name)
    print(f"{len(MUTATIONS) - len(survived)}/{len(MUTATIONS)} mutations detected")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
