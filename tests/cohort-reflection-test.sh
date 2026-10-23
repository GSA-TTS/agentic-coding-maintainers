#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 -I -B - "$ROOT/scripts/cohort-reflection.py" <<'PY'
import importlib.util
import hashlib
import hmac
import json
import sys
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location("reflection", sys.argv[1])
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
as_of = datetime(2026, 10, 22, tzinfo=timezone.utc)
key = b"synthetic-test-key-32-bytes-long!!"
sha_a = "a" * 40
sha_b = "b" * 40


def row(case, number, kind, **fields):
    return dict(schema_version=1, event_id=f"e{number}", case_id=case,
                event_type=kind, occurred_at="2026-10-10T00:00:00Z",
                recorded_at="2026-10-11T00:00:00Z", **fields)


def read(rows):
    return module.events_from("".join(json.dumps(r) + "\n" for r in rows).encode(), as_of)


rows = [
    row("complete", 1, "intake", case_type="implementation", eligibility="eligible"),
    row("complete", 2, "review", head_sha=sha_a, independent="yes"),
    row("complete", 3, "handoff", head_sha=sha_a, review_event_id="e2", checks="passing"),
    row("complete", 4, "outcome", head_sha=sha_a, handoff_event_id="e3", repository_event_id="merge1"),
    row("open", 5, "intake", case_type="review", eligibility="eligible"),
    row("blocked", 6, "intake", case_type="review", eligibility="eligible"),
    row("blocked", 7, "transition", state="blocked"),
    row("cancelled", 8, "intake", case_type="security", eligibility="eligible"),
    row("cancelled", 9, "transition", state="cancelled"),
    row("rework", 10, "intake", case_type="implementation", eligibility="eligible"),
    row("rework", 11, "review", head_sha=sha_a, independent="yes"),
    row("rework", 12, "rework", review_event_id="e11", changed_sha=sha_b, substantive="yes"),
    row("rework", 13, "rework", review_event_id="e11", changed_sha=sha_b, substantive="yes"),
    row("excluded", 14, "intake", case_type="other", eligibility="excluded"),
    row("unknown", 15, "intake", case_type="other", eligibility="unknown"),
]
report = module.reflect(read(rows), as_of, key)
assert len(report["eligible_ids"]) == 5
assert len(report["unfinished_for_verified_throughput"]) == 5  # even claimed outcomes remain unverified
assert report["documented_outcome_ids_unverified"] == [module.pseudonym("complete", key)]
assert report["verified_completion_ids"] == []
assert report["post_review_substantive_rework_ids"] == [module.pseudonym("rework", key)]  # cycles don't inflate cases
assert report["excluded_ids"] == [module.pseudonym("excluded", key)]
assert report["unknown_eligibility_ids"] == [module.pseudonym("unknown", key)]
queue = report["needs_maintainer_disposition"]
assert len(queue) == 1 and queue[0]["case_label"] == module.pseudonym("unknown", key)
assert queue[0]["case_type"] == "other" and queue[0]["review_due"] is True
assert queue[0]["age_whole_days"] == 12
assert "unknown" not in [row["case_label"] for row in queue]
assert "no automatic exclusion" in report["disposition_policy"]
assert '"complete"' not in json.dumps(report)
assert "UNMEASURED" in report["intake_completeness"]


def refuses(malformed):
    try:
        read(malformed)
    except module.Unverified:
        return
    raise AssertionError("invalid ledger was accepted")


refuses(rows + [dict(rows[0])])  # duplicate event id
refuses([row("orphan", 1, "review", head_sha=sha_a, independent="yes")])
refuses([rows[0], row("complete", 16, "intake", case_type="review", eligibility="eligible")])
refuses([rows[0], row("complete", 17, "review", head_sha="invalid", independent="yes")])
refuses([rows[0], row("complete", 18, "handoff", head_sha=sha_b, review_event_id="e2", checks="passing")])
refuses([rows[0], row("complete", 19, "outcome", head_sha=sha_b, handoff_event_id="e3", repository_event_id="merge2")])
refuses([rows[0], row("complete", 20, "transition", state="not-a-state")])
refuses([rows[0], dict(row("complete", 21, "review", head_sha=sha_a, independent="yes"), secret="not-allowed")])
refuses([dict(rows[0], schema_version=True)])
refuses([rows[0], dict(row("complete", 30, "transition", state="blocked"), occurred_at="2026-10-12T00:00:00Z", recorded_at="2026-10-11T00:00:00Z")])
refuses([rows[0], dict(row("complete", 31, "transition", state="blocked"), recorded_at="2026-10-10T00:00:00Z")])
refuses([rows[0], rows[1], dict(row("complete", 32, "handoff", head_sha=sha_a, review_event_id="e2", checks="passing"),
                            occurred_at="2026-10-09T00:00:00Z")])
