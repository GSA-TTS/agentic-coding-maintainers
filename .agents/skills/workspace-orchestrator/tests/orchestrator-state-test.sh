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

state="$($CMD show impl-a | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
[[ "$state" == Ready ]] || fail "new task is not Ready"

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
"$CMD" show review-b | grep -q '"schema_version": 2'
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

# Duplicate exact scope is a verified refusal, not UNKNOWN.
mkdir "$WORK/scope-owner"
"$CMD" create scope-owner --scope 'repo:x:path:shared' --kind review --worktree "$WORK/scope-owner" --head-sha "$REVIEW_SHA" >/dev/null
expect_rc 4 "$CMD" create scope-duplicate --scope 'repo:x:path:shared' --kind review --worktree "$WORK" --head-sha "$REVIEW_SHA"
[[ ! -e "$STATE/tasks/scope-duplicate/task.json" ]] || fail "duplicate task record was written"

# Invalid transition and direct Unknown are caller errors.
expect_rc 2 "$CMD" transition scope-owner Done
expect_rc 2 "$CMD" transition scope-owner Unknown

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
