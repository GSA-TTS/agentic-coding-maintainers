"""Offline synthetic GitHub observations; never call a real API in this test."""

import importlib.util
import json
import os
import pathlib
import shutil
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
      "state": "closed", "merged_at_present": True, "merge_commit_sha_present": True,
      "merged": True, "merged_at": "2020-01-01T12:00:00Z", "merge_commit_sha": MERGE}


def observed(response=pr, commit_sha=MERGE):
    calls = []

    def get(endpoint, projection):
        calls.append((endpoint, projection))
        if endpoint.endswith("/pulls/7"):
            return response
        if endpoint.endswith("/commits/" + MERGE):
            return {"sha": commit_sha}
        raise AssertionError("unapproved endpoint: " + endpoint)

    result = module.observe(mapping, get)
    return result, calls


result, calls = observed()
assert result == "MERGE_OBSERVED_IN_GITHUB"
assert calls == [("repos/acme/widgets/pulls/7", module.PR_FIELDS),
                 ("repos/acme/widgets/commits/" + MERGE, module.COMMIT_FIELDS)]
# Evaluate the EXACT --jq expression on raw synthetic API responses. The CLI
# stub below manually emits projected JSON and cannot prove jq actually drops
# a large PR body or distinguishes omitted fields from explicit null values.
raw_pr = dict(pr, body="x" * 100_000)
for label, value in (("complete", raw_pr),
                     ("omitted-time", {key: item for key, item in raw_pr.items() if key != "merged_at"}),
                     ("explicit-null-time", dict(raw_pr, merged_at=None)),
                     ("omitted-commit", {key: item for key, item in raw_pr.items() if key != "merge_commit_sha"}),
                     ("explicit-null-commit", dict(raw_pr, merge_commit_sha=None))):
    projection = subprocess.run(["jq", "-c", module.PR_FIELDS], input=json.dumps(value).encode(),
                                capture_output=True, check=False, timeout=5)
    assert projection.returncode == 0, projection.stderr
    projected = json.loads(projection.stdout)
    assert "body" not in projected and len(projection.stdout) < module.MAX_BYTES
    assert projected["merged_at_present"] is (label != "omitted-time")
    assert projected["merge_commit_sha_present"] is (label != "omitted-commit")
    assert "merged_at" in projected and "merge_commit_sha" in projected
    if label == "explicit-null-time":
        assert projected["merged_at"] is None
    if label == "explicit-null-commit":
        assert projected["merge_commit_sha"] is None
    if label.startswith("omitted"):
        refuses_projection = False
        try:
            module.observe(mapping, lambda _endpoint, _projection: projected)
        except module.Unverified:
            refuses_projection = True
        assert refuses_projection, "an omitted raw merge field survived the projection"
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
refuses(dict(pr, merged=False, merged_at=None, merged_at_present=False))
refuses(dict(pr, merged=False, merged_at=None, merge_commit_sha_present=False))
refuses({k: v for k, v in dict(pr, merged=False).items() if k != "merged_at"})
refuses({k: v for k, v in dict(pr, merged=False).items() if k != "merge_commit_sha"})
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
ledger = fixture / "cases.jsonl"
key_file = fixture / "report.key"
test_key = b"synthetic-merge-ledger-report-key!!"
key_file.write_bytes(test_key)
key_file.chmod(0o600)
intake = {"schema_version": 1, "event_id": "intake-1", "case_id": "case-1", "event_type": "intake",
          "occurred_at": "2020-01-01T00:00:00Z", "recorded_at": "2020-01-01T00:01:00Z",
          "case_type": "implementation", "eligibility": "eligible"}
association = {"schema_version": 1, "event_id": "association-2", "case_id": "case-1", "event_type": "pr_association",
               "occurred_at": "2020-01-02T00:00:00Z", "recorded_at": "2020-01-02T00:01:00Z",
               "intake_event_id": "intake-1", "repository": "acme/widgets", "pr_number": 7,
               "head_sha": HEAD, "provenance": "agent_recorded"}
