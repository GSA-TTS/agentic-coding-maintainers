"""Offline, synthetic acceptance tests for the private append-only case ledger."""

import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
WRITER = ROOT / "scripts/append-cohort-event.py"
OUTBOX = pathlib.Path(tempfile.gettempdir()).resolve() / "maintainer-evaluation-disposal"
if OUTBOX.parent.is_relative_to(ROOT):
    raise SystemExit("UNVERIFIED: temp root must be outside the repository")
if not OUTBOX.parent.is_dir() or (OUTBOX.parent.stat().st_mode & 0o002 and not OUTBOX.parent.stat().st_mode & 0o1000):
    raise SystemExit("UNVERIFIED: system temp parent is unsafe")
OUTBOX.mkdir(mode=0o700, exist_ok=True)
if OUTBOX.is_symlink() or OUTBOX.stat().st_uid != os.getuid() or OUTBOX.stat().st_mode & 0o077:
    raise SystemExit("UNVERIFIED: synthetic test outbox is not private")
FIXTURE = pathlib.Path(tempfile.mkdtemp(prefix=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d-append-cohort-test-"), dir=OUTBOX))
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
saved = json.loads(before)
assert saved == dict(intake, recorded_at=saved["recorded_at"])
assert datetime.datetime.fromisoformat(saved["recorded_at"].replace("Z", "+00:00")).tzinfo is not None


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
rejects(event(2, "transition", state="blocked"), path=FIXTURE / "not-initialized.jsonl")

# Explicit O_EXCL initialization is safe to repeat: existing bytes survive.
original = LEDGER.read_bytes()
try:
    os.open(LEDGER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
except FileExistsError:
    pass
else:
    raise AssertionError("exclusive initialization overwrote a ledger")
assert LEDGER.read_bytes() == original

# An exclusive lock held by another cooperating writer produces UNVERIFIED
# after a bounded wait; no append may sneak past it.
locker = subprocess.Popen([sys.executable, "-I", "-B", "-c",
                           "import fcntl,sys,time; f=open(sys.argv[1],'rb'); "
                           "fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); time.sleep(8)", str(LEDGER)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
assert locker.stdout and locker.stdout.readline().strip() == "locked"
locked = submit(event(2, "transition", state="blocked"))
assert locked.returncode == 3 and b"UNVERIFIED" in locked.stderr
assert LEDGER.read_bytes() == original
locker.terminate()
locker.wait(timeout=5)

second = submit(event(2, "transition", state="blocked"))
assert second.returncode == 0
assert len(LEDGER.read_bytes().splitlines()) == 2
assert b'"recorded_at"' in LEDGER.read_bytes()
assert hashlib.sha256(LEDGER.read_bytes()).digest() != hashlib.sha256(before).digest()

# Two cooperating CLI processes must serialize their validate/append steps.
with ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(submit, event(n, "transition", state="open")) for n in (3, 4)]
    results = [future.result() for future in futures]
assert all(result.returncode == 0 for result in results), results
assert sorted(json.loads(line)["event_id"] for line in LEDGER.read_bytes().splitlines()) == [
    "evt-1", "evt-2", "evt-3", "evt-4",
]

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
