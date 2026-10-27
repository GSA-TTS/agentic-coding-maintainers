"""Offline historical review-request observations for a declared PR only."""

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts/observe-review-requests.py"
spec = importlib.util.spec_from_file_location("review_events", CLI)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
START, END = module.utc("2026-10-01T00:00:00Z"), module.utc("2026-10-26T00:00:00Z")
FIXTURE = pathlib.Path(tempfile.mkdtemp(prefix="review-requests-observation-"))
FIXTURE.chmod(0o700)
(FIXTURE / "MANIFEST.md").write_text(
    "Synthetic review-request event and private-key fixtures from tests/observe-review-requests-test.py. "
    "No real GitHub or user data; safe for operator disposal.\n", encoding="utf-8")
KEY = FIXTURE / "report.key"
KEY.write_bytes(b"synthetic-review-request-report-key-32bytes")
KEY.chmod(0o600)


def event(event_id, name="review_requested", *, target="user", created="2026-10-05T00:00:00Z"):
    row = {"id": event_id, "event": name, "created_at": created}
    if name in module.EVENTS:
        row["requested_reviewer"] = {"login": "private-user"} if target == "user" else None
        row["requested_team"] = {"slug": "private-team"} if target == "team" else None
    return row


url = "https://api.github.com/repos/acme/widgets/issues/7/events?per_page=100&page=1"
two = [event(1), event(2, "review_request_removed", target="team"), event(3, "labeled")]
raw = b"HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n\r\n" + json.dumps(two).encode()
assert module.parse_http(raw, url, 1)[0] == two
assert module.parse_http(raw, url, 1)[1] is None
link = b'Link: <https://api.github.com/repos/acme/widgets/issues/7/events?per_page=100&page=2>; rel="next"\r\n'
assert module.parse_http(b"HTTP/2.0 200 OK\r\n" + link + b"\r\n" + json.dumps(two).encode(), url, 1)[1].endswith("page=2")


def rejects_http(data):
    try:
        module.parse_http(data, url, 1)
    except module.Unverified:
        return
    raise AssertionError("invalid HTTP event response accepted")


rejects_http(b"HTTP/2.0 403 Forbidden\r\n\r\n[]")
rejects_http(b"HTTP/2.0 200 OK\r\n\r\nnot-json")
rejects_http(b"HTTP/2.0 200 OK\r\n" + link.replace(b"page=2", b"page=9") + b"\r\n[]")
rejects_http(b"HTTP/2.0 200 OK\r\n" + link + link + b"\r\n[]")
rejects_http(b"HTTP/2.0 200 OK\r\n\r\n" + json.dumps([event(n) for n in range(1, 101)]).encode())
rejects_http(b"HTTP/2.0 200 OK\r\n\r\n" + b'{"id":1,"id":2}')
rejects_http(b"HTTP/2.0 200 OK\r\n\r\n" + b'[{"id":1,"id":2,"event":"review_requested"}]')


def scans(pages):
    seen = []

    def get(repository, number, page, deadline):
        assert (repository, number) == ("acme/widgets", 7)
        seen.append(page)
        return pages[page - 1]

    return module.scan("acme/widgets", 7, START, END, get, module.time.monotonic() + 2), seen


observed, pages = scans([([event(1), event(2, "review_request_removed", target="team"), event(3, "labeled")], None)])
assert observed == ([(1, "review_requested", "2026-10-05T00:00:00Z", "login", "private-user"),
                     (2, "review_request_removed", "2026-10-05T00:00:00Z", "slug", "private-team")], 1) and pages == [1]
observed, pages = scans([([event(1)], "next"), ([event(2, target="team")], None)])
assert observed[1] == 2 and pages == [1, 2]


def rejects_scan(pages):
    try:
        scans(pages)
    except module.Unverified:
        return
    raise AssertionError("incomplete event scan was accepted")


rejects_scan([([], "next")])
rejects_scan([([event(1), event(1)], None)])
rejects_scan([([event(1, target="none")], None)])
rejects_scan([([dict(event(1), requested_reviewer={})], None)])
rejects_scan([([dict(event(1), requested_reviewer="redacted")], None)])
rejects_scan([([event(1, created="2026-99-99T00:00:00Z")], None)])