ledger.write_text(json.dumps(intake) + "\n" + json.dumps(association) + "\n", encoding="utf-8")
ledger.chmod(0o600)


def check_binding(candidate, mapped=mapping, *, valid=True):
    ledger.write_text("".join(json.dumps(row) + "\n" for row in candidate), encoding="utf-8")
    ledger.chmod(0o600)
    if valid:
        module.bind_ledger(ledger, mapped, test_key)
    else:
        try:
            module.bind_ledger(ledger, mapped, test_key)
        except (module.Unverified, ValueError):
            pass
        else:
            raise AssertionError("invalid ledger association was accepted")


check_binding([intake, association])
check_binding([], valid=False)
check_binding([dict(intake, case_id="other")], valid=False)
check_binding([dict(intake, case_type="review")], valid=False)
check_binding([dict(intake, eligibility="unknown")], valid=False)
check_binding([dict(intake, eligibility="excluded")], valid=False)
check_binding([dict(intake, recorded_at="9999-12-31T00:00:00Z")], valid=False)
check_binding([intake], valid=False)
check_binding([intake, dict(association, repository="other/widgets")], valid=False)
check_binding([intake, dict(association, pr_number=8)], valid=False)
check_binding([intake, dict(association, head_sha="c" * 40)], valid=False)
check_binding([intake, association, dict(association, event_id="association-3")], valid=False)
check_binding([intake, dict(association, provenance="maintainer_confirmed")], valid=False)
valid_fix = {"schema_version": 1, "event_id": "correction-2", "case_id": "case-1",
             "event_type": "eligibility_correction", "intake_event_id": "intake-1",
             "occurred_at": "2020-01-02T00:00:00Z", "recorded_at": "2020-01-02T00:01:00Z",
             "replacement": "eligible", "reason_code": "eligibility_review"}
check_binding([dict(intake, eligibility="unknown"), valid_fix, association], valid=True)
check_binding([intake, dict(valid_fix, replacement="excluded"), association], valid=False)
future_fix = {"schema_version": 1, "event_id": "correction-2", "case_id": "case-1",
              "event_type": "eligibility_correction", "intake_event_id": "intake-1",
              "occurred_at": "2020-01-02T00:00:00Z", "recorded_at": "9999-12-31T00:00:00Z",
              "replacement": "eligible", "reason_code": "eligibility_review"}
check_binding([dict(intake, eligibility="unknown"), future_fix, association], valid=False)
conflicting_review = {"schema_version": 1, "event_id": "review-2", "case_id": "case-1", "event_type": "review",
                      "occurred_at": "2020-01-02T00:00:00Z", "recorded_at": "2020-01-02T00:01:00Z",
                      "head_sha": "c" * 40, "independent": "yes"}
check_binding([intake, association, conflicting_review], valid=True)  # no outcome claim yet
# The v1 event chain requires review → handoff → outcome on the same case/head.
review = dict(conflicting_review, head_sha="a" * 40)
handoff = {"schema_version": 1, "event_id": "handoff-3", "case_id": "case-1", "event_type": "handoff",
           "occurred_at": "2020-01-03T00:00:00Z", "recorded_at": "2020-01-03T00:01:00Z",
           "review_event_id": "review-2", "head_sha": "a" * 40, "checks": "passing"}
outcome = {"schema_version": 1, "event_id": "outcome-4", "case_id": "case-1", "event_type": "outcome",
           "occurred_at": "2020-01-04T00:00:00Z", "recorded_at": "2020-01-04T00:01:00Z",
           "handoff_event_id": "handoff-3", "head_sha": "a" * 40, "repository_event_id": "merge-7"}
check_binding([intake, association, review, handoff, outcome], valid=True)
check_binding([intake, association, dict(review, head_sha="c" * 40), dict(handoff, head_sha="c" * 40),
               dict(outcome, head_sha="c" * 40)], valid=False)
