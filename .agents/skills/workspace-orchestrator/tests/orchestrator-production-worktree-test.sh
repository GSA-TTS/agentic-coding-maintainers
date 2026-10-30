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
# A clean checkout may contain an uninitialized submodule. Add a gitlink
# directly so the fixture remains offline and never executes nested Git config.
GITLINK_REPO="$CONSUMER/gitlink-source"
mkdir "$GITLINK_REPO"
git -C "$GITLINK_REPO" init -q --template="$CONSUMER/empty-template"
git -C "$GITLINK_REPO" config user.name "Orchestrator Test"
git -C "$GITLINK_REPO" config user.email orchestrator-test@example.invalid
printf 'nested\n' > "$GITLINK_REPO/nested.txt"
git -C "$GITLINK_REPO" add nested.txt
git -C "$GITLINK_REPO" commit -q -m 'test: nested fixture'
gitlink_head="$(git -C "$GITLINK_REPO" rev-parse HEAD)"
git -C "$WORKTREE" update-index --add --cacheinfo "160000,$gitlink_head,vendor/dependency"
git -C "$WORKTREE" commit -q -m 'test: add uninitialized gitlink'
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

"$CMD" transition production-task Reviewing >/dev/null
"$CMD" record production-task reviewer qa-reviewer --reviewed-sha "$head" >/dev/null
"$CMD" record production-task validation 'production fixture passed' >/dev/null
# Complete review fields alone cannot bypass the unresolved finding.
set +e
"$CMD" transition production-task 'Ready for human review' >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 4 ]]
shown="$("$CMD" show production-task)"
revision="$(python3 -I -B -c 'import json,sys; print(json.load(sys.stdin)["revision"])' <<<"$shown")"
finding_digest="$(python3 -I -B -c 'import hashlib,json,sys; print(hashlib.sha256(json.load(sys.stdin)["findings"][0].encode("utf-8")).hexdigest())' <<<"$shown")"
"$CMD" resolve-finding production-task --finding-index 0 \
  --finding-sha256 "$finding_digest" --head-sha "$head" \
  --expected-revision "$revision" --disposition fixed --reviewer qa-reviewer \
  --evidence 'Synthetic production fixture disposition; not an actual independent review' >/dev/null
python3 - "$CONSUMER/.orchestrator/tasks/production-task/task.json" "$head" "$revision" "$finding_digest" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
assert d["findings"] == ["unresolved finding"]
assert d["state"] == "Reviewing"
assert d["revision"] == int(sys.argv[3]) + 1
assert d["legacy_finding_dispositions"] == {"epoch": 0, "history": [{
    "finding_index": 0, "finding_sha256": sys.argv[4], "head_sha": sys.argv[2],
    "epoch": 0, "disposition": "fixed", "reviewer": "qa-reviewer",
    "implementation_owner": "test-worker",
    "evidence": "Synthetic production fixture disposition; not an actual independent review",
    "revision": int(sys.argv[3]) + 1,
}]}
PY
printf unreviewed > "$WORKTREE/untracked.txt"
set +e
"$CMD" transition production-task 'Ready for human review' >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 4 ]]
grep -q '"state": "Reviewing"' "$CONSUMER/.orchestrator/tasks/production-task/task.json"
rm "$WORKTREE/untracked.txt"
"$CMD" transition production-task 'Ready for human review' >/dev/null
"$CMD" record production-task finding 'late correctness finding' >/dev/null
grep -q '"state": "Rework"' "$CONSUMER/.orchestrator/tasks/production-task/task.json"
grep -q 'late correctness finding' "$CONSUMER/.orchestrator/tasks/production-task/task.json"
python3 - "$CONSUMER/.orchestrator/tasks/production-task/task.json" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
assert d["findings"] == ["unresolved finding", "late correctness finding"]
assert len(d["legacy_finding_dispositions"]["history"]) == 1
assert d["legacy_finding_dispositions"]["history"][0]["finding_index"] == 0
PY

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

