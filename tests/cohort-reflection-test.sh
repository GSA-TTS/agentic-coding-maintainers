#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
python3 -I -B - "$ROOT/scripts/cohort-reflection.py" <<'PY'
import importlib.util
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
# Reproducing an earlier cutoff must not be invalidated by a later append.
after = dict(row("complete", 29, "transition", state="cancelled"),
             occurred_at="2026-10-24T00:00:00Z", recorded_at="2026-10-25T00:00:00Z")
assert module.reflect(read(rows + [after]), as_of, key) == report
only_excluded = module.reflect(read([rows[13]]), as_of, key)
assert only_excluded["coverage"] == "no_eligible_evidence"
try:
    module.events_from(b'{"truncated":true}', as_of)
except module.Unverified:
    pass
else:
    raise AssertionError("incomplete line accepted")
print("cohort-reflection tests: PASS")
PY
