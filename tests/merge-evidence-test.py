"""Offline counterexamples for a supplied PR snapshot, not GitHub attestation."""

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROBE = ROOT / "scripts/merge-evidence.py"
HEAD = "a" * 40
MERGE = "b" * 40


def run(snapshot, *, repository="acme/widgets", number=7, head=HEAD):
    raw = snapshot if isinstance(snapshot, bytes) else json.dumps(snapshot).encode()
    return subprocess.run([sys.executable, "-I", "-B", str(PROBE), "--repository", repository,
                           "--number", str(number), "--head", head], input=raw, capture_output=True, check=False)


def example(**changes):
    value = {"schema_version": 1, "repository": "acme/widgets", "number": 7,
             "state": "CLOSED", "head_sha": HEAD,
             "merged_at": "2020-01-01T12:00:00Z", "merge_commit_sha": MERGE}
    value.update(changes)
    return value


def expects(status, snapshot, **args):
    result = run(snapshot, **args)
    assert result.returncode == 0 and not result.stderr, (status, result.stderr)
    report = json.loads(result.stdout)
    assert report["classification"] == status
    assert report["provenance"].startswith("UNVERIFIED")
    assert report["policy_compliance"] == "UNMEASURED" and report["delivery_credit"] is False
    assert "acme/widgets" not in result.stdout.decode()


def refuses(snapshot, **args):
    result = run(snapshot, **args)
    assert result.returncode == 3 and b"UNVERIFIED" in result.stderr and not result.stdout, result


expects("MERGE_CLAIM_IN_SUPPLIED_SNAPSHOT", example())  # squash SHA != head
expects("NOT_MERGED_IN_SUPPLIED_SNAPSHOT", example(state="OPEN", merged_at=None, merge_commit_sha=None))
refuses(example(state="OPEN", merged_at=None, merge_commit_sha=MERGE))
expects("CLOSED_NOT_MERGED_IN_SUPPLIED_SNAPSHOT", example(merged_at=None, merge_commit_sha=None))
refuses(example(head_sha="c" * 40))
refuses(example(repository="other/widgets"))
refuses(example(number=8))
refuses(example(merged_at=None))  # closed with ambiguous merge_commit_sha
refuses(example(merge_commit_sha=None))
refuses(example(state="OPEN"))  # open with merge timestamp
refuses(example(state="OPEN", head_sha="c" * 40))  # contradictory fields win over mismatch
refuses(example(merged_at=None, head_sha="c" * 40))
refuses(example(merged_at="2026-99-99T99:99:99Z"))
refuses(example(merged_at="2026-02-30T12:00:00Z"))
refuses(example(merged_at="9999-12-31T12:00:00Z"))
refuses(example(schema_version=True))
refuses(example(extra="never echo this"))
refuses(example(head_sha="not-a-sha"))
refuses(example(), repository="bad/owner/repo")
refuses(example(), head="not-a-sha")
refuses(b'{"schema_version":1,"schema_version":1}')
refuses(b"x" * 16385)
refuses(b"")
print("merge-evidence tests: PASS")
