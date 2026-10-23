"""Offline, synthetic acceptance tests for the private append-only case ledger."""

import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
WRITER = ROOT / "scripts/append-cohort-event.py"
OUTBOX = pathlib.Path(tempfile.gettempdir()) / "maintainer-evaluation-disposal"
OUTBOX.mkdir(mode=0o700, exist_ok=True)
if OUTBOX.is_symlink() or OUTBOX.stat().st_uid != os.getuid() or OUTBOX.stat().st_mode & 0o077:
    raise SystemExit("UNVERIFIED: synthetic test outbox is not private")
FIXTURE = pathlib.Path(tempfile.mkdtemp(prefix="append-cohort-test-", dir=OUTBOX))
(FIXTURE / "MANIFEST.md").write_text(
    "# Append-cohort test fixtures\n\n"
    "This directory was created by tests/append-cohort-event-test.py. It holds only synthetic "
    "JSONL task events, a symlink to a synthetic ledger and deliberately malformed inputs. "
    "Nothing here is real task evidence; safe for the operator to delete. "
    "An interrupted test may have created only some of these items.\n",
    encoding="utf-8",
)
LEDGER = FIXTURE / "cases.jsonl"
LEDGER.touch(mode=0o600)


def submit(event, *, path=LEDGER):
    data = json.dumps(event).encode() if not isinstance(event, bytes) else event
    return subprocess.run([sys.executable, "-I", "-B", str(WRITER), "--ledger", str(path)],
                          input=data, capture_output=True, check=False)


def event(number, kind, **payload):
    return dict(schema_version=1, event_id=f"evt-{number}", case_id="case-one",
                event_type=kind, occurred_at="2020-01-01T00:00:00Z", **payload)


intake = event(1, "intake", case_type="review", eligibility="eligible")
first = submit(intake)
assert first.returncode == 0 and b"not independently verified" in first.stdout
assert LEDGER.stat().st_mode & 0o777 == 0o600
before = LEDGER.read_bytes()
assert before.endswith(b"\n") and json.loads(before)["recorded_at"].endswith("Z")


def rejects(candidate, *, path=LEDGER):
    original = path.read_bytes() if path.is_file() else None
    result = submit(candidate, path=path)
    assert result.returncode == 3 and b"UNVERIFIED" in result.stderr and not result.stdout, result
    if original is not None:
        assert path.read_bytes() == original, "rejected event changed the ledger"


rejects(intake)  # duplicate ID/intake
rejects(event(2, "review", head_sha="bad-sha", independent="yes"))
rejects(event(2, "transition", state="blocked", secret="unallowed-field"))
rejects(event(2, "handoff", head_sha="a" * 40, review_event_id="absent", checks="passing"))
rejects(b'{"schema_version":1,"schema_version":1}')
rejects(event(2, "transition", state="blocked"), path=FIXTURE / "missing-parent" / "events.jsonl")

second = submit(event(2, "transition", state="blocked"))
assert second.returncode == 0
assert len(LEDGER.read_bytes().splitlines()) == 2
assert b'"recorded_at"' in LEDGER.read_bytes()

# Complete-but-invalid and incomplete ledgers fail closed without repair.
with LEDGER.open("ab") as handle:
    handle.write(b"{\"truncated\":")
incomplete = LEDGER.read_bytes()
rejects(event(3, "transition", state="open"))
assert LEDGER.read_bytes() == incomplete

# Neither the destination nor its parent may be followed through a symlink.
link = FIXTURE / "linked.jsonl"
link.symlink_to(LEDGER)
rejects(event(3, "transition", state="open"), path=link)
ancestor = FIXTURE / "ancestor"
ancestor.symlink_to(FIXTURE, target_is_directory=True)
rejects(event(3, "transition", state="open"), path=ancestor / "cases.jsonl")

print("append-cohort-event tests: PASS")
print(f"append_cohort_fixture={FIXTURE}", file=sys.stderr)
