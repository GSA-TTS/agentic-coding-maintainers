"""Offline synthetic GitHub observations; never call a real API in this test."""

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/observe-merge.py"
spec = importlib.util.spec_from_file_location("merge_observation", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
HEAD, MERGE = "a" * 40, "b" * 40
mapping = {"schema_version": 1, "case_id": "case-1", "repository": "acme/widgets", "number": 7, "head_sha": HEAD}
pr = {"number": 7, "base": {"repo": {"full_name": "acme/widgets"}}, "head": {"sha": HEAD},
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
unmerged = dict(pr, merged=False, merged_at=None, merge_commit_sha=None)
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
print("observe-merge tests: PASS")
print("observe_merge_fixture=" + str(fixture), file=sys.stderr)
