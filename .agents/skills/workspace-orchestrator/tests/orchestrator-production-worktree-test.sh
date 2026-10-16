#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Git hooks export repository-local GIT_* variables (especially GIT_INDEX_FILE).
# `git -C <fixture>` does not override all of them, so clear the complete local
# set before any fixture Git operation.
while IFS= read -r name; do unset "$name"; done < <(git rev-parse --local-env-vars)
CONSUMER="$(mktemp -d "${TMPDIR:-/tmp}/orchestrator-production.XXXXXX")"
REPO="$CONSUMER/source"
WORKTREE="$CONSUMER/work/task-one"
export WORKSPACE_ORCHESTRATOR_ROOT="$CONSUMER"
unset ORCHESTRATOR_TEST_MODE ORCHESTRATOR_STATE_DIR
CMD="$ROOT/bin/orchestrator-state.sh"
export HOME="$CONSUMER/home"
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
export MISE_DISABLE=1
mkdir -p "$HOME" "$CONSUMER/empty-template"

mkdir -p "$REPO" "$CONSUMER/work"
git -C "$REPO" init -q --template="$CONSUMER/empty-template"
git -C "$REPO" config user.name "Orchestrator Test"
git -C "$REPO" config user.email "orchestrator-test@example.invalid"
printf 'base\n' > "$REPO/example.txt"
git -C "$REPO" add example.txt
git -C "$REPO" commit -q -m 'test: base'
base="$(git -C "$REPO" rev-parse HEAD)"
git -C "$REPO" worktree add -q -b task/one "$WORKTREE" "$base"

"$CMD" create production-task --scope 'example/repo:path:example.txt' \
  --kind implementation --repo example/repo --branch task/one \
  --worktree "$WORKTREE" --base-sha "$base" --owned-path example.txt >/dev/null
"$CMD" claim production-task --owner test-worker --pid $$ >/dev/null
"$CMD" transition production-task Implementing >/dev/null
"$CMD" record production-task reviewer stale-reviewer --reviewed-sha "$base" >/dev/null
"$CMD" record production-task validation 'stale validation' >/dev/null
"$CMD" record production-task finding 'unresolved finding' >/dev/null

printf 'change\n' >> "$WORKTREE/example.txt"
git -C "$WORKTREE" add example.txt
git -C "$WORKTREE" commit -q -m 'test: implementation'
head="$(git -C "$WORKTREE" rev-parse HEAD)"
"$CMD" update-head production-task "$head" >/dev/null

python3 - "$CONSUMER/.orchestrator/tasks/production-task/task.json" "$head" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
assert d["head_sha"] == sys.argv[2]
assert d["reviewed_sha"] == ""
assert d["reviewers"] == []
assert d["validation"] == []
assert d["findings"] == ["unresolved finding"]
PY

"$CMD" record production-task resolution 'unresolved finding' >/dev/null

"$CMD" transition production-task Reviewing >/dev/null
"$CMD" record production-task reviewer qa-reviewer --reviewed-sha "$head" >/dev/null
"$CMD" record production-task validation 'production fixture passed' >/dev/null
"$CMD" transition production-task 'Ready for human review' >/dev/null
"$CMD" record production-task finding 'late correctness finding' >/dev/null
grep -q '"state": "Rework"' "$CONSUMER/.orchestrator/tasks/production-task/task.json"
grep -q 'late correctness finding' "$CONSUMER/.orchestrator/tasks/production-task/task.json"

# A finding after the third rework blocks/escalates instead of overflowing the
# schema and leaving the task falsely ready.
python3 - "$CONSUMER/.orchestrator/tasks/production-task/task.json" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d["state"]="Ready for human review"; d["rework_count"]=3
open(p,"w").write(json.dumps(d,sort_keys=True,indent=2)+"\n")
PY
"$CMD" record production-task finding 'fourth-cycle finding' >/dev/null
grep -q '"state": "Blocked"' "$CONSUMER/.orchestrator/tasks/production-task/task.json"
grep -q 'three rework cycles reached' "$CONSUMER/.orchestrator/tasks/production-task/task.json"

# A subdirectory of a worktree is not accepted as the assigned worktree root.
mkdir "$WORKTREE/subdir"
set +e
"$CMD" create bad-root --scope 'example/repo:path:subdir' --kind implementation \
  --repo example/repo --branch task/one --worktree "$WORKTREE/subdir" \
  --base-sha "$base" --owned-path subdir >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]]

# Transition-time identity checks reject unrecorded branch/head drift.
git -C "$REPO" worktree add -q -b task/tamper "$CONSUMER/work/tamper" "$base"
"$CMD" create tamper-task --scope 'example/repo:path:tamper' --kind implementation \
  --repo example/repo --branch task/tamper --worktree "$CONSUMER/work/tamper" \
  --base-sha "$base" --owned-path tamper >/dev/null
"$CMD" claim tamper-task --owner test-worker --pid $$ >/dev/null
printf drift >> "$CONSUMER/work/tamper/example.txt"
git -C "$CONSUMER/work/tamper" add example.txt
git -C "$CONSUMER/work/tamper" commit -q -m 'test: unrecorded drift'
set +e
"$CMD" transition tamper-task Implementing >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 3 ]]
grep -q '"state": "Claimed"' "$CONSUMER/.orchestrator/tasks/tamper-task/task.json"

git -C "$REPO" worktree add -q -b task/path-swap "$CONSUMER/work/path-swap" "$base"
"$CMD" create path-swap-task --scope 'example/repo:path:path-swap' --kind implementation \
  --repo example/repo --branch task/path-swap --worktree "$CONSUMER/work/path-swap" \
  --base-sha "$base" --owned-path path-swap >/dev/null
"$CMD" claim path-swap-task --owner test-worker --pid $$ >/dev/null
mv "$CONSUMER/work/path-swap" "$CONSUMER/work/path-swap.real"
ln -s path-swap.real "$CONSUMER/work/path-swap"
set +e
"$CMD" transition path-swap-task Implementing >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 3 ]]
grep -q '"state": "Claimed"' "$CONSUMER/.orchestrator/tasks/path-swap-task/task.json"

printf 'orchestrator production worktree tests: PASS\n'
