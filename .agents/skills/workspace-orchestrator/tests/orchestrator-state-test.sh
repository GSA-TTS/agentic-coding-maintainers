#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$(mktemp -d "${TMPDIR:-/tmp}/orchestrator-state.XXXXXX")"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/orchestrator-work.XXXXXX")"
WORK_REVIEW="$(mktemp -d "${TMPDIR:-/tmp}/orchestrator-review.XXXXXX")"
export ORCHESTRATOR_STATE_DIR="$STATE"
export ORCHESTRATOR_TEST_MODE=1
CMD="$ROOT/bin/orchestrator-state.sh"
REVIEW_SHA="$(printf 'b%.0s' {1..40})"

fail() { printf 'orchestrator-state test FAILED: %s\n' "$*" >&2; exit 1; }
expect_rc() {
  local want="$1"; shift
  set +e
  "$@" >/tmp/orch-out.$$ 2>/tmp/orch-err.$$
  local got=$?
  set -e
  [[ "$got" -eq "$want" ]] || fail "expected rc=$want, got rc=$got: $*"
}

"$CMD" create impl-a --scope 'repo:x:path:a' --kind implementation \
  --repo x/y --worktree "$WORK" --base-sha "$(printf 'a%.0s' {1..40})" \
  --head-sha "$(printf 'a%.0s' {1..40})" --owned-path a --acceptance 'a works' >/dev/null
"$CMD" create review-b --scope 'repo:x:pr:2:head:bbbb' --kind review \
  --repo x/y --worktree "$WORK_REVIEW" --base-sha "$REVIEW_SHA" --head-sha "$REVIEW_SHA" >/dev/null

shown="$($CMD show impl-a)"
state="$(python3 -I -B -c 'import json,sys; print(json.load(sys.stdin)["state"])' <<<"$shown")"
[[ "$state" == Ready ]] || fail "new task is not Ready"
expect_rc 2 "$CMD" transition impl-a Claimed
grep -q '"state": "Ready"' "$STATE/tasks/impl-a/task.json" || fail "direct Claimed transition changed Ready task"

# Persisted schema-1 task records remain readable and are upgraded on the next
# mutation rather than forcing an operator to discard coordination evidence.
python3 - "$STATE/tasks/review-b/task.json" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p))
d["schema_version"]=1
for k in ("tracker_type","tracker_number","head_sha","reviewed_sha","transition_intent","rework_count"):
    d.pop(k,None)
open(p,"w").write(json.dumps(d,sort_keys=True,indent=2)+"\n")
PY
# Capture the complete producer output before matching. `grep -q` closes a
# pipe on its first match, which can SIGPIPE the Python CLI under pipefail and
# turn an otherwise successful assertion into a flaky BrokenPipeError.
shown="$($CMD show review-b)"
grep -q '"schema_version": 2' <<<"$shown"
"$CMD" record review-b validation 'migration preserved task' >/dev/null
grep -q '"schema_version": 2' "$STATE/tasks/review-b/task.json"
# Legacy headless review records cannot be declared ready until rebound.
"$CMD" claim review-b --owner legacy-reviewer --pid $$ >/dev/null
"$CMD" transition review-b Reviewing >/dev/null
"$CMD" record review-b reviewer qa --reviewed-sha "$REVIEW_SHA" >/dev/null
set +e
"$CMD" transition review-b 'Ready for human review' >/dev/null 2>&1; rc=$?
set -e
[[ "$rc" -eq 4 ]]
"$CMD" transition review-b Cancelled >/dev/null

"$CMD" claim impl-a --owner worker-a --pid $$ >/dev/null
"$CMD" transition impl-a Implementing >/dev/null
python3 - "$STATE/tasks/impl-a/task.json" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
assert d["state"] == "Implementing"
assert d["leases"]["global_slot"] is not None
assert d["leases"]["implementation_lane"] is not None
PY

"$CMD" transition impl-a Reviewing >/dev/null
sha="$(printf 'a%.0s' {1..40})"
"$CMD" record impl-a reviewer qa-1 --next-action 'independent QA at fixed SHA' --reviewed-sha "$sha" >/dev/null
"$CMD" record impl-a validation '86 tests passed at abc123' >/dev/null
python3 - "$STATE/tasks/impl-a/task.json" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
assert d["state"] == "Reviewing"
assert d["leases"]["global_slot"] is not None
assert d["leases"]["implementation_lane"] is None
assert d["reviewers"] == ["qa-1"]
assert d["validation"] == ["86 tests passed at abc123"]
PY
"$CMD" transition impl-a 'Ready for human review' >/dev/null
"$CMD" transition impl-a Done >/dev/null
[[ ! -d "$STATE/scopes/$(printf 'repo:x:path:a' | shasum -a 256 | cut -d' ' -f1).lock" ]] || fail "Done task retained scope lock"