refuses([rows[0], rows[1], row("complete", 22, "handoff", head_sha=sha_b, review_event_id="e2", checks="passing")])
refuses([rows[0], rows[1], rows[2], row("complete", 23, "outcome", head_sha=sha_b, handoff_event_id="e3", repository_event_id="merge3")])
refuses([rows[0], rows[1], row("complete", 24, "outcome", head_sha=sha_a, handoff_event_id="e2", repository_event_id="merge4")])
refuses([rows[0], rows[1], row("othercase", 25, "intake", case_type="review", eligibility="eligible"),
         row("othercase", 26, "handoff", head_sha=sha_a, review_event_id="e2", checks="passing")])
# A late-recorded earlier transition cannot overwrite a later-occurring state.
late = [rows[0], dict(row("complete", 27, "transition", state="blocked"), occurred_at="2026-10-15T00:00:00Z"),
        dict(row("complete", 28, "transition", state="open"), occurred_at="2026-10-12T00:00:00Z",
             recorded_at="2026-10-16T00:00:00Z")]
late[1]["recorded_at"] = "2026-10-15T00:00:00Z"
assert module.reflect(read(late), as_of, key)["unfinished_for_verified_throughput"][0]["state"] == "blocked"
# Equal occurrence time uses append order as the documented tie-breaker.
tied = [rows[0], row("complete", 33, "transition", state="blocked"), row("complete", 34, "transition", state="open")]
assert module.reflect(read(tied), as_of, key)["unfinished_for_verified_throughput"][0]["state"] == "open"
# Reproducing an earlier cutoff must not be invalidated by a later append.
after = dict(row("complete", 29, "transition", state="cancelled"),
             occurred_at="2026-10-24T00:00:00Z", recorded_at="2026-10-25T00:00:00Z")
assert module.reflect(read(rows + [after]), as_of, key) == report
only_excluded = module.reflect(read([rows[13]]), as_of, key)
assert only_excluded["coverage"] == "no_eligible_evidence"
assert only_excluded["needs_maintainer_disposition"] == []
# A recent unknown is visible but not yet overdue. It never becomes excluded.
recent = dict(row("recent-unknown", 35, "intake", case_type="review", eligibility="unknown"),
              occurred_at="2026-10-20T00:00:00Z", recorded_at="2026-10-20T01:00:00Z")
recent_report = module.reflect(read([recent]), as_of, key)
assert recent_report["needs_maintainer_disposition"][0]["review_due"] is False
assert recent_report["excluded_ids"] == []
older = dict(row("older-unknown", 36, "intake", case_type="review", eligibility="unknown"),
             occurred_at="2026-08-01T00:00:00Z", recorded_at="2026-08-01T01:00:00Z")
older_report = module.reflect(read([older]), as_of, key)
assert older_report["coverage"] == "no_eligible_evidence" and older_report["unknown_eligibility_ids"] == []
assert older_report["needs_maintainer_disposition"][0]["case_label"] == module.pseudonym("older-unknown", key)
assert older_report["needs_maintainer_disposition"][0]["review_due"] is True
# Just below 7 days must not display seven whole days or report due; at exactly
# 7 days both values move together. The queue sorts by unrounded duration.
pre_due = dict(row("pre-due", 37, "intake", case_type="review", eligibility="unknown"),
               occurred_at="2026-10-15T00:00:01Z", recorded_at="2026-10-15T01:00:00Z")
at_due = dict(row("at-due", 38, "intake", case_type="review", eligibility="unknown"),
              occurred_at="2026-10-15T00:00:00Z", recorded_at="2026-10-15T01:00:00Z")