# End-to-end CLI runs a fake gh with a constrained absolute GET. It must emit
# only an aggregate and keyed fingerprint, not private reviewer/team details.
stub = FIXTURE / "gh"
stub.write_text(
    "#!/usr/bin/env python3\n"
    "import json,sys\n"
    "assert sys.argv[1:4] == ['api','--method','GET'] and sys.argv[4]=='--include'\n"
    "if sys.argv[5].endswith('/pulls/7'):\n"
    "  assert sys.argv[6:8]==['--jq','{number,base:{repo:{full_name}}}']\n"
    "  sys.stdout.buffer.write(b'HTTP/2.0 200 OK\\r\\n\\r\\n'+json.dumps({'number':7,'base':{'repo':{'full_name':'acme/widgets'}}}).encode())\n"
    "else:\n"
    "  assert sys.argv[5] == " + repr(url) + "\n"
    "  sys.stdout.buffer.write(" + repr(raw) + ")\n",
    encoding="utf-8",
)
stub.chmod(0o700)
env = {**os.environ, "PATH": str(FIXTURE) + os.pathsep + os.environ.get("PATH", "")}
for key in ("GH_HOST", "GITHUB_HOST", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    env.pop(key, None)
cmd = [sys.executable, "-I", "-B", str(CLI), "--repository", "acme/widgets", "--pr", "7",
       "--window-start", "2026-10-01T00:00:00Z", "--as-of", "2026-10-26T00:00:00Z",
       "--key-file", str(KEY)]
result = subprocess.run(cmd, env=env, capture_output=True, check=False, timeout=10)
assert result.returncode == 0 and not result.stderr, result.stderr
output = json.loads(result.stdout)
assert set(output) == {"schema_version", "mode", "coverage", "event_count", "page_count", "observation_identity_hmac", "limitation"}
assert output["event_count"] == 2 and len(output["observation_identity_hmac"]) == 64
assert all(secret not in result.stdout + result.stderr for secret in (b"acme/widgets", b"private-user", b"private-team"))
env["GH_HOST"] = "other.example"
bad_host = subprocess.run(cmd, env=env, capture_output=True, check=False, timeout=10)
assert bad_host.returncode == 3 and b"UNVERIFIED" in bad_host.stderr and not bad_host.stdout
env.pop("GH_HOST")
# An issue number that has no Pulls API resource is not a PR. The observer
# must refuse before it requests event history.
stub.write_text(
    "#!/usr/bin/env python3\nimport json,sys,pathlib\n"
    "calls=pathlib.Path(" + repr(str(FIXTURE / "ordinary-calls.txt")) + ")\n"
    "with calls.open('a') as log: log.write(sys.argv[5]+'\\n')\n"
    "if sys.argv[5].endswith('/pulls/7'):\n"
    "  sys.stdout.buffer.write(b'HTTP/2.0 404 Not Found\\r\\n\\r\\n{}')\n"
    "else:\n"
    "  sys.stdout.buffer.write(b'HTTP/2.0 200 OK\\r\\n\\r\\n'+json.dumps(" + repr(two) + ").encode())\n",
    encoding="utf-8",
)
stub.chmod(0o700)
ordinary = subprocess.run(cmd, env=env, capture_output=True, check=False, timeout=10)
assert ordinary.returncode == 3 and b"UNVERIFIED" in ordinary.stderr and not ordinary.stdout
assert (FIXTURE / "ordinary-calls.txt").read_text(encoding="utf-8").splitlines() == [
    "https://api.github.com/repos/acme/widgets/pulls/7"]

# Both complete event passes must traverse Link page 2 and compare target
# identity. A missing next Link on a full page or a target changed on pass 2
# cannot report a historical request observation.
page1 = [event(n, "labeled") for n in range(1, 101)]
page1[0] = event(1)
page2 = [event(101, "review_request_removed", target="team")]
first_page = b"HTTP/2.0 200 OK\r\n" + link + b"\r\n" + json.dumps(page1).encode()
second_page = b"HTTP/2.0 200 OK\r\n\r\n" + json.dumps(page2).encode()
counter = FIXTURE / "event-calls.txt"


def paged_stub(*, changed=False, missing_link=False):
    source = (
        "#!/usr/bin/env python3\nimport json,sys,pathlib\n"
        "counter=pathlib.Path(" + repr(str(counter)) + ")\n"
        "calls=int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(calls+1))\n"
        "url=sys.argv[5]\n"
        "if url.endswith('/pulls/7'):\n"
        "  sys.stdout.buffer.write(b'HTTP/2.0 200 OK\\r\\n\\r\\n'+json.dumps({'number':7,'base':{'repo':{'full_name':'acme/widgets'}}}).encode())\n"
        "elif url.endswith('page=1'):\n"
        "  sys.stdout.buffer.write(" + repr(first_page if not missing_link else b"HTTP/2.0 200 OK\r\n\r\n" + json.dumps(page1).encode()) + ")\n"
        "elif url.endswith('page=2'):\n"
        "  payload=" + repr(second_page) + " if (not " + repr(changed) + " or calls < 4) else " + repr(b"HTTP/2.0 200 OK\r\n\r\n" + json.dumps([dict(page2[0], requested_team={"slug": "other-team"})]).encode()) + "\n"
        "  sys.stdout.buffer.write(payload)\n"
        "else: sys.exit(9)\n"
    )
    stub.write_text(source, encoding="utf-8")
    stub.chmod(0o700)


counter.write_text("0", encoding="utf-8")
paged_stub()
multi = subprocess.run(cmd, env=env, capture_output=True, check=False, timeout=10)
assert multi.returncode == 0 and not multi.stderr, multi.stderr
assert json.loads(multi.stdout)["page_count"] == 2 and json.loads(multi.stdout)["event_count"] == 2
assert counter.read_text(encoding="utf-8") == "5"  # identity GET + two pages per pass
counter.write_text("0", encoding="utf-8")
paged_stub(changed=True)
changed_target = subprocess.run(cmd, env=env, capture_output=True, check=False, timeout=10)
assert changed_target.returncode == 3 and b"UNVERIFIED" in changed_target.stderr and not changed_target.stdout
assert b"private-team" not in changed_target.stderr and b"other-team" not in changed_target.stderr
assert counter.read_text(encoding="utf-8") == "5"
counter.write_text("0", encoding="utf-8")
paged_stub(missing_link=True)
unbounded = subprocess.run(cmd, env=env, capture_output=True, check=False, timeout=10)
assert unbounded.returncode == 3 and b"UNVERIFIED" in unbounded.stderr and not unbounded.stdout
print("observe-review-requests tests: PASS")
print("review_requests_fixture=" + str(FIXTURE), file=sys.stderr)
