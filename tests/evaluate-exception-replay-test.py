"""Offline adversarial replay fixtures; no GitHub or model calls."""

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts/evaluate-exception-replay.py"
FIXTURE = pathlib.Path(tempfile.mkdtemp(prefix="exception-replay-manifest-"))
FIXTURE.chmod(0o700)
(FIXTURE / "MANIFEST.md").write_text("Synthetic private replay cohort and label manifest. No real cases or secrets; safe for operator disposal.\n", encoding="utf-8")
MANIFEST = FIXTURE / "cohort.json"


def case(cid: str, *, human: str | None = "HUMAN_TRIAGE", planner: str | None = "HUMAN_TRIAGE",
         verdict: str | None = "UNVERIFIED", independent: bool = True):
    return {"case_id": cid, "maintainer_action": human, "planner_action": planner,
            "planner_verdict": verdict, "independent_label": independent}


def replay(expected, cases, *, labels=None):
    # Independent fixture construction: planner results must not be able to
    # choose the maintainer label or its independence flag. Callers override
    # labels explicitly where the expected judgment differs from HUMAN_TRIAGE.
    labels = labels or {}
    MANIFEST.write_text(json.dumps({"schema_version": 1, "frozen_at": "2020-01-01T00:00:00Z",
                                    "cases": [{"case_id": cid,
                                               "maintainer_action": labels.get(cid, ("HUMAN_TRIAGE", True))[0],
                                               "independent_label": labels.get(cid, ("HUMAN_TRIAGE", True))[1]}
                                              for cid in expected]}), encoding="utf-8")
    MANIFEST.chmod(0o600)
    return subprocess.run([sys.executable, "-I", "-B", str(CLI), "--manifest", str(MANIFEST)],
                          input=json.dumps({"schema_version": 1,
                                            "cases": [{"case_id": row["case_id"],
                                                       "planner_action": row["planner_action"],
                                                       "planner_verdict": row["planner_verdict"]} for row in cases]}).encode(),
                          capture_output=True, check=False, timeout=5)


def report(result, *, expected_rc):
    assert result.returncode == expected_rc and not result.stderr, result.stderr
    value = json.loads(result.stdout)
    assert value["rollout_status"] == "NOT_EVALUATED" and value["execution_performed"] is False
    assert "caller-supplied current inputs" in value["limitation"]
    assert "case-1" not in result.stdout.decode()  # no raw case IDs
    return value


good = report(replay(["case-1", "case-2"], [case("case-1"), case("case-2", planner="REVIEW_INDEPENDENT_WORK")],
                     labels={"case-2": ("DEFER_CI_MEASUREMENT", True)}), expected_rc=0)
assert good["expected_count"] == 2 and good["comparable_count"] == 2 and good["agreement_count"] == 1
assert good["verdict_measured_count"] == 2 and good["missing_verdict_count"] == 0
assert good["confusion_coverage"] == "SUPPRESSED_UNVERIFIED_PRIVACY" and good["confusion_counts"] is None
missing = report(replay(["case-1", "case-2"], [case("case-1")]), expected_rc=3)
assert missing["missing_count"] == 1 and missing["received_count"] == 1
unknown = report(replay(["case-1"], [case("case-1")], labels={"case-1": ("HUMAN_TRIAGE", False)}), expected_rc=3)
assert unknown["unlabelled_count"] == 1 and unknown["comparable_count"] == 0
unsafe = report(replay(["case-1"], [case("case-1", planner="MERGE", verdict="PASS")]), expected_rc=3)
assert unsafe["unsafe_recommendation_count"] == 1 and unsafe["rollout_status"] == "NOT_EVALUATED"
verdict_only = report(replay(["case-1"], [case("case-1", verdict="PASS")]), expected_rc=3)
assert verdict_only["unsafe_recommendation_count"] == 1
false_pass_action = report(replay(["case-1"], [case("case-1", planner="PASS")]), expected_rc=3)
assert false_pass_action["unsafe_recommendation_count"] == 1
assert false_pass_action["confusion_counts"] is None
missing_verdict = report(replay(["case-1"], [case("case-1", verdict=None)]), expected_rc=3)
assert missing_verdict["missing_verdict_count"] == 1 and missing_verdict["verdict_measured_count"] == 0
missing_action = report(replay(["case-1"], [case("case-1", planner=None)]), expected_rc=3)
assert missing_action["comparable_count"] == 0
missing_label = report(replay(["case-1"], [case("case-1")], labels={"case-1": (None, True)}), expected_rc=3)
assert missing_label["caller_asserted_independent_label_count"] == 0 and missing_label["unlabelled_count"] == 1
four = report(replay([f"case-{n}" for n in range(1, 5)], [case(f"case-{n}") for n in range(1, 5)]), expected_rc=0)
assert four["confusion_coverage"] == "SUPPRESSED_UNVERIFIED_PRIVACY" and four["confusion_counts"] is None
five = report(replay([f"case-{n}" for n in range(1, 6)], [case(f"case-{n}") for n in range(1, 6)]), expected_rc=0)
assert five["confusion_coverage"] == "SUPPRESSED_UNVERIFIED_PRIVACY" and five["confusion_counts"] is None