boundary_queue = module.reflect(read([pre_due, at_due]), as_of, key)["needs_maintainer_disposition"]
assert boundary_queue[0]["case_label"] == module.pseudonym("at-due", key)
assert boundary_queue[0]["age_whole_days"] == 7 and boundary_queue[0]["review_due"] is True
assert boundary_queue[1]["age_whole_days"] == 6 and boundary_queue[1]["review_due"] is False
# A maintainer decision is a new event, never a rewrite of intake. It removes
# the old unknown from the operational queue, even outside the 28-day cohort.
corrected = dict(row("older-unknown", 39, "eligibility_correction",
                     intake_event_id="e36", replacement="eligible", reason_code="eligibility_review"),
                 occurred_at="2026-10-18T00:00:00Z", recorded_at="2026-10-18T01:00:00Z")
with_correction = module.reflect(read([older, corrected]), as_of, key)
assert with_correction["needs_maintainer_disposition"] == []
assert older["eligibility"] == "unknown"
assert with_correction["coverage"] == "no_eligible_evidence"  # no retroactive addition to the cohort
assert with_correction["eligibility_correction_count"] == 0  # count is scoped to the intake cohort
fresh_unknown = dict(row("new-unknown", 40, "intake", case_type="review", eligibility="unknown"),
                     occurred_at="2026-10-10T00:00:00Z", recorded_at="2026-10-10T01:00:00Z")
fresh_fix = dict(row("new-unknown", 41, "eligibility_correction",
                     intake_event_id="e40", replacement="eligible", reason_code="eligibility_review"),
                 occurred_at="2026-10-11T00:00:00Z", recorded_at="2026-10-11T01:00:00Z")
fixed_report = module.reflect(read([fresh_unknown, fresh_fix]), as_of, key)
assert fixed_report["eligible_ids"] == [module.pseudonym("new-unknown", key)]
assert fixed_report["unknown_eligibility_ids"] == [] and fixed_report["needs_maintainer_disposition"] == []
assert fixed_report["eligibility_correction_count"] == 1
assert fixed_report["corrected_case_labels"] == [module.pseudonym("new-unknown", key)]
assert module.reflect(read([fresh_unknown, fresh_fix]), datetime(2026, 10, 10, 12, tzinfo=timezone.utc), key)["unknown_eligibility_ids"] == [module.pseudonym("new-unknown", key)]
refuses([fresh_unknown, dict(fresh_fix, intake_event_id="missing")])
refuses([fresh_unknown, dict(fresh_fix, replacement="unknown")])
refuses([fresh_unknown, dict(fresh_fix, reason_code="free text")])
refuses([fresh_unknown, fresh_fix, dict(fresh_fix, event_id="e42", replacement="excluded")])
# A recorded correction must not claim to have been made before the intake was
# actually recorded, even if the intake's backdated occurred_at came first.
refuses([fresh_unknown, dict(fresh_fix, occurred_at="2026-10-10T00:30:00Z")])
try:
    module.events_from(b'{"truncated":true}', as_of)
except module.Unverified:
    pass
else:
    raise AssertionError("incomplete line accepted")
# Exercise the operator CLI, including the private-file boundary and exit 3.
import os
import pathlib
import subprocess
import tempfile

fixture = pathlib.Path(tempfile.mkdtemp(prefix="cohort-cli-"))
os.chmod(fixture, 0o700)
manifest = fixture / "MANIFEST.md"
manifest.write_text(
    "# Cohort reflection CLI fixture\n\n"
    "Created by tests/cohort-reflection-test.sh under the system temporary directory. "
    "It contains only synthetic case events, a synthetic test key, symlink and oversized input. "
    "No real case, credential or task evidence. This private directory can be deleted by the operator. "
    "An interrupted test may contain only some of these items.\n",
    encoding="utf-8",
)
ledger = fixture / "cases.jsonl"
key_file = fixture / "report.key"
key_file.write_bytes(key)
os.chmod(key_file, 0o600)
inventory_file = fixture / "inventory.json"