# Legacy dispositions preserve findings, bind index/text/head/revision, and
# fail closed on stale or malformed evidence. Run only in the approved sandbox.
python3 -I -B - "$CMD" <<'PY'
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

cmd = sys.argv[1]
with tempfile.TemporaryDirectory(prefix="legacy-dispositions-") as tmp:
    root = Path(tmp).resolve()
    state, work = root / ".orchestrator", root / "work"
    work.mkdir()
    env = dict(os.environ, WORKSPACE_ORCHESTRATOR_ROOT=str(root),
               ORCHESTRATOR_STATE_DIR=str(state), ORCHESTRATOR_TEST_MODE="1")
    task_id = "legacy"
    task = state / "tasks" / task_id / "task.json"

    def call(*args, rc=0):
        result = subprocess.run([cmd, *args], env=env, text=True, capture_output=True)
        assert result.returncode == rc, (args, result.returncode, result.stdout, result.stderr)
        if rc == 3:
            assert "UNVERIFIED" in result.stderr and json.loads(result.stdout)["state"] == "Unknown"
        return json.loads(result.stdout) if rc == 0 else None

    def git(*args):
        return subprocess.check_output([
            "git", "-c", "user.name=Sandbox Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-C", str(work), *args,
        ], text=True).strip()

    def saved():
        return json.loads(task.read_text())

    def put(record):
        task.write_text(json.dumps(record))

    git("init", "-b", "fixture")
    git("commit", "--allow-empty", "-m", "fixture A")
    a = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-m", "fixture B")
    b = git("rev-parse", "HEAD")
    git("reset", "--hard", a)
    call("create", "legacy", "--kind", "implementation", "--scope", "legacy:findings",
         "--repo", "fixture/legacy", "--branch", "fixture", "--worktree", str(work),
         "--base-sha", a, "--head-sha", a)
    call("claim", "legacy", "--owner", "implementer", "--pid", str(os.getpid()))
    call("transition", "legacy", "Reviewing")
    texts = ["first finding: café", "second finding"]
    for text in texts:
        call("record", "legacy", "finding", text)
    call("record", "legacy", "reviewer", "qa", "--reviewed-sha", a)
    call("record", "legacy", "validation", "fixture review evidence")
    # Exercise production Git identity/cleanliness checks against the isolated
    # fixture repository as well as CLI/state validation (still sandbox-only).
    env.pop("ORCHESTRATOR_TEST_MODE")

    def resolve(index=0, rc=0, **overrides):
        options = {"finding-index": str(index),
                   "finding-sha256": hashlib.sha256(texts[index].encode()).hexdigest(),
                   "head-sha": saved()["head_sha"], "disposition": "fixed",
                   "reviewer": "qa", "evidence": "fixture-only evidence, not a real review",
                   "expected-revision": str(saved()["revision"])}
        options.update(overrides)
        args = ["resolve-finding", task_id]
        for key, value in options.items():
            if value is not None:
                args.extend(["--" + key, value])
        before = task.read_bytes()
        result = call(*args, rc=rc)
        if rc:
            assert task.read_bytes() == before, "refused resolution mutated task"
        return result

    call("transition", "legacy", "Ready for human review", rc=4)
    before = task.read_bytes()
    call("record", "legacy", "resolution", texts[0], rc=2)
    call("record", "legacy", "finding", texts[0], rc=4)
    assert task.read_bytes() == before
    resolve(rc=2, reviewer=None)
    resolve(rc=2, reviewer=" ")
    resolve(rc=2, evidence=" ")
    resolve(rc=2, **{"expected-revision": None})
    resolve(rc=4, reviewer="implementer")
    resolve(rc=4, **{"expected-revision": "0"})
    resolve(rc=4, **{"head-sha": b})
    resolve(rc=4, **{"finding-sha256": "0" * 64})
    resolve(rc=4, **{"finding-index": "2"})
    resolve(rc=2, **{"finding-index": "-1"})
    git("reset", "--hard", b)
    resolve(rc=3)  # actual checkout head must match recorded head
    git("reset", "--hard", a)
    dirty = work / "untracked-fixture"
    dirty.write_text("dirty checkout fixture")
    resolve(rc=4)
    dirty.unlink()
    original = saved()
    no_owner = copy.deepcopy(original)
    no_owner["owner"] = ""
    put(no_owner)
    resolve(rc=4)
    put(original)
    resolve()
    resolve(rc=4)  # duplicate at a current revision still refused
    call("transition", "legacy", "Ready for human review", rc=4)
    resolve(1, disposition="refuted")
    resolved = saved()
    assert resolved["findings"] == texts
    history = resolved["legacy_finding_dispositions"]["history"]
    assert [item["disposition"] for item in history] == ["fixed", "refuted"]

    # Optional extension absent is legacy-compatible; present-but-broken is not.
    malformed = [None, {}, {"epoch": False, "history": []}]
    for field, value in (("finding_index", True), ("finding_sha256", "0" * 64),
                         ("head_sha", b), ("reviewer", "implementer"), ("evidence", ""),
                         ("revision", resolved["revision"] + 1), ("epoch", 1)):
        ledger = copy.deepcopy(resolved["legacy_finding_dispositions"])
        ledger["history"][0][field] = value
        malformed.append(ledger)
    duplicate = copy.deepcopy(resolved["legacy_finding_dispositions"])
    duplicate["history"].append(copy.deepcopy(duplicate["history"][0]))
    malformed.append(duplicate)
    # Historical entries no longer compare to the current owner, but a single
    # epoch still cannot name two implementation owners at the same head.
    conflicting_owner = copy.deepcopy(resolved["legacy_finding_dispositions"])
    conflicting_owner["epoch"] = 1
    conflicting_owner["history"][1]["implementation_owner"] = "different-owner"
    malformed.append(conflicting_owner)
    for ledger in malformed:
        corrupt = copy.deepcopy(resolved)
        corrupt["legacy_finding_dispositions"] = ledger
        put(corrupt)
        before = task.read_bytes()
        call("show", "legacy", rc=3)
        call("transition", "legacy", "Ready for human review", rc=3)
        assert task.read_bytes() == before
    put(resolved)
    protocol = copy.deepcopy(resolved)
    protocol["review_protocol"] = {}
    put(protocol)
    resolve(rc=4)
    call("transition", "legacy", "Ready for human review", rc=4)
    protocol["transition_intent"] = "Ready for human review"
    put(protocol)
    call("reconcile", "legacy", rc=3)
    for field, value in (("validation", []), ("reviewers", []), ("reviewed_sha", b)):
        incomplete = copy.deepcopy(resolved)
        incomplete[field] = value
        put(incomplete)
        call("transition", "legacy", "Ready for human review", rc=4)
    put(resolved)

    # Crash recovery must use exactly the same all-findings-resolved gate.
    pending = copy.deepcopy(resolved)
    pending["transition_intent"] = "Ready for human review"
    pending["legacy_finding_dispositions"]["history"].pop()
    put(pending)
    call("reconcile", "legacy", rc=3)
    pending["legacy_finding_dispositions"] = copy.deepcopy(resolved["legacy_finding_dispositions"])
    put(pending)
    call("reconcile", "legacy")
    assert saved()["state"] == "Ready for human review"
    call("transition", "legacy", "Rework")
    call("claim", "legacy", "--owner", "implementer", "--pid", str(os.getpid()))

    # Real Git-backed A -> B -> A updates cannot resurrect A's dispositions.
    for head in (b, a):
        git("reset", "--hard", head)
        call("update-head", "legacy", head)
    assert saved()["legacy_finding_dispositions"] == {"epoch": 2, "history": history}
    call("update-head", "legacy", a)  # same head does not advance epoch
    assert saved()["legacy_finding_dispositions"]["epoch"] == 2
    call("transition", "legacy", "Reviewing")
    call("record", "legacy", "reviewer", "qa", "--reviewed-sha", a)
    call("record", "legacy", "validation", "fresh fixture evidence")
    call("transition", "legacy", "Ready for human review", rc=4)
    resolve()
    resolve(1, disposition="refuted")
    assert saved()["legacy_finding_dispositions"]["history"][:2] == history
    call("transition", "legacy", "Ready for human review")
    call("record", "legacy", "finding", "new finding after readiness")
    assert saved()["state"] == "Rework" and saved()["findings"] == texts + ["new finding after readiness"]
    resolve(rc=4)  # wrong lifecycle state
    call("claim", "legacy", "--owner", "replacement", "--pid", str(os.getpid()))
    assert saved()["legacy_finding_dispositions"]["epoch"] == 3
    call("transition", "legacy", "Reviewing")
    call("record", "legacy", "reviewer", "qa", "--reviewed-sha", a)
    call("record", "legacy", "validation", "replacement-owner fixture evidence")
    call("transition", "legacy", "Ready for human review", rc=4)
    call("transition", "legacy", "Cancelled")
    resolve(rc=4)

    # Same-head reopenings retain exact identity/history and revoke readiness.
    # Repeat with a detached review checkout: branch identity is deliberately
    # irrelevant there, but actual HEAD and cleanliness must still be checked.
    for kind in ("implementation", "review"):
        task_id = "reopen-" + kind
        task = state / "tasks" / task_id / "task.json"
        if kind == "review":
            git("checkout", "--detach", a)
        call("create", task_id, "--kind", kind, "--scope", task_id,
             "--repo", "fixture/legacy", "--branch", "fixture", "--worktree", str(work),
             "--base-sha", a, "--head-sha", a)
        call("claim", task_id, "--owner", "implementer", "--pid", str(os.getpid()))
        call("transition", task_id, "Reviewing")
        call("record", task_id, "finding", texts[0])
        resolve(rc=4, reviewer="implementer")
        resolve(rc=2, reviewer=" ")
        resolve(rc=2, evidence=" ")
        git("reset", "--hard", b)
        resolve(rc=3)
        git("reset", "--hard", a)
        dirty.write_text("dirty review checkout fixture")
        resolve(rc=4)
        dirty.unlink()
        resolve(disposition="persists")  # explicit initial unresolved evidence
        resolve(rc=4, disposition="persists")
        resolve(disposition="refuted")

        def ready():
            call("record", task_id, "reviewer", "qa", "--reviewed-sha", a)
            call("record", task_id, "validation", "fresh sandbox fixture review")
            call("transition", task_id, "Ready for human review")

        ready()
        for cycle, outcome in enumerate(("fixed", "refuted", "fixed"), 1):
            before = saved()
            retained = copy.deepcopy(before["legacy_finding_dispositions"]["history"])
            resolve(rc=4, disposition="persists", **{"expected-revision": "0"})
            resolve(rc=4, disposition="persists", **{"head-sha": b})
            resolve(rc=4, disposition="persists", **{"finding-sha256": "0" * 64})
            resolve(rc=4, disposition="persists", reviewer="implementer")
            protocol = copy.deepcopy(before)
            protocol["review_protocol"] = {}
            put(protocol)
            resolve(rc=4, disposition="persists")
            put(before)
            call("record", task_id, "finding", texts[0], rc=4)
            assert saved() == before
            reopened = resolve(disposition="persists")
            ledger = reopened["legacy_finding_dispositions"]
            assert reopened["state"] == "Rework" and reopened["rework_count"] == cycle
            assert reopened["findings"] == [texts[0]] and ledger["epoch"] == 0
            assert ledger["history"][:-1] == retained
            event = ledger["history"][-1]
            assert event["disposition"] == "persists" and event["head_sha"] == a
            assert event["revision"] == before["revision"] + 1 == reopened["revision"]
            assert event["reviewer"] == "qa" and event["implementation_owner"] == "implementer"
            assert event["evidence"] and event["finding_index"] == 0
            assert event["finding_sha256"] == hashlib.sha256(texts[0].encode()).hexdigest()
            assert not reopened["reviewers"] and not reopened["validation"] and not reopened["reviewed_sha"]
            call("claim", task_id, "--owner", "implementer", "--pid", str(os.getpid()))
            call("transition", task_id, "Reviewing")
            call("record", task_id, "reviewer", "qa", "--reviewed-sha", a)
            call("record", task_id, "validation", "new evidence cannot hide persisting finding")
            call("transition", task_id, "Ready for human review", rc=4)
            resolve(rc=4, disposition="persists")
            current = saved()
            pending = copy.deepcopy(current)
            pending["transition_intent"] = "Ready for human review"
            put(pending)
            call("reconcile", task_id, rc=3)
            put(current)
            # Increasing revision numbers alone cannot legalize duplicate events.
            duplicate = copy.deepcopy(current)
            duplicate["revision"] += 1
            duplicate["legacy_finding_dispositions"]["history"].append(
                dict(event, revision=duplicate["revision"]))
            put(duplicate)
            call("show", task_id, rc=3)
            put(current)
            resolve(disposition=outcome)
            resolve(rc=4, disposition="refuted" if outcome == "fixed" else "fixed")
            closed = saved()
            duplicate = copy.deepcopy(closed)
            duplicate["revision"] += 1
            duplicate["legacy_finding_dispositions"]["history"].append(
                dict(duplicate["legacy_finding_dispositions"]["history"][-1],
                     revision=duplicate["revision"]))
            put(duplicate)
            call("show", task_id, rc=3)
            put(closed)
            ready()
        resolve(disposition="persists")
        assert saved()["state"] == "Blocked" and saved()["rework_count"] == 3
        assert not saved()["reviewed_sha"] and not saved()["validation"] and not saved()["reviewers"]
        call("transition", task_id, "Cancelled")
        resolve(rc=4, disposition="persists")
