"""Offline shadow-mode replay tests: no operation is executed."""

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts/plan-exception.py"
HEAD = "a" * 40
OLD = "b" * 40


def snapshot(**changes):
    value = {"schema_version": 1, "task_id": "case-1", "blocker": "UNKNOWN",
             "task_head_sha": HEAD, "evidence_head_sha": None, "evidence_coverage": "none",
             "attempts_for_head": 0, "observed_at": "2020-01-01T00:00:00Z",
             "operation": "remote_read", "measurement": None, "policy_authorization": False,
             "independent_work_ready": False, "write_settlement": "not_attempted"}
    value.update(changes)
    return value


def run(value):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    return subprocess.run([sys.executable, "-I", "-B", str(CLI)], input=raw, capture_output=True, check=False, timeout=5)


def action(expected, **changes):
    response = run(snapshot(**changes))
    assert response.returncode == 0 and not response.stderr, response.stderr
    result = json.loads(response.stdout)
    assert result["action"] == expected, (result, expected)
    assert result["mode"] == "SHADOW_ONLY" and result["current_verdict"] == "UNVERIFIED"
    assert result["execution_performed"] is False


def refuses(value):
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
action("MEASURE_READ_ONLY", blocker="UNKNOWN", measurement="check_status", attempts_for_head=1)
action("REVIEW_INDEPENDENT_WORK", blocker="UNKNOWN", measurement="check_status", attempts_for_head=2,
       independent_work_ready=True)
action("HUMAN_TRIAGE", blocker="UNKNOWN", measurement="check_status", attempts_for_head=2)
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
refuses(snapshot(blocker="PARTIAL_WRITE", operation="remote_read"))
refuses(snapshot(blocker="PARTIAL_WRITE", operation="remote_write", write_settlement="confirmed"))
refuses(snapshot(write_settlement="unknown", operation="remote_read"))
refuses(snapshot(blocker="STALE_HEAD", evidence_head_sha=HEAD))
refuses(snapshot(blocker="STALE_HEAD", evidence_head_sha=None))
refuses(b'{"schema_version":1,"schema_version":1}')
refuses(b"x" * 8193)
refuses(b"")
print("plan-exception tests: PASS")
