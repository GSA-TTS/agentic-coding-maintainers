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
assert queue[0]["days_since_recording"] == 11
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
association = dict(row("complete", 42, "pr_association", intake_event_id="e1",
                       repository="acme/widgets", pr_number=7, head_sha=sha_a,
                       provenance="agent_recorded"),
                   occurred_at="2026-10-12T00:00:00Z", recorded_at="2026-10-12T01:00:00Z")
assert module.reflect(read([rows[0], association]), as_of, key)["verified_completion_ids"] == []
refuses([rows[0], dict(association, repository="invalid/repo/path")])
refuses([rows[0], dict(association, provenance="signed")])
refuses([rows[0], association, dict(association, event_id="e43")])
refuses([rows[0], dict(association, intake_event_id="missing")])
refuses([rows[0], dict(association, occurred_at="2026-10-10T00:00:00Z")])
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
assert {entry["case_label"] for entry in boundary_queue} == {module.pseudonym("at-due", key), module.pseudonym("pre-due", key)}
assert boundary_queue[0]["days_since_recording"] == 6 and boundary_queue[0]["review_due"] is False
assert boundary_queue[1]["days_since_recording"] == 6 and boundary_queue[1]["review_due"] is False
# Backdating occurred_at alone cannot accelerate the operational review cue.
backdated = dict(row("backdated", 43, "intake", case_type="review", eligibility="unknown"),
                 occurred_at="2026-08-01T00:00:00Z", recorded_at="2026-10-20T00:00:00Z")
assert module.reflect(read([backdated]), as_of, key)["needs_maintainer_disposition"][0]["review_due"] is False
# Exactly seven full days since writer-set recorded_at IS due.
at_recorded_boundary = dict(at_due, recorded_at="2026-10-15T00:00:00Z")
assert module.reflect(read([at_recorded_boundary]), as_of, key)["needs_maintainer_disposition"][0]["review_due"] is True
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
assert fixed_report["eligible_ids"] == []  # original intake cohort does not change
assert fixed_report["unknown_eligibility_ids"] == [module.pseudonym("new-unknown", key)]
assert fixed_report["needs_maintainer_disposition"] == []
assert fixed_report["intake_cohort_count"] == 1
assert fixed_report["original_eligibility_counts"] == {"eligible": 0, "excluded": 0, "unknown": 1}
assert fixed_report["effective_eligibility_labels"]["eligible"] == [module.pseudonym("new-unknown", key)]
assert fixed_report["eligibility_correction_count"] == 1
assert fixed_report["corrected_case_labels"] == [module.pseudonym("new-unknown", key)]
quality = fixed_report["correction_quality"]
assert quality["denominator_first_intakes"] == 1 and quality["corrected_case_count"] == 1
assert quality["original_unknown_count"] == 1 and quality["unknown_resolved_count"] == 1
assert quality["unknown_pending_case_labels"] == []
assert quality["corrected_case_labels_by_original_eligibility"]["unknown"] == [module.pseudonym("new-unknown", key)]
assert quality["unknown_recorded_disposition_delays"] == [
    {"case_label": module.pseudonym("new-unknown", key), "recorded_delay_hours": 24.0}]
