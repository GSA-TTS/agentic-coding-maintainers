"""Offline bounded Issues-connection observation fixtures; no real GitHub calls."""

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts/observe-github-issues.py"
spec = importlib.util.spec_from_file_location("issue_observer", CLI)
assert spec and spec.loader
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
START = observer.utc("2026-10-01T00:00:00Z")
END = observer.utc("2026-10-26T00:00:00Z")
FIXTURE = pathlib.Path(tempfile.mkdtemp(prefix="github-issues-observation-"))
FIXTURE.chmod(0o700)
(FIXTURE / "MANIFEST.md").write_text(
    "Synthetic GitHub Issues observations and report key from tests/observe-github-issues-test.py. "
    "No real issues, credentials or user data. Safe for operator disposal.\n", encoding="utf-8")
KEY = FIXTURE / "report.key"
KEY.write_bytes(b"synthetic-private-report-key-32bytes!!")
KEY.chmod(0o600)


def node(number, created="2026-10-05T00:00:00Z"):
    return {"number": number, "createdAt": created}


def response(nodes=None, has_next=False, cursor=None):
    return {"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": has_next,
                                                              "endCursor": cursor},
                                                   "nodes": nodes if nodes is not None else []}}}}


def two_pass(pages):
    observed = []

    def get(owner, repo, cursor, deadline):
        assert owner == "acme" and repo == "widgets"
        observed.append(cursor)
        return pages[len(observed) - 1]

    first = observer.scan("acme/widgets", START, END, get, observer.time.monotonic() + 2)
    second = observer.scan("acme/widgets", START, END, get, observer.time.monotonic() + 2)
    return first, second, observed


def rejects(pages):
    try:
        observer.scan("acme/widgets", START, END, lambda *_: pages[0], observer.time.monotonic() + 2)
    except observer.Unverified:
        return
    raise AssertionError("invalid issues page accepted")


first, second, calls = two_pass([response([]), response([])])
assert first == second == [()] and calls == [None, None]
first, second, calls = two_pass([response([node(1)], True, "cursor-1"),
                                 response([node(2)], False),
                                 response([node(1)], True, "cursor-1"),
                                 response([node(2)], False)])
assert first == second == [(1,), (2,)] and calls == [None, "cursor-1", None, "cursor-1"]
boundary = response([node(3, "2026-10-25T23:59:59Z"), node(4, "2026-10-26T00:00:00Z")], True, "later")
assert observer.scan("acme/widgets", START, END, lambda *_: boundary, observer.time.monotonic() + 2) == [(3,)]
rejects([response([], True, "cursor-1")])
rejects([response([node(1), node(1)])])
rejects([{"errors": [{"message": "rate limit"}], "data": None}])
rejects([response([{"number": True, "createdAt": "2026-10-05T00:00:00Z"}])])
rejects([response([node(1)], True, None)])
rejects([response([node(1, "2026-10-26T00:00:00Z")], True, None)])
for invalid in ({}, {"data": None}, {"data": {}}, {"data": {"repository": None}},
                {"data": {"repository": {}}},
                {"data": {"repository": {"issues": {"nodes": []}}}},
                {"data": {"repository": {"issues": {"pageInfo": {"hasNextPage": False}}}}}):
    rejects([invalid])

# Real CLI path: a local gh stub emits two small responses and refuses any
# command other than the allowlisted GraphQL read. No title/body is emitted.
stub = FIXTURE / "gh"
stub.write_text(
    "#!/usr/bin/env python3\n"
    "import json,sys\n"
    "assert sys.argv[1:4] == ['api','--method','POST']\n"
    "assert sys.argv[4] == 'https://api.github.com/graphql'\n"
    "query=next(arg for arg in sys.argv if arg.startswith('query='))[6:]\n"
    "assert query == " + repr(observer.QUERY) + " and query.lstrip().startswith('query(')\n"
    "assert 'mutation' not in query.lower()\n"
    "assert all(arg in ('https://api.github.com/graphql','-f') or arg.startswith(('query=','owner=','repo=','after=')) for arg in sys.argv[4:])\n"
    "assert any(arg=='owner=acme' for arg in sys.argv) and any(arg=='repo=widgets' for arg in sys.argv)\n"
    "print(json.dumps(" + repr(response([node(987654321)])) + "))\n",
    encoding="utf-8",
)
stub.chmod(0o700)
env = {**os.environ, "PATH": str(FIXTURE) + os.pathsep + os.environ.get("PATH", "")}
env.pop("GH_HOST", None)
env.pop("GITHUB_HOST", None)
for proxy in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    env.pop(proxy, None)
command = [sys.executable, "-I", "-B", str(CLI), "--repository", "acme/widgets",
           "--window-start", "2026-10-01T00:00:00Z", "--as-of", "2026-10-26T00:00:00Z",
           "--key-file", str(KEY)]
success = subprocess.run(command, env=env, capture_output=True, check=False, timeout=10)
assert success.returncode == 0 and not success.stderr, success.stderr
output = json.loads(success.stdout)
assert output["coverage"] == "TWO_CONSISTENT_VISIBLE_READS_NOT_ATOMIC"
assert output["issue_count"] == 1 and output["page_count"] == 1 and len(output["observation_identity_hmac"]) == 64
assert set(output) == {"schema_version", "mode", "coverage", "page_count", "issue_count",
                       "observation_identity_hmac", "limitation"}