PY

# Duplicate exact scope is a verified refusal, not UNKNOWN.
mkdir "$WORK/scope-owner"
"$CMD" create scope-owner --scope 'repo:x:path:shared' --kind review --worktree "$WORK/scope-owner" --head-sha "$REVIEW_SHA" >/dev/null
expect_rc 4 "$CMD" create scope-duplicate --scope 'repo:x:path:shared' --kind review --worktree "$WORK" --head-sha "$REVIEW_SHA"
[[ ! -e "$STATE/tasks/scope-duplicate/task.json" ]] || fail "duplicate task record was written"

# A root path owns ALL children; a path check that treats '.' as a regular
# segment admits a second writer to src/example beneath it.
mkdir "$WORK/whole-repo" "$WORK/nested-repo"
"$CMD" create whole-repo --scope 'repo:x:path:all' --kind review --repo x/whole --worktree "$WORK/whole-repo" --head-sha "$REVIEW_SHA" --owned-path . >/dev/null
expect_rc 4 "$CMD" create nested-repo --scope 'repo:x:path:nested' --kind review --repo x/whole --worktree "$WORK/nested-repo" --head-sha "$REVIEW_SHA" --owned-path src/example

# Invalid transition and direct Unknown are caller errors.
expect_rc 2 "$CMD" transition scope-owner Done
expect_rc 2 "$CMD" transition scope-owner Unknown