# Distinguish claimed occurrence gap from writer-recorded gap. Both were 24h in
# the first fixture, so a regression to occurred_at would otherwise pass.
different_gap = dict(fresh_fix, occurred_at="2026-10-10T02:00:00Z", recorded_at="2026-10-11T03:00:00Z")
assert module.reflect(read([fresh_unknown, different_gap]), as_of, key)["correction_quality"]["unknown_recorded_disposition_delays"][0]["recorded_delay_hours"] == 26.0
prior_report = module.reflect(read([fresh_unknown, fresh_fix]), datetime(2026, 10, 10, 12, tzinfo=timezone.utc), key)
assert prior_report["correction_quality"]["corrected_case_count"] == 0
assert prior_report["correction_quality"]["unknown_pending_case_labels"] == [module.pseudonym("new-unknown", key)]
# A correction appended after an older snapshot does not revise its status.
assert module.reflect(read([fresh_unknown, fresh_fix]), datetime(2026, 10, 10, 12, tzinfo=timezone.utc), key)["needs_maintainer_disposition"][0]["case_label"] == module.pseudonym("new-unknown", key)
assert module.reflect(read([fresh_unknown, fresh_fix]), datetime(2026, 10, 10, 12, tzinfo=timezone.utc), key)["unknown_eligibility_ids"] == [module.pseudonym("new-unknown", key)]
refuses([fresh_unknown, dict(fresh_fix, intake_event_id="missing")])
refuses([fresh_unknown, dict(fresh_fix, replacement="unknown")])
refuses([fresh_unknown, dict(fresh_fix, reason_code="free text")])
refuses([fresh_unknown, fresh_fix, dict(fresh_fix, event_id="e42", replacement="excluded")])
# A recorded correction must not claim to have been made before the intake was
# actually recorded, even if the intake's backdated occurred_at came first.
refuses([fresh_unknown, dict(fresh_fix, occurred_at="2026-10-10T00:30:00Z")])
# All-retained disposition ages are separate from every pre-existing cohort
# field. Older eligible/excluded corrections remain visible alongside pending
# older unknowns, without retroactive delivery credit or denominator changes.
age_field = "all_retained_intake_disposition_ages"
older_excluded = dict(older, case_id="older-excluded", event_id="e50")
older_pending = dict(older, case_id="older-pending", event_id="e51")
excluded_fix = dict(corrected, case_id="older-excluded", event_id="e52",
                    intake_event_id="e50", replacement="excluded",
                    occurred_at="2026-08-02T00:00:00Z")
retained_rows = [older, older_excluded, older_pending] + rows + [corrected, excluded_fix]
retained_events = read(retained_rows)
before_reflection = json.dumps(retained_events, sort_keys=True)
retained_report = module.reflect(retained_events, as_of, key)
assert json.dumps(retained_events, sort_keys=True) == before_reflection
assert module.reflect(retained_events, as_of, key) == retained_report
ages = retained_report[age_field]
assert ages["coverage"] == "recorded_events_only"
assert ages["retained_intake_count"] == 10
assert "separate from the 28-day intake cohort" in ages["scope"]
assert "not verified source-to-decision time" in ages["time_basis"]
assert ages["corrected_cases"] == sorted([
    {"case_label": module.pseudonym("older-unknown", key),
     "original_eligibility": "unknown", "effective_eligibility": "eligible",
     "recorded_delay_hours": 1872.0},
    {"case_label": module.pseudonym("older-excluded", key),
     "original_eligibility": "unknown", "effective_eligibility": "excluded",
     "recorded_delay_hours": 1872.0},
], key=lambda entry: entry["case_label"])
assert ages["pending_unknown_cases"] == sorted([
    {"case_label": module.pseudonym("older-pending", key),
     "original_eligibility": "unknown", "effective_eligibility": "unknown",
     "recorded_age_hours": 1967.0},
    {"case_label": module.pseudonym("unknown", key),
     "original_eligibility": "unknown", "effective_eligibility": "unknown",
     "recorded_age_hours": 264.0},
], key=lambda entry: entry["case_label"])
changed_projection_fields = {age_field, "needs_maintainer_disposition", "out_of_window_recorded_case_count"}
assert {name: value for name, value in retained_report.items() if name not in changed_projection_fields} == {
    name: value for name, value in report.items() if name not in changed_projection_fields}
assert retained_report["out_of_window_recorded_case_count"] == 3
assert {entry["case_label"] for entry in retained_report["needs_maintainer_disposition"]} == {
    entry["case_label"] for entry in ages["pending_unknown_cases"]}
for case in ("older-unknown", "older-excluded", "older-pending"):
    assert json.dumps(case) not in json.dumps(ages)
assert all(set(entry) == {"case_label", "original_eligibility", "effective_eligibility", "recorded_delay_hours"}
           for entry in ages["corrected_cases"])
assert all(set(entry) == {"case_label", "original_eligibility", "effective_eligibility", "recorded_age_hours"}
           for entry in ages["pending_unknown_cases"])