assert type(output["issue_count"]) is int and "acme/widgets" not in success.stdout.decode()
assert b"987654321" not in success.stdout and b"987654321" not in success.stderr
env["GH_HOST"] = "other.example"
wrong_host = subprocess.run(command, env=env, capture_output=True, check=False, timeout=10)
assert wrong_host.returncode == 3 and b"UNVERIFIED" in wrong_host.stderr and not wrong_host.stdout
env.pop("GH_HOST")
env["HTTPS_PROXY"] = "http://invalid.example"
proxy_refusal = subprocess.run(command, env=env, capture_output=True, check=False, timeout=10)
assert proxy_refusal.returncode == 3 and b"UNVERIFIED" in proxy_refusal.stderr and not proxy_refusal.stdout
assert b"987654321" not in proxy_refusal.stderr
env.pop("HTTPS_PROXY")
# Capture mode is different from summary mode: it MUST continue after an
# as-of boundary page if the API still advertises a successor. GitHub may
# include a non-null terminal endCursor, normalized to null for the adapter's
# continuation-only cursor_out contract.
capture_file = FIXTURE / "full-capture.json"
normal_stub = stub.read_text(encoding="utf-8")
stub.write_text(
    "#!/usr/bin/env python3\n"
    "import json,sys\n"
    "assert sys.argv[1:5] == ['api','--method','POST','https://api.github.com/graphql']\n"
    "query=next(arg for arg in sys.argv if arg.startswith('query='))[6:]\n"
    "assert query == " + repr(observer.QUERY) + "\n"
    "after=next((arg[6:] for arg in sys.argv if arg.startswith('after=')),None)\n"
    "if after is None:\n"
    "  payload=" + repr(response([node(987654321, "2026-10-26T00:00:00Z")], True, "cursor-one")) + "\n"
    "elif after=='cursor-one':\n"
    "  payload=" + repr(response([node(987654322, "2026-10-27T00:00:00Z")], False, "api-terminal-cursor")) + "\n"
    "else: sys.exit(9)\n"
    "print(json.dumps(payload))\n",
    encoding="utf-8",
)
stub.chmod(0o700)
capture_command = command + ["--capture-output", str(capture_file)]
capture_result = subprocess.run(capture_command, env=env, capture_output=True, check=False, timeout=10)
assert capture_result.returncode == 0 and b"UNVERIFIED" in capture_result.stdout, capture_result.stderr
assert capture_file.stat().st_mode & 0o777 == 0o600
captured = json.loads(capture_file.read_text(encoding="utf-8"))
assert len(captured["passes"]) == 2 and all(len(p["pages"]) == 2 for p in captured["passes"])
assert all(p["pages"][0]["has_next"] and p["pages"][0]["cursor_out"] == "cursor-one" for p in captured["passes"])
assert all(p["pages"][1]["cursor_in"] == "cursor-one" and p["pages"][1]["cursor_out"] is None for p in captured["passes"])
assert b"987654321" not in capture_result.stdout and b"cursor-one" not in capture_result.stdout
repeated = subprocess.run(capture_command, env=env, capture_output=True, check=False, timeout=10)
assert repeated.returncode == 3 and b"UNVERIFIED" in repeated.stderr and capture_file.exists()
stub.write_text(normal_stub, encoding="utf-8")

# Duplicate JSON keys can overwrite pageInfo flags before scan() sees them;
# a contradictory true/false hasNextPage must refuse rather than publish a
# purported full-terminal capture. Terminal cursor values must be validated
# BEFORE normalization to null in the v1 continuation-only format.
for raw in (
    b'{"data":{"repository":{"issues":{"pageInfo":{"hasNextPage":true,"hasNextPage":false,"endCursor":null},"nodes":[]}}}}',
    json.dumps(response([node(987654321)], False, "x" * 257)).encode(),
    json.dumps(response([node(987654321)], False, "\ud800")).encode(),
):
    stub.write_text("#!/usr/bin/env python3\nimport sys\nsys.stdout.buffer.write(" + repr(raw) + ")\n", encoding="utf-8")
    stub.chmod(0o700)
    bad_capture = FIXTURE / f"bad-capture-{len(list(FIXTURE.glob('bad-capture-*')))}.json"
    failed = subprocess.run(command + ["--capture-output", str(bad_capture)], env=env,
                            capture_output=True, check=False, timeout=10)
    assert failed.returncode == 3 and b"UNVERIFIED" in failed.stderr and not failed.stdout
    assert not bad_capture.exists()
stub.write_text(normal_stub, encoding="utf-8")
for body in ("import sys; sys.stdout.write('x'*70000)\n",
             "import sys; sys.stderr.write('x'*70000)\n",
             "import sys; sys.stdout.write('x'*35000); sys.stderr.write('y'*35000)\n",
             "import sys; sys.exit(9)\n",
             "print('not-json')\n"):
    stub.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    stub.chmod(0o700)
    failed = subprocess.run(command, env=env, capture_output=True, check=False, timeout=10)
    assert failed.returncode == 3 and b"UNVERIFIED" in failed.stderr and not failed.stdout
    assert b"987654321" not in failed.stderr
print("observe-github-issues tests: PASS")
print("github_issues_fixture=" + str(FIXTURE), file=sys.stderr)