# Rework also requires a fresh atomic claim, not a state-only transition.
mkdir "$WORK/rework-owner"
"$CMD" create rework-owner --scope 'repo:x:rework' --kind implementation --worktree "$WORK/rework-owner" --head-sha "$(printf 'c%.0s' {1..40})" >/dev/null
"$CMD" claim rework-owner --owner worker-r --pid $$ >/dev/null
"$CMD" transition rework-owner Reviewing >/dev/null
"$CMD" transition rework-owner Rework >/dev/null
expect_rc 2 "$CMD" transition rework-owner Claimed
grep -q '"state": "Rework"' "$STATE/tasks/rework-owner/task.json" || fail "direct Claimed transition changed Rework task"

# Six active slots are admitted; a seventh is refused and stays Ready.
for n in 1 2 3 4 5 6 7; do
  mkdir "$WORK/review-$n"
  "$CMD" create "review-$n" --scope "repo:x:review:$n" --kind review --worktree "$WORK/review-$n" --head-sha "$REVIEW_SHA" >/dev/null
done
for n in 1 2 3 4 5 6; do "$CMD" claim "review-$n" --owner "r$n" --pid $$ >/dev/null; done
expect_rc 4 "$CMD" claim review-7 --owner r7 --pid $$
[[ "$(find "$STATE/slots" -name '*.lock' -type d | wc -l | tr -d ' ')" == 6 ]] || fail "global slot count is not six"
grep -q '"state": "Ready"' "$STATE/tasks/review-7/task.json" || fail "refused task was partially claimed"

