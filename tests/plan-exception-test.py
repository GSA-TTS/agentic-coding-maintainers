"""Offline shadow-mode replay tests: no operation is executed."""

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts/plan-exception.py"
HEAD = "a" * 40
OLD = "b" * 40
FIXTURE = pathlib.Path(tempfile.mkdtemp(prefix="exception-attempts-"))
FIXTURE.chmod(0o700)
(FIXTURE / "MANIFEST.md").write_text(
    "Synthetic private attempt ledger for tests/plan-exception-test.py. No real task evidence; "
    "safe for operator disposal. An interrupted test may have only some items.\n", encoding="utf-8")
LEDGER = FIXTURE / "attempts.jsonl"
LEDGER.write_bytes(b"")
LEDGER.chmod(0o600)


def snapshot(**changes):
    value = {"schema_version": 1, "task_id": "case-1", "blocker": "UNKNOWN",
             "task_head_sha": HEAD, "evidence_head_sha": None, "evidence_coverage": "none",
             "observed_at": "2020-01-01T00:00:00Z",
             "operation": "remote_read", "measurement": None, "policy_authorization": False,
             "independent_work_ready": False, "write_settlement": "not_attempted"}
    value.update(changes)
    return value


def write_attempts(rows):
    LEDGER.write_bytes("".join(json.dumps(row) + "\n" for row in rows).encode())
    LEDGER.chmod(0o600)


def attempt(number, *, task="case-1", head=HEAD, when="2019-12-31T00:00:00Z"):
    return {"schema_version": 1, "attempt_id": f"attempt-{number}", "task_id": task,
            "head_sha": head, "measurement": "check_status", "outcome": "unverified", "recorded_at": when}


def run(value, *, path=LEDGER):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    return subprocess.run([sys.executable, "-I", "-B", str(CLI), "--attempt-ledger", str(path)],
                          input=raw, capture_output=True, check=False, timeout=5)


def action(expected, *, attempts=0, **changes):
    write_attempts([attempt(n) for n in range(attempts)])
    response = run(snapshot(**changes))
    assert response.returncode == 0 and not response.stderr, response.stderr
    result = json.loads(response.stdout)
    assert result["action"] == expected, (result, expected)
    assert result["mode"] == "SHADOW_ONLY" and result["current_verdict"] == "UNVERIFIED"
    assert result["execution_performed"] is False
    assert result["attempts_for_head_from_private_ledger"] == attempts


def refuses(value):
    write_attempts([])
    response = run(value)
    assert response.returncode == 3 and b"UNVERIFIED" in response.stderr and not response.stdout, response


action("RECONCILE_WRITE_READ_ONLY", blocker="PARTIAL_WRITE", operation="remote_write", write_settlement="unknown")
action("RECONCILE_WRITE_READ_ONLY", blocker="POLICY_DECISION", operation="remote_write", write_settlement="unknown")
action("HUMAN_AUTHORIZATION", blocker="CODE_BUG", operation="remote_write")
action("REMEASURE_HEAD_READ_ONLY", blocker="STALE_HEAD", evidence_head_sha=OLD, independent_work_ready=True)
action("HUMAN_POLICY_DECISION", blocker="POLICY_DECISION", measurement="check_status")
action("DEFER_CI_MEASUREMENT", blocker="CI_OUTAGE")
action("REVIEW_INDEPENDENT_WORK", blocker="CI_OUTAGE", independent_work_ready=True)
action("OWNER_REWORK_REVIEW", blocker="CODE_BUG", evidence_coverage="complete", evidence_head_sha=HEAD)
action("MEASURE_SOURCE_READ_ONLY", blocker="MISSING_PROVENANCE", measurement="source_provenance")
action("MEASURE_READ_ONLY", blocker="UNKNOWN", measurement="check_status", attempts=1)
action("REVIEW_INDEPENDENT_WORK", blocker="UNKNOWN", measurement="check_status", attempts=2,
       independent_work_ready=True)
action("HUMAN_TRIAGE", blocker="UNKNOWN", measurement="check_status", attempts=2)
action("HUMAN_TRIAGE", blocker="CODE_BUG", evidence_coverage="none", evidence_head_sha=HEAD)
action("HUMAN_TRIAGE", blocker="CODE_BUG", evidence_coverage="complete", task_head_sha=None,
       evidence_head_sha=None)
action("HUMAN_TRIAGE", blocker="CODE_BUG", evidence_coverage="complete", evidence_head_sha=None)

refuses(snapshot(schema_version=True))
refuses(snapshot(blocker=[]))
refuses(snapshot(operation=[]))
refuses(snapshot(write_settlement=[]))
refuses(snapshot(evidence_coverage=[]))
refuses(snapshot(observed_at="2020-99-99T99:99:99Z"))
refuses(snapshot(measurement="gh pr merge"))
refuses(snapshot(policy_authorization="yes"))
refuses(snapshot(extra="untrusted free text"))
refuses(snapshot(attempts_for_head=0))
refuses(snapshot(blocker="PARTIAL_WRITE", operation="remote_read"))
refuses(snapshot(blocker="PARTIAL_WRITE", operation="remote_write", write_settlement="confirmed"))
refuses(snapshot(write_settlement="unknown", operation="remote_read"))
refuses(snapshot(blocker="STALE_HEAD", evidence_head_sha=HEAD))
refuses(snapshot(blocker="STALE_HEAD", evidence_head_sha=None))
refuses(snapshot(task_head_sha=None, measurement="check_status"))
refuses(b'{"schema_version":1,"schema_version":1}')
refuses(b"x" * 8193)
refuses(b"")
# A changed head gets a fresh budget; a malformed OTHER case still poisons the
# whole ledger rather than silently disappearing from the denominator.
write_attempts([attempt(1, head=OLD), attempt(2, task="other-case", head=HEAD)])
fresh = run(snapshot(measurement="check_status"))
assert fresh.returncode == 0 and json.loads(fresh.stdout)["attempts_for_head_from_private_ledger"] == 0
write_attempts([attempt(1), attempt(1)])
assert run(snapshot()).returncode == 3
write_attempts([attempt(1, task="unrelated"), dict(attempt(2, task="unrelated"), measurement=[])])
bad_other = run(snapshot(measurement="check_status"))
assert bad_other.returncode == 3 and b"UNVERIFIED" in bad_other.stderr and not bad_other.stdout
write_attempts([attempt(1, when="2020-01-02T00:00:00Z")])
assert run(snapshot()).returncode == 3
write_attempts([attempt(1)])
assert run(snapshot(task_head_sha=None, measurement="check_status")).returncode == 3
LEDGER.chmod(0o644)
assert run(snapshot()).returncode == 3
LEDGER.chmod(0o600)
LINK = FIXTURE / "linked.jsonl"
LINK.symlink_to(LEDGER)
assert run(snapshot(), path=LINK).returncode == 3
ANCESTOR = FIXTURE / "linked-parent"
ANCESTOR.symlink_to(FIXTURE, target_is_directory=True)
assert run(snapshot(), path=ANCESTOR / "attempts.jsonl").returncode == 3
assert run(snapshot(), path=FIXTURE / "absent.jsonl").returncode == 3
print("exception_attempt_fixture=" + str(FIXTURE), file=sys.stderr)
print("plan-exception tests: PASS")