def cli(input_rows, *, ledger_path=ledger):
    ledger.write_bytes("".join(json.dumps(r) + "\n" for r in input_rows).encode())
    os.chmod(ledger, 0o600)
    inventory_file.write_text(json.dumps({
        "schema_version": 1,
        "as_of": "2026-10-22T00:00:00Z",
        "window_start": "2026-09-24T00:00:00Z",
        "sources": [{
            "source_id": "synthetic-feed",
            "enumerated_at": "2026-10-22T00:00:00Z",
            "coverage": "complete",
            "requests": [{"request_id": row["case_id"], "received_at": row["occurred_at"],
                          "eligibility": row["eligibility"]}
                         for row in input_rows if row["event_type"] == "intake"],
        }],
    }), encoding="utf-8")
    os.chmod(inventory_file, 0o600)
    return subprocess.run([sys.executable, "-I", "-B", sys.argv[1], "--ledger", str(ledger_path),
                           "--key-file", str(key_file), "--inventory", str(inventory_file),
                           "--required-source", "synthetic-feed", "--as-of", "2026-10-22T00:00:00Z"],
                          capture_output=True, text=True, check=False)


good = cli(rows[:13])  # eligible cohort only; unknown eligibility is tested separately
assert good.returncode == 0 and not good.stderr, (good.returncode, good.stderr)
output = json.loads(good.stdout)
assert output["coverage"] == "recorded_eligible_cohort"
assert output["ledger_identity_hmac"] == hmac.new(key, b"ledger-identity-v1\0" + ledger.read_bytes(), hashlib.sha256).hexdigest()
assert all(raw not in output["eligible_ids"] + output["excluded_ids"] + output["unknown_eligibility_ids"]
           for raw in ("complete", "open", "blocked", "cancelled", "rework", "excluded", "unknown"))
no_eligible = cli([rows[13], rows[14]])
assert no_eligible.returncode == 3 and json.loads(no_eligible.stdout)["coverage"] == "no_eligible_evidence"
assert json.loads(no_eligible.stdout)["ledger_identity_hmac"] != output["ledger_identity_hmac"]
ledger.write_bytes(b"")
assert subprocess.run([sys.executable, "-I", "-B", sys.argv[1], "--ledger", str(ledger),
                       "--key-file", str(key_file), "--as-of", "2026-10-22T00:00:00Z"],
                      capture_output=True, text=True, check=False).returncode == 3
cli(rows)
os.chmod(ledger, 0o644)
unsafe = subprocess.run([sys.executable, "-I", "-B", sys.argv[1], "--ledger", str(ledger),
                         "--key-file", str(key_file), "--as-of", "2026-10-22T00:00:00Z"],
                        capture_output=True, text=True, check=False)
assert unsafe.returncode == 3 and "UNVERIFIED" in unsafe.stderr and not unsafe.stdout
os.chmod(ledger, 0o600)
link = fixture / "linked.jsonl"
link.symlink_to(ledger)
assert cli(rows, ledger_path=link).returncode == 3
huge = fixture / "huge.jsonl"
huge.write_bytes(b"x" * (module.MAX_BYTES + 1))
os.chmod(huge, 0o600)
assert cli(rows, ledger_path=huge).returncode == 3
invalid_json = fixture / "invalid.jsonl"
invalid_json.write_text('{"not-json":}\n', encoding="utf-8")
os.chmod(invalid_json, 0o600)
assert cli(rows, ledger_path=invalid_json).returncode == 3
invalid_schema = fixture / "invalid-schema.jsonl"
invalid_schema.write_text(json.dumps(dict(rows[0], schema_version=2)) + "\n", encoding="utf-8")
os.chmod(invalid_schema, 0o600)
assert cli(rows, ledger_path=invalid_schema).returncode == 3
ancestor = fixture / "ancestor"
ancestor.symlink_to(fixture)
assert cli(rows, ledger_path=ancestor / "cases.jsonl").returncode == 3
early = subprocess.run([sys.executable, "-I", "-B", sys.argv[1], "--ledger", str(ledger),
                        "--key-file", str(key_file), "--as-of", "0001-01-01T00:00:00Z"],
                       capture_output=True, text=True, check=False)
assert early.returncode == 3 and "UNVERIFIED" in early.stderr and "Traceback" not in early.stderr
print("cohort_cli_fixture=" + str(fixture), file=sys.stderr)
print("cohort-reflection tests: PASS")
PY