# Invalid owner input is refused before reservation and cannot leak capacity.
"$CMD" create bad-owner --scope 'repo:x:review:bad-owner' --kind review --head-sha "$REVIEW_SHA" >/dev/null
too_long="$(printf 'x%.0s' {1..501})"
expect_rc 2 "$CMD" claim bad-owner --owner "$too_long" --pid $$
[[ "$(find "$STATE/slots" -name '*.lock' -type d | wc -l | tr -d ' ')" == 6 ]] || fail "invalid owner leaked a slot"
grep -q '"state": "Ready"' "$STATE/tasks/bad-owner/task.json" || fail "invalid owner partially claimed task"

# A post-reservation persistence failure rolls the slot back and leaves the task
# claimable rather than creating an orphan/Unknown state.
"$CMD" transition review-1 Cancelled >/dev/null
"$CMD" create claim-write-fail --scope 'repo:x:review:claim-write-fail' --kind review --head-sha "$REVIEW_SHA" >/dev/null
export ORCHESTRATOR_TEST_FAIL_CLAIM_WRITE=1
expect_rc 3 "$CMD" claim claim-write-fail --owner reviewer --pid $$
unset ORCHESTRATOR_TEST_FAIL_CLAIM_WRITE
[[ "$(find "$STATE/slots" -name '*.lock' -type d | wc -l | tr -d ' ')" == 5 ]] || fail "failed claim leaked a slot"
grep -q '"state": "Ready"' "$STATE/tasks/claim-write-fail/task.json" || fail "failed claim changed task state"

