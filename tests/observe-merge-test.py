"""Offline synthetic GitHub observations; never call a real API in this test."""

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/observe-merge.py"
spec = importlib.util.spec_from_file_location("merge_observation", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
HEAD, MERGE = "a" * 40, "b" * 40
mapping = {"schema_version": 1, "case_id": "case-1", "repository": "acme/widgets", "number": 7, "head_sha": HEAD}
pr = {"number": 7, "base": {"repo": {"full_name": "acme/widgets"}}, "head": {"sha": HEAD},
      "state": "closed",
      "merged": True, "merged_at": "2020-01-01T12:00:00Z", "merge_commit_sha": MERGE}


def observed(response=pr, commit_sha=MERGE):
    calls = []

    def get(endpoint):
        calls.append(endpoint)
        if endpoint.endswith("/pulls/7"):
            return response
        if endpoint.endswith("/commits/" + MERGE):
            return {"sha": commit_sha}
        raise AssertionError("unapproved endpoint: " + endpoint)

    result = module.observe(mapping, get)
    return result, calls


result, calls = observed()
assert result == "MERGE_OBSERVED_IN_GITHUB"
assert calls == ["repos/acme/widgets/pulls/7", "repos/acme/widgets/commits/" + MERGE]
unmerged = dict(pr, merged=False, state="open", merged_at=None, merge_commit_sha=None)
assert observed(unmerged)[0] == "NOT_MERGED"


def refuses(response, *, commit_sha=MERGE):
    try:
        observed(response, commit_sha)
    except module.Unverified:
        return
    raise AssertionError("contradictory GitHub response was accepted")


refuses(dict(pr, number=8))
refuses(dict(pr, base={"repo": {"full_name": "other/repo"}}))
refuses(dict(pr, head={"sha": "c" * 40}))
refuses(dict(pr, merged="true"))
refuses(dict(pr, merged_at=None))
refuses(dict(pr, merged_at="9999-12-31T12:00:00Z"))
refuses(dict(pr, merge_commit_sha=None))
refuses(dict(pr, merged=False))
refuses(dict(pr, state="open"))
refuses(dict(pr, state=None))
refuses({key: value for key, value in pr.items() if key != "state"})
refuses(pr, commit_sha="c" * 40)

# The CLI refuses a caller-controlled symlink/private-file violation BEFORE it
# reaches gh. A malicious gh stub makes any accidental network/exec visible.
fixture = pathlib.Path(tempfile.mkdtemp(prefix="merge-observation-"))
fixture.chmod(0o700)
(fixture / "MANIFEST.md").write_text(
    "Synthetic case-to-PR mapping for tests/observe-merge-test.py; no real user data. "
    "This private test directory is safe for operator disposal.\n", encoding="utf-8")
private = fixture / "mapping.json"
private.write_text(json.dumps(mapping), encoding="utf-8")
private.chmod(0o600)
assert module.private_mapping(private) == mapping
for broken in (dict(mapping, case_id="bad/case"), dict(mapping, number=True), dict(mapping, head_sha="bad")):
    private.write_text(json.dumps(broken), encoding="utf-8")
    try:
        module.private_mapping(private)
    except module.Unverified:
        pass
    else:
        raise AssertionError("invalid mapping accepted")
private.write_text(json.dumps(mapping), encoding="utf-8")
linked = fixture / "linked.json"
linked.symlink_to(private)
try:
    module.private_mapping(linked)
except OSError:
    pass
else:
    raise AssertionError("symlinked mapping accepted")
private.chmod(0o644)
try:
    module.private_mapping(private)
except module.Unverified:
    pass
else:
    raise AssertionError("world-readable mapping accepted")
private.chmod(0o600)
result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--mapping", str(private), "--case-id", "other"],
                        capture_output=True, text=True, check=False)