check_binding([intake, association])  # restore the positive CLI fixture
# The validator is code, not ledger data: never follow a symlinked sibling or
# leak a traceback if its import is broken. Do not mutate the checkout's
# canonical validator: an interrupted test must not leave reviewed source
# missing/replaced or race another reader. Run those cases on an isolated copy.
isolated = fixture / "isolated-scripts"
isolated.mkdir(mode=0o700)
copy_script = isolated / SCRIPT.name
shutil.copyfile(SCRIPT, copy_script)
copy_script.chmod(0o600)
validator = isolated / "cohort-reflection.py"
validator_bytes = SCRIPT.with_name("cohort-reflection.py").read_bytes()
validator.write_bytes(validator_bytes)
validator.chmod(0o600)
validator_backup = fixture / "validator-original.py"
validator_backup.write_bytes(validator_bytes)
validator_backup.chmod(0o600)
isolated_spec = importlib.util.spec_from_file_location("isolated_observer", copy_script)
assert isolated_spec and isolated_spec.loader
isolated_module = importlib.util.module_from_spec(isolated_spec)
isolated_spec.loader.exec_module(isolated_module)
validator.unlink()
validator.symlink_to(validator_backup)
try:
    isolated_module.bind_ledger(ledger, mapping, test_key)
except isolated_module.Unverified:
    pass
else:
    raise AssertionError("symlinked validator accepted")
validator.unlink()
validator.write_text("raise ImportError('synthetic broken validator')\n", encoding="utf-8")
try:
    isolated_module.bind_ledger(ledger, mapping, test_key)
except isolated_module.Unverified:
    pass
else:
    raise AssertionError("changed validator accepted without a reviewed digest")
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
result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--mapping", str(private),
                         "--ledger", str(ledger), "--key-file", str(key_file), "--case-id", "other"],
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
    "assert sys.argv[5] == '--jq' and sys.argv[6] in " + repr([module.PR_FIELDS, module.COMMIT_FIELDS]) + "\n"
    "assert url.startswith('https://api.github.com/repos/acme/widgets/')\n"
    "if url.endswith('/pulls/7'):\n"
    "  value=" + repr(dict(pr, body="x" * 100_000)) + "\n"
    "  print(json.dumps({k:value[k] for k in ('number','base','head','state','merged','merged_at','merge_commit_sha','merged_at_present','merge_commit_sha_present')}))\n"
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
                          "--ledger", str(ledger), "--key-file", str(key_file), "--case-id", "case-1"],
                         env=env, capture_output=True, text=True, check=False, timeout=25)
assert success.returncode == 0 and not success.stderr
output = json.loads(success.stdout)
assert output["classification"] == "MERGE_OBSERVED_IN_GITHUB"
assert output["cohort_delivery_credit"] is False and output["policy_compliance"] == "UNMEASURED"
assert "association authenticity UNVERIFIED" in output["source"]
assert len(output["ledger_identity_hmac"]) == 64 and output["observed_at"].endswith("Z")
assert "case-1" not in success.stdout and "acme/widgets" not in success.stdout
env["GH_HOST"] = "other.example"
wrong_host = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--mapping", str(private),
                             "--ledger", str(ledger), "--key-file", str(key_file), "--case-id", "case-1"],
                            env=env, capture_output=True, text=True, check=False, timeout=25)
assert wrong_host.returncode == 3 and "UNVERIFIED" in wrong_host.stderr and not wrong_host.stdout
# Failure-mode stub variants: none may return success JSON. The subprocess
# calling the CLI has its OWN timeout, so a hanging implementation goes red
# instead of hanging the test suite indefinitely.
env.pop("GH_HOST")


def failure_stub(body):
    stub.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    stub.chmod(0o700)
    attempted = subprocess.run([sys.executable, "-I", "-B", str(SCRIPT), "--mapping", str(private),
                                 "--ledger", str(ledger), "--key-file", str(key_file), "--case-id", "case-1"], env=env, capture_output=True, text=True,
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
                            "--ledger", str(ledger), "--key-file", str(key_file), "--case-id", "case-1"], env=env, capture_output=True, text=True,
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
