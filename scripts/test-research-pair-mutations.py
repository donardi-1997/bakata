"""Mutation check for the offline pair controller (on demand, not in CI).

Each mutation removes one critical guarantee in a temporary copy of
services/intelligence; the controller tests must fail for every mutation.
Usage: python scripts/test-research-pair-mutations.py
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1] / "services" / "intelligence"
TARGET = "intelligence/research_pair_controller.py"
MUTATIONS = {
    "no post-claim deadline recheck": (
        'if _now(self.clock()) + LAUNCH_MARGIN >= state.until:\n            raise ValueError("Deadline reached after claim',
        'if False:\n            raise ValueError("Deadline reached after claim'),
    "repeat uncertain stop": ("if member.stop_claimed:\n", "if False:\n"),
    "worker without live proxy": ('if self._describe(state, "proxy", proxy.identity) != "running":', "if False:"),
    "proxy starting accepted": ('!= "running":\n                raise ValueError("Proxy not RUNNING")',
                                'not in ("running", "starting"):\n                raise ValueError("Proxy not RUNNING")'),
    "no post-claim proxy recheck": ("if latest.proxy.stop_claimed or latest.proxy.stopped:", "if False:"),
    "no peer-down stop": ("peer_down = any(", "peer_down = False and any("),
    "stop claim ignored": ("stop_decided = any(", "stop_decided = False and any("),
    "no per-role isolation": ("            except Exception as exc:  # recorded",
                              "            except ZeroDivisionError as exc:  # recorded"),
    "unverifiable does not stop": ("unverifiable = bool(errors)", "unverifiable = False"),
    "no bind retry": ("            except Conflict:\n                continue",
                      "            except Conflict:\n                raise"),
    "nonce not in token": ("state.nonce, role]", "role]"),
    "skip startedBy identity check": ('or task.get("startedBy") != token[:32]', "or False"),
    "stale clock for stop claim": ('{"type": "claim-stop", "role": role, "at": _now(self.clock())}',
                                   '{"type": "claim-stop", "role": role, "at": now}'),
    "role override accepted": ('if overrides.get("taskRoleArn") or overrides.get("executionRoleArn"):',
                               "if False:"),
    "command/env override accepted": ('if set(overrides) - {"containerOverrides"} or overrides.get("containerOverrides") != expected:',
                                      "if False:"),
    "unsafe own task not stopped": ("observed[role] = exc.status", "pass"),
    "observation not isolated": ("except Exception as exc:  # identity unverified",
                                 "except ZeroDivisionError as exc:  # identity unverified"),
    "foreign subnet accepted": ('if subnets and subnets != {getattr(c, role + "_subnet")}:', "if False:"),
    "running without ENI accepted": ('if last == "RUNNING" and not subnets:', "if False:"),
    "claim without invocation time": ("if self.remaining is not None and self.remaining() < MIN_EFFECT_SECONDS:",
                                      "if False:"),
    "skewed claim defers reconcile": ("abs(now - claimed_at[role])", "(now - claimed_at[role])"),
    "supervise ignores enabled": (
        '        """Tick: never launches, never releases the slot; isolates failures per role."""\n'
        "        self._require_enabled()",
        '        """Tick."""'),
}


def main():
    survived = []
    for name, (old, new) in MUTATIONS.items():
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "si"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__"))
            path = copy / TARGET
            text = path.read_text(encoding="utf-8")
            if old not in text:
                print(f"{name:32} -> STALE (pattern not found)")
                survived.append(name)
                continue
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "unittest", "tests.test_research_pair_controller"],
                                    cwd=copy, capture_output=True, text=True,
                                    env={**os.environ, "PYTHONPATH": ".", "PYTHONDONTWRITEBYTECODE": "1"})
            detected = result.returncode != 0
            print(f"{name:32} -> {'DETECTED' if detected else 'SURVIVED'}")
            if not detected:
                survived.append(name)
    print(f"{len(MUTATIONS) - len(survived)}/{len(MUTATIONS)} mutations detected")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