assert result.returncode == 3 and "UNVERIFIED" in result.stderr and not result.stdout
# Exercise the SUCCESSFUL CLI through a local gh fixture, not only observe()
# with a Python getter. It must keep delivery credit false and never emit raw
# case/repo identity. The stub refuses any host other than api.github.com.
stub = fixture / "gh"
stub.write_text(
    "#!/usr/bin/env python3\n"
    "import json,sys\n"
    "assert sys.argv[1:4] == ['api','--method','GET']\n"
    "url=sys.argv[4]\n"
    "assert url.startswith('https://api.github.com/repos/acme/widgets/')\n"
    "if url.endswith('/pulls/7'):\n"
    "  print(json.dumps(" + repr(pr) + "))\n"
    "elif url.endswith('/commits/' + '" + MERGE + "'):\n"
    "  print(json.dumps({'sha':'" + MERGE + "'}))\n"
    "else: sys.exit(9)\n",
    encoding="utf-8",
)
stub.chmod(0o700)
env = {**os.environ, "PATH": str(fixture) + os.pathsep + os.environ.get("PATH", "")}
env.pop("GH_HOST", None)
env.pop("GITHUB_HOST", None)
success = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--mapping", str(private),
                          "--case-id", "case-1"], env=env, capture_output=True, text=True, check=False, timeout=25)
assert success.returncode == 0 and not success.stderr
output = json.loads(success.stdout)
assert output["classification"] == "MERGE_OBSERVED_IN_GITHUB"
assert output["cohort_delivery_credit"] is False and output["policy_compliance"] == "UNMEASURED"
assert "UNVERIFIED caller-supplied" in output["source"]
assert "case-1" not in success.stdout and "acme/widgets" not in success.stdout
env["GH_HOST"] = "other.example"
wrong_host = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--mapping", str(private),
                             "--case-id", "case-1"], env=env, capture_output=True, text=True, check=False, timeout=25)
assert wrong_host.returncode == 3 and "UNVERIFIED" in wrong_host.stderr and not wrong_host.stdout
# Failure-mode stub variants: none may return success JSON. The subprocess
# calling the CLI has its OWN timeout, so a hanging implementation goes red
# instead of hanging the test suite indefinitely.
env.pop("GH_HOST")


def failure_stub(body):
    stub.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    stub.chmod(0o700)
    attempted = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--mapping", str(private),
                                "--case-id", "case-1"], env=env, capture_output=True, text=True,
                               check=False, timeout=25)
    assert attempted.returncode == 3 and "UNVERIFIED" in attempted.stderr and not attempted.stdout, attempted


failure_stub("import sys; sys.stdout.write('x'*9000)\n")
failure_stub("import sys; sys.stderr.write('x'*9000)\n")
failure_stub("print('not-json')\n")
failure_stub("import sys; sys.exit(9)\n")
failure_stub("import time; time.sleep(16)\n")
# A child inherits gh's stdout and tries to outlive it. The observation must
# terminate the isolated group and not wait forever for that open pipe.
child_pid = fixture / "child.pid"
stub.write_text(
    "#!/usr/bin/env python3\n"
    "import json,subprocess,sys\n"
    "subprocess.Popen([sys.executable,'-c'," + repr("import os,time; open(" + repr(str(child_pid)) + ", 'w').write(str(os.getpid())); time.sleep(16)") + "])\n"
    "print(json.dumps(" + repr(pr) + "),flush=True)\n",
    encoding="utf-8",
)
stub.chmod(0o700)
held_pipe = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--mapping", str(private),
                            "--case-id", "case-1"], env=env, capture_output=True, text=True,
                           check=False, timeout=25)
assert held_pipe.returncode == 3 and "UNVERIFIED" in held_pipe.stderr and not held_pipe.stdout
assert child_pid.exists(), "child never started; test did not exercise process-group cleanup"
pid = int(child_pid.read_text(encoding="utf-8"))
for _ in range(20):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        break
    time.sleep(0.05)
else:
    raise AssertionError("GitHub helper child survived the timed-out observation")
print("observe-merge tests: PASS")
print("observe_merge_fixture=" + str(fixture), file=sys.stderr)