# A correction also older than the cohort window is retained, not just a recent
# decision about an old intake.
older_fix = dict(corrected, occurred_at="2026-08-02T00:00:00Z", recorded_at="2026-08-03T01:00:00Z")
assert module.reflect(read([older, older_fix]), as_of, key)[age_field]["corrected_cases"][0]["recorded_delay_hours"] == 48.0
# Claimed occurrence can precede the cutoff while writer recording follows it.
# Neither such a correction nor a later-recorded intake changes the old report.
post_cutoff_fix = dict(corrected, case_id="older-pending", event_id="e53",
                       intake_event_id="e51", occurred_at="2026-08-02T00:00:00Z",
                       recorded_at="2026-10-23T00:00:00Z")
post_cutoff_intake = dict(older, case_id="later-intake", event_id="e54",
                          recorded_at="2026-10-23T00:00:00Z")
assert module.reflect(read(retained_rows + [post_cutoff_fix, post_cutoff_intake]), as_of, key) == retained_report
# At the exact recording cutoff the decision appears; it cannot use backdated
# occurrence to shorten its delay. Pending age uses that same fixed cutoff.
at_cutoff_fix = dict(post_cutoff_fix, recorded_at="2026-10-22T00:00:00Z")
at_cutoff_ages = module.reflect(read(retained_rows + [at_cutoff_fix]), as_of, key)[age_field]
assert next(entry for entry in at_cutoff_ages["corrected_cases"]
            if entry["case_label"] == module.pseudonym("older-pending", key))["recorded_delay_hours"] == 1967.0
assert len(at_cutoff_ages["pending_unknown_cases"]) == 1
# A backdated intake recorded recently must not acquire a historical pending age.
assert module.reflect(read([backdated]), as_of, key)[age_field]["pending_unknown_cases"][0]["recorded_age_hours"] == 48.0
assert module.reflect(read([fresh_unknown, different_gap]), as_of, key)[age_field]["corrected_cases"][0]["recorded_delay_hours"] == 26.0
# Corrections from non-unknown classifications are included, and correcting TO
# unknown leaves a pending case whose age does not restart at correction time.
to_unknown = dict(fresh_fix, replacement="unknown")
reclassified = module.reflect(read([dict(fresh_unknown, eligibility="eligible"), to_unknown]), as_of, key)[age_field]
assert reclassified["corrected_cases"][0]["recorded_delay_hours"] == 24.0
assert reclassified["corrected_cases"][0]["original_eligibility"] == "eligible"
assert reclassified["pending_unknown_cases"][0]["effective_eligibility"] == "unknown"
assert reclassified["pending_unknown_cases"][0]["recorded_age_hours"] == 287.0
empty_snapshot = module.reflect(read([post_cutoff_intake]), as_of, key)
assert empty_snapshot[age_field]["coverage"] == "no_evidence"
assert empty_snapshot[age_field]["retained_intake_count"] == 0
assert empty_snapshot[age_field]["corrected_cases"] == empty_snapshot[age_field]["pending_unknown_cases"] == []
assert empty_snapshot["correction_quality"]["coverage"] == "no_evidence"
assert empty_snapshot["correction_quality"]["denominator_first_intakes"] == 0
assert empty_snapshot["verified_completion_ids"] == []
assert only_excluded[age_field]["coverage"] == "recorded_events_only"
assert only_excluded[age_field]["corrected_cases"] == only_excluded[age_field]["pending_unknown_cases"] == []
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
assert ledger.read_bytes() == "".join(json.dumps(r) + "\n" for r in rows[:13]).encode()
assert json.loads(cli(rows[:13]).stdout) == output  # fixed bytes/key/cutoff reproduce the report
later_output = cli(rows[:13] + [after])
assert later_output.returncode == 0 and not later_output.stderr
later_report = json.loads(later_output.stdout)
assert later_report["ledger_identity_hmac"] != output["ledger_identity_hmac"]
assert {name: value for name, value in later_report.items() if name != "ledger_identity_hmac"} == {
    name: value for name, value in output.items() if name != "ledger_identity_hmac"}
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
