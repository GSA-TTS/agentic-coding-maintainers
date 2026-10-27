"""Offline adversarial replay fixtures; no GitHub or model calls."""

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts/evaluate-exception-replay.py"


def case(cid, *, human="HUMAN_TRIAGE", planner="HUMAN_TRIAGE", verdict="UNVERIFIED", independent=True):
    return {"case_id": cid, "maintainer_action": human, "planner_action": planner,
            "planner_verdict": verdict, "independent_label": independent}


def replay(expected, cases):
    return subprocess.run([sys.executable, "-I", "-B", str(CLI)],
                          input=json.dumps({"schema_version": 1, "expected_case_ids": expected,
                                            "cases": cases}).encode(), capture_output=True, check=False, timeout=5)


def report(result, *, expected_rc):
    assert result.returncode == expected_rc and not result.stderr, result.stderr
    value = json.loads(result.stdout)
    assert value["rollout_status"] == "NOT_EVALUATED" and value["execution_performed"] is False
    assert value["limitation"].startswith("expected IDs")
    assert "case-1" not in result.stdout.decode()  # no raw case IDs
    return value


good = report(replay(["case-1", "case-2"], [case("case-1"), case("case-2", human="DEFER_CI_MEASUREMENT",
                                                              planner="REVIEW_INDEPENDENT_WORK")]), expected_rc=0)
assert good["expected_count"] == 2 and good["comparable_count"] == 2 and good["agreement_count"] == 1
assert good["confusion_coverage"] == "SUPPRESSED_SMALL_COHORT" and good["confusion_counts"] is None
missing = report(replay(["case-1", "case-2"], [case("case-1")]), expected_rc=3)
assert missing["missing_count"] == 1 and missing["received_count"] == 1
unknown = report(replay(["case-1"], [case("case-1", independent=False)]), expected_rc=3)
assert unknown["unlabelled_count"] == 1 and unknown["comparable_count"] == 0
unsafe = report(replay(["case-1"], [case("case-1", planner="MERGE", verdict="PASS")]), expected_rc=3)
assert unsafe["unsafe_recommendation_count"] == 1 and unsafe["rollout_status"] == "NOT_EVALUATED"
false_pass_action = report(replay(["case-1"], [case("case-1", planner="PASS")]), expected_rc=3)
assert false_pass_action["unsafe_recommendation_count"] == 1
assert false_pass_action["confusion_counts"] is None
five = report(replay([f"case-{n}" for n in range(1, 6)], [case(f"case-{n}") for n in range(1, 6)]), expected_rc=0)
assert five["confusion_coverage"] == "DISPLAYED" and five["confusion_counts"]["HUMAN_TRIAGE"]["HUMAN_TRIAGE"] == 5


def rejects(raw):
    result = subprocess.run([sys.executable, "-I", "-B", str(CLI)], input=raw, capture_output=True, check=False, timeout=5)
    assert result.returncode == 3 and b"UNVERIFIED" in result.stderr and not result.stdout, result


rejects(b"")
rejects(b"x" * 65537)
rejects(b'{"schema_version":1,"schema_version":1}')
rejects(json.dumps({"schema_version": True, "expected_case_ids": ["case-1"], "cases": [case("case-1")]}).encode())
rejects(json.dumps({"schema_version": 1, "expected_case_ids": ["case-1", "case-1"], "cases": [case("case-1")]}).encode())
rejects(json.dumps({"schema_version": 1, "expected_case_ids": ["case-1"], "cases": [case("other")]}).encode())
rejects(json.dumps({"schema_version": 1, "expected_case_ids": ["case-1"], "cases": [case("case-1"), case("case-1")]}).encode())
rejects(json.dumps({"schema_version": 1, "expected_case_ids": ["case-1"], "cases": [dict(case("case-1"), raw_pr_body="untrusted")]}).encode())
print("evaluate-exception-replay tests: PASS")