# Production review tasks are bound to a real repository/worktree/head.
REVIEW_WORKTREE="$CONSUMER/work/review"
git -C "$REPO" worktree add -q --detach "$REVIEW_WORKTREE" "$head"
"$CMD" create fixed-review --scope 'example/repo:pr:1' --kind review \
  --repo example/repo --worktree "$REVIEW_WORKTREE" --head-sha "$head" >/dev/null
"$CMD" claim fixed-review --owner reviewer --pid $$ >/dev/null
"$CMD" transition fixed-review Reviewing >/dev/null
"$CMD" record fixed-review reviewer qa --reviewed-sha "$head" >/dev/null
"$CMD" record fixed-review validation 'fixed review evidence' >/dev/null
"$CMD" transition fixed-review 'Ready for human review' >/dev/null

# Populating a gitlink changes what the reviewer can read and must remain a
# verified dirty-checkout refusal without invoking Git inside the directory.
git -C "$REPO" worktree add -q --detach "$CONSUMER/work/dirty-gitlink-review" "$head"
mkdir -p "$CONSUMER/work/dirty-gitlink-review/vendor/dependency"
printf 'local content\n' > "$CONSUMER/work/dirty-gitlink-review/vendor/dependency/local.txt"
"$CMD" create dirty-gitlink-review --scope 'example/repo:pr:dirty-gitlink' --kind review \
  --repo example/repo --worktree "$CONSUMER/work/dirty-gitlink-review" --head-sha "$head" >/dev/null
"$CMD" claim dirty-gitlink-review --owner reviewer --pid $$ >/dev/null
set +e
"$CMD" transition dirty-gitlink-review Reviewing >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 4 ]]
grep -q '"state": "Claimed"' "$CONSUMER/.orchestrator/tasks/dirty-gitlink-review/task.json"

# An ignored file changes what a test or reviewer may read. The fixed-head
# readiness check must reject it, even though `git status` may omit it.
git -C "$REVIEW_WORKTREE" config --local core.excludesfile /dev/null
git -C "$REVIEW_WORKTREE" config --local core.fsmonitor false
git -C "$REPO" worktree add -q --detach "$CONSUMER/work/ignored-review" "$head"
"$CMD" create ignored-review --scope 'example/repo:pr:ignored' --kind review \
  --repo example/repo --worktree "$CONSUMER/work/ignored-review" --head-sha "$head" >/dev/null
"$CMD" claim ignored-review --owner reviewer --pid $$ >/dev/null
"$CMD" transition ignored-review Reviewing >/dev/null
"$CMD" record ignored-review reviewer qa --reviewed-sha "$head" >/dev/null
"$CMD" record ignored-review validation 'offline fixed-head fixture' >/dev/null
printf '*.scratch\n' > "$CONSUMER/work/ignored-review/.gitignore"
printf 'changed\n' > "$CONSUMER/work/ignored-review/local.scratch"
set +e
"$CMD" transition ignored-review 'Ready for human review' >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 4 ]]

set +e
"$CMD" create fabricated-review --scope 'example/repo:pr:2' --kind review \
  --repo example/repo --worktree "$REVIEW_WORKTREE" --head-sha "$(printf 'f%.0s' {1..40})" >/dev/null 2>&1
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

# An existing base object from unrelated history cannot anchor the initial diff.
git -C "$REPO" switch -q --orphan unrelated-base
git -C "$REPO" rm -q --ignore-unmatch -rf .
printf unrelated > "$REPO/unrelated.txt"
git -C "$REPO" add unrelated.txt
git -C "$REPO" commit -q -m 'test: unrelated base'
unrelated="$(git -C "$REPO" rev-parse HEAD)"
git -C "$REPO" switch -q main 2>/dev/null || git -C "$REPO" switch -q master
set +e
"$CMD" create unrelated-task --scope 'example/repo:path:unrelated' --kind implementation \
  --repo example/repo --branch task/one --worktree "$WORKTREE" \
  --base-sha "$unrelated" --owned-path unrelated >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]]

printf 'orchestrator production worktree tests: PASS\n'