def rejects(raw):
    result = subprocess.run([sys.executable, "-I", "-B", str(CLI), "--manifest", str(MANIFEST)],
                            input=raw, capture_output=True, check=False, timeout=5)
    assert result.returncode == 3 and b"UNVERIFIED" in result.stderr and not result.stdout, result


rejects(b"")
rejects(b"x" * 65537)
rejects(b'{"schema_version":1,"schema_version":1}')
replay(["case-1"], [case("case-1")])  # set a one-case manifest for rejection tests
rejects(json.dumps({"schema_version": True, "cases": []}).encode())
rejects(json.dumps({"schema_version": 1, "cases": [{"case_id": "other", "planner_action": "HUMAN_TRIAGE", "planner_verdict": "UNVERIFIED"}]}).encode())
rejects(json.dumps({"schema_version": 1, "cases": [{"case_id": "case-1", "planner_action": "HUMAN_TRIAGE", "planner_verdict": "UNVERIFIED"}] * 2}).encode())
rejects(json.dumps({"schema_version": 1, "cases": [{"case_id": "case-1", "planner_action": "HUMAN_TRIAGE", "planner_verdict": "UNVERIFIED", "raw_pr_body": "untrusted"}]}).encode())
rejects(json.dumps({"schema_version": 1, "cases": [{"case_id": "case-1", "planner_action": "HUMAN_TRIAGE", "planner_verdict": "UNVERIFIED", "maintainer_action": "MERGE"}]}).encode())
rejects(json.dumps({"schema_version": 1, "cases": [{"case_id": "case-1", "planner_action": "HUMAN_TRIAGE", "planner_verdict": "UNVERIFIED", "independent_label": True}]}).encode())
# A stale or symlinked manifest must not silently become a complete cohort.
MANIFEST.write_text(json.dumps({"schema_version": 1, "frozen_at": "9999-12-31T00:00:00Z", "cases": [{"case_id": "case-1", "maintainer_action": "HUMAN_TRIAGE", "independent_label": True}]}), encoding="utf-8")
rejects(json.dumps({"schema_version": 1, "cases": []}).encode())
replay(["case-1"], [case("case-1")])
LINK = FIXTURE / "cohort-link.json"
LINK.symlink_to(MANIFEST)
linked = subprocess.run([sys.executable, "-I", "-B", str(CLI), "--manifest", str(LINK)],
                        input=json.dumps({"schema_version": 1, "cases": []}).encode(), capture_output=True, check=False, timeout=5)
assert linked.returncode == 3 and b"UNVERIFIED" in linked.stderr and not linked.stdout
print("exception_replay_fixture=" + str(FIXTURE), file=sys.stderr)
print("evaluate-exception-replay tests: PASS")
