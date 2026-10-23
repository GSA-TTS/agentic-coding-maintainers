"""Synthetic, offline tests for conditional source-attested intake coverage."""

import datetime
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
READER = ROOT / "scripts/cohort-reflection.py"
spec = importlib.util.spec_from_file_location("cohort_inventory", READER)
assert spec and spec.loader
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
as_of = datetime.datetime(2026, 10, 23, tzinfo=datetime.timezone.utc)
key = b"synthetic-inventory-test-key-more-than-32-bytes"
events = [dict(schema_version=1, event_id="intake-1", case_id="case-one", event_type="intake",
               occurred_at="2026-10-05T00:00:00Z", recorded_at="2026-10-05T01:00:00Z",
               case_type="review", eligibility="eligible")]


def item(request_id, eligibility="eligible"):
    return {"request_id": request_id, "received_at": "2026-10-05T00:00:00Z", "eligibility": eligibility}


def source(name, coverage="complete", requests=None):
    return {"source_id": name, "enumerated_at": "2026-10-23T00:00:00Z",
            "coverage": coverage, "requests": requests if requests is not None else [item("case-one")]}


def inventory(sources):
    return {"schema_version": 1, "as_of": "2026-10-23T00:00:00Z",
            "window_start": "2026-09-25T00:00:00Z", "sources": sources}


def report(obj, required={"issue-feed"}):
    return reader.reconcile_inventory(json.dumps(obj).encode(), events, as_of, key, required)


complete = report(inventory([source("issue-feed", requests=[item("case-one")])]))
assert complete["status"] == "operator_asserted_source_coverage"
assert complete["eligible_enumerated_count"] == 1 and complete["eligible_recorded_count"] == 1
missing = report(inventory([source("issue-feed", requests=[item("case-one"), item("case-two")])]))
assert missing["status"] == "UNVERIFIED" and missing["eligible_recorded_count"] == 1
assert missing["missing_eligible_labels"] == [reader.pseudonym("case-two", key)]
assert "case-two" not in json.dumps(complete)
assert "all real-world" in complete["scope"]
assert report(inventory([source("issue-feed", "partial")]))["status"] == "UNVERIFIED"
assert report(inventory([source("issue-feed")]), {"issue-feed", "review-feed"})["status"] == "UNVERIFIED"
assert report(inventory([source("issue-feed", requests=[item("case-one"), item("unknown", "unknown")])]))["status"] == "UNVERIFIED"
assert report(inventory([source("issue-feed", requests=[item("excluded", "excluded")])]))["status"] == "UNVERIFIED"
assert report(inventory([source("issue-feed", requests=[item("case-one", "unknown")])]))["status"] == "UNVERIFIED"
late_request = inventory([source("issue-feed", requests=[item("case-one")])])
late_request["sources"][0]["requests"][0]["received_at"] = "2026-10-06T00:00:00Z"
assert report(late_request)["status"] == "UNVERIFIED"
assert report(late_request)["eligible_recorded_count"] == 0

# A ledger-only intake is a numerator/denominator discrepancy, not a bonus
# recorded request. Matching IDs with different eligibility cannot be counted.
assert report(inventory([source("issue-feed", requests=[item("case-two")])]))["status"] == "UNVERIFIED"
conflict = report(inventory([source("issue-feed", requests=[item("case-one", "excluded"), item("case-two")])]))
assert conflict["status"] == "UNVERIFIED" and conflict["eligible_recorded_count"] == 0


def refuses(obj, required={"issue-feed"}):
    try:
        report(obj, required)
    except reader.Unverified:
        return
    raise AssertionError("invalid request inventory was accepted")


refuses(inventory([source("issue-feed"), source("issue-feed")]))
refuses(inventory([source("issue-feed", requests=[item("case-one"), item("case-one")])]))
refuses(inventory([source("rogue-feed")]))
refuses(inventory([source("issue-feed", requests=[item("case-one", "yes")])]))
refuses(dict(inventory([source("issue-feed")]), as_of="2026-10-20T00:00:00Z"))
refuses(inventory([source("issue-feed")]), set())
refuses(dict(inventory([source("issue-feed")]), window_start="2026-09-24T00:00:00Z"))
refuses(inventory([source("issue-feed", requests=[item("case-one"), item("case-one")])]))

# Wrong-typed event enums must raise the reader's explicit degraded state,
# not leak a TypeError from Python set membership.
for bad in (dict(events[0], event_type=[]), dict(events[0], case_type=[]), dict(events[0], eligibility=[])):
    try:
        reader.events_from((json.dumps(bad) + "\n").encode(), as_of)
    except reader.Unverified:
        pass
    else:
        raise AssertionError("wrong-typed event enum was accepted")

# The operator CLI must also return 3 when a required feed is incomplete.
fixture = pathlib.Path(tempfile.mkdtemp(prefix="intake-inventory-"))
fixture.chmod(0o700)
(fixture / "MANIFEST.md").write_text("Synthetic intake inventory and key from tests/intake-inventory-test.py. "
                                     "No real user data. Safe for operator disposal.\n", encoding="utf-8")
ledger = fixture / "events.jsonl"
key_file = fixture / "report.key"
inventory_file = fixture / "inventory.json"
ledger.write_text(json.dumps(events[0]) + "\n", encoding="utf-8")
key_file.write_bytes(key)
inventory_file.write_text(json.dumps(inventory([source("issue-feed", "partial")])), encoding="utf-8")
for file in (ledger, key_file, inventory_file):
    file.chmod(0o600)
cmd = [sys.executable, "-I", "-B", str(READER), "--ledger", str(ledger), "--key-file", str(key_file),
       "--inventory", str(inventory_file), "--required-source", "issue-feed", "--as-of", "2026-10-23T00:00:00Z"]
partial = subprocess.run(cmd, capture_output=True, text=True, check=False)
assert partial.returncode == 3 and not partial.stderr
assert json.loads(partial.stdout)["intake_inventory"]["status"] == "UNVERIFIED"
inventory_file.write_text(json.dumps(inventory([source("issue-feed")])), encoding="utf-8")
covered = subprocess.run(cmd, capture_output=True, text=True, check=False)
assert covered.returncode == 0
assert json.loads(covered.stdout)["intake_inventory"]["status"] == "operator_asserted_source_coverage"
assert "CONDITIONAL" in json.loads(covered.stdout)["intake_completeness"]
inventory_file.write_text(json.dumps(inventory([source("issue-feed", requests=[item("case-one"), item("case-two")])])), encoding="utf-8")
missing_cli = subprocess.run(cmd, capture_output=True, text=True, check=False)
assert missing_cli.returncode == 3 and json.loads(missing_cli.stdout)["intake_inventory"]["status"] == "UNVERIFIED"
missing_inventory = subprocess.run([sys.executable, "-I", "-B", str(READER), "--ledger", str(ledger),
                                   "--key-file", str(key_file), "--as-of", "2026-10-23T00:00:00Z"],
                                  capture_output=True, text=True, check=False)
assert missing_inventory.returncode == 3 and "UNVERIFIED" in missing_inventory.stderr and not missing_inventory.stdout
print("intake-inventory tests: PASS")
print("intake_inventory_fixture=" + str(fixture), file=sys.stderr)