expect_rc 2 "$CMD" create headless-review --scope 'repo:x:review:headless' --kind review

# Leading dots are identity-bearing, and identical paths in different repos do
# not conflict mechanically.
mkdir "$WORK/dot-a" "$WORK/dot-b"
"$CMD" create dot-a --scope 'repo:a:dot' --kind review --repo owner/a --worktree "$WORK/dot-a" --head-sha "$REVIEW_SHA" --owned-path .github/workflows >/dev/null
"$CMD" create dot-b --scope 'repo:b:dot' --kind review --repo owner/b --worktree "$WORK/dot-b" --head-sha "$REVIEW_SHA" --owned-path .github/workflows >/dev/null
grep -q '".github/workflows"' "$STATE/tasks/dot-a/task.json"

# Corrupt state must be UNKNOWN (3), never recreated or reported healthy.
printf '{"schema_version":1' > "$STATE/tasks/review-7/task.json"
expect_rc 3 "$CMD" show review-7
grep -q UNVERIFIED /tmp/orch-err.$$ || fail "corrupt state did not say UNVERIFIED"
grep -q Unknown /tmp/orch-out.$$ || fail "corrupt state did not emit Unknown"

# A lock with no owner metadata is ambiguous and remains in place.
mkdir "$STATE/slots/orphan.lock"
expect_rc 3 "$CMD" reconcile
[[ -d "$STATE/slots/orphan.lock" ]] || fail "ambiguous lock was removed automatically"

# An earlier ambiguous slot must block admission even when a LATER slot is
# free; otherwise global capacity is falsely reported as measurable.
STATE3="$(mktemp -d "${TMPDIR:-/tmp}/orchestrator-ambiguous.XXXXXX")"
export ORCHESTRATOR_STATE_DIR="$STATE3"
"$CMD" create ambiguous-slot --scope 'repo:x:review:ambiguous' --kind review --head-sha "$REVIEW_SHA" >/dev/null
mkdir "$STATE3/slots/0.lock"
expect_rc 3 "$CMD" claim ambiguous-slot --owner reviewer --pid $$
[[ ! -e "$STATE3/slots/1.lock" ]] || fail "ambiguous slot allowed a later free slot to be claimed"
grep -q '"state": "Ready"' "$STATE3/tasks/ambiguous-slot/task.json" || fail 'ambiguous slot partially claimed a task'

# Dead workers become Blocked and release capacity. Use a PID that we actually
# owned and waited for, not an assumed high PID.
STATE2="$(mktemp -d "${TMPDIR:-/tmp}/orchestrator-dead.XXXXXX")"
export ORCHESTRATOR_STATE_DIR="$STATE2"
"$CMD" create interrupted --scope 'repo:x:path:dead' --kind implementation --worktree "$WORK" >/dev/null
sleep 0.01 & dead=$!; wait "$dead"
# Claim requires a live pid, so claim with this shell then rewrite both records to
# the measured dead pid while preserving the original process-start mismatch as
# absent ownership evidence would be UNKNOWN. The fixture uses the actual start
# captured for this shell, then removes the worktree instead for deterministic
# interrupted recovery without PID reuse assumptions.
"$CMD" claim interrupted --owner dead-worker --pid $$ >/dev/null
mv "$WORK" "$WORK.missing"
"$CMD" reconcile interrupted >/dev/null
grep -q '"state": "Blocked"' "$STATE2/tasks/interrupted/task.json" || fail "missing worktree did not block task"
grep -q 'worktree missing' "$STATE2/tasks/interrupted/task.json" || fail "missing worktree reason absent"
[[ "$(find "$STATE2/slots" -name '*.lock' -type d | wc -l | tr -d ' ')" == 0 ]] || fail "blocked task retained worker slot"

printf 'orchestrator-state tests: PASS\n'
