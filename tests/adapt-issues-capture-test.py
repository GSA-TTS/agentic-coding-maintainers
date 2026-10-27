"""Offline full-terminal two-pass capture fixtures, with no GitHub calls."""

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADAPTER = ROOT / "scripts/adapt-issues-capture.py"
VALIDATOR = ROOT / "scripts/check-intake-sources.py"
FIXTURE = pathlib.Path(tempfile.mkdtemp(prefix="issues-capture-adapter-"))
FIXTURE.chmod(0o700)
(FIXTURE / "MANIFEST.md").write_text(
    "Synthetic private Issues captures, report key and v1 registry output from tests/adapt-issues-capture-test.py. "
    "No real GitHub issues or user data; safe for operator disposal.\n", encoding="utf-8")
CAPTURE, OUTPUT, KEY = (FIXTURE / name for name in ("capture.json", "registry.json", "report.key"))
KEY.write_bytes(b"synthetic-hmac-key-at-least-thirty-two-bytes")
KEY.chmod(0o600)


def page(cursor=None, successor=None, more=False, issues=None):
    return {"cursor_in": cursor, "cursor_out": successor, "has_next": more,
            "issues": issues if issues is not None else []}


def issue(number, created="2026-10-05T00:00:00Z"):
    return {"number": number, "created_at": created}


def capture(pages=None, *, second=None):
    pages = pages if pages is not None else [page(issues=[issue(7)])]
    return {"schema_version": 1, "repository": "acme/widgets",
            "window_start": "2026-10-01T00:00:00Z", "as_of": "2026-10-26T00:00:00Z",
            "query_type": "graphql_issues_created_asc",
            "passes": [{"captured_at": "2026-10-27T00:00:00Z", "pages": pages},
                       {"captured_at": "2026-10-27T00:01:00Z", "pages": second if second is not None else pages}]}


def run(value, *, output=OUTPUT, required="issue-feed:github_issues"):
    CAPTURE.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    CAPTURE.chmod(0o600)
    args = [sys.executable, "-I", "-B", str(ADAPTER), "--capture", str(CAPTURE),
            "--output", str(output), "--key-file", str(KEY), "--repository", "acme/widgets",
            "--window-start", "2026-10-01T00:00:00Z", "--as-of", "2026-10-26T00:00:00Z"]
    result = subprocess.run(args, capture_output=True, check=False, timeout=5)
    if result.returncode == 0:
        checked = subprocess.run([sys.executable, "-I", "-B", str(VALIDATOR), "--registry", str(output),
                                  "--required-source", required], capture_output=True, check=False, timeout=5)
        assert checked.returncode == 3 and not checked.stderr, checked.stderr
        report = json.loads(checked.stdout)
        assert report["status"] == "UNVERIFIED" and report["incomplete_source_count"] == 1
    return result


def expects_reject(value):
    target = FIXTURE / f"rejected-{len(list(FIXTURE.glob('rejected-*')))}.json"
    result = run(value, output=target)
    assert result.returncode == 3 and b"UNVERIFIED" in result.stderr and not result.stdout, result
    assert not target.exists(), "rejected capture created a registry entry"


first = run(capture())
assert first.returncode == 0 and b"provenance UNVERIFIED" in first.stdout
registry = json.loads(OUTPUT.read_text(encoding="utf-8"))
assert registry["sources"][0]["coverage"] == "partial"
assert registry["sources"][0]["source_type"] == "github_issues"
assert registry["sources"][0]["pages"][0]["request_ids"] != ["7"]
assert "acme/widgets" not in first.stdout.decode()
empty = run(capture([page()]), output=FIXTURE / "empty.json")
assert empty.returncode == 0
two = [page(successor="opaque-cursor-1", more=True, issues=[issue(7), issue(8)]),
       page(cursor="opaque-cursor-1", issues=[issue(9)])]
multi = run(capture(two), output=FIXTURE / "multi.json")
assert multi.returncode == 0
result = json.loads((FIXTURE / "multi.json").read_text(encoding="utf-8"))
assert len(result["sources"][0]["pages"]) == 2
assert result["sources"][0]["pages"][0]["cursor_out"] == result["sources"][0]["pages"][1]["cursor_in"]
assert "opaque-cursor-1" not in json.dumps(result)

expects_reject(capture(two, second=[page(issues=[issue(7), issue(10)])]))
expects_reject(capture([page(issues=[issue(7)])], second=[page(issues=[issue(7, "2026-10-06T00:00:00Z")])]))
expects_reject(capture([page(issues=[issue(7)])], second=[page(issues=[issue(7), issue(8, "2026-10-27T00:00:00Z")])]))
duplicate_pass_time = capture()
duplicate_pass_time["passes"][1]["captured_at"] = duplicate_pass_time["passes"][0]["captured_at"]
expects_reject(duplicate_pass_time)
expects_reject(capture([page(successor="\ud800", more=True), page(cursor="\ud800")]))
expects_reject(capture([page(successor="next", more=True)]))
expects_reject(capture([page(issues=[issue(7)]), page(issues=[issue(8)])]))
expects_reject(capture([page(successor="next", more=True, issues=[issue(7)]),
                       page(cursor="next", issues=[issue(7)])]))
expects_reject(capture([page(issues=[issue(7, "2026-10-26T00:00:00Z")])],
                       second=[page(issues=[issue(7)])]))
expects_reject(dict(capture(), repository="different/repo"))
expects_reject(dict(capture(), query_type="rest_issues_including_prs"))
expects_reject(b'{"schema_version":1,"schema_version":1}')
expects_reject(b"x" * 65537)
linked = FIXTURE / "linked-capture.json"
linked.symlink_to(CAPTURE)
assert run(capture(), output=linked).returncode == 3
print("adapt-issues-capture tests: PASS")
print("issues_capture_fixture=" + str(FIXTURE), file=sys.stderr)
