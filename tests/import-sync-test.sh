#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Keep fixture Git operations independent from pre-commit's repository-local
# environment (for example GIT_INDEX_FILE pointing at the outer repository).
while IFS= read -r name; do unset "$name"; done < <(git rev-parse --local-env-vars)
SOURCE="$(mktemp -d "${TMPDIR:-/tmp}/maintainers-import-source.XXXXXX")"
export HOME="$SOURCE-home"
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1
export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
export MISE_DISABLE=1
mkdir -p "$HOME" "$SOURCE-empty-template"
git -C "$SOURCE" init -q --template="$SOURCE-empty-template"
git -C "$SOURCE" config user.name "Import Test"
git -C "$SOURCE" config user.email "import-test@example.invalid"
mkdir -p "$SOURCE/bin" "$SOURCE/tests/fixtures/orchestrator-monitor-bin" "$SOURCE/docs" "$SOURCE/.opencode/agents"
for name in orchestrator-state.sh orchestrator-state.py orchestrator-monitor.sh orchestrator-monitor.py; do
  cp "$ROOT/.agents/skills/workspace-orchestrator/bin/$name" "$SOURCE/bin/$name"
done
for name in orchestrator-state-test.sh orchestrator-monitor-test.sh orchestrator-demo.sh; do
  cp "$ROOT/.agents/skills/workspace-orchestrator/tests/$name" "$SOURCE/tests/$name"
done
cp "$ROOT/.agents/skills/workspace-orchestrator/tests/fixtures/orchestrator-monitor-bin/gh" "$SOURCE/tests/fixtures/orchestrator-monitor-bin/gh"
cp "$ROOT/.agents/skills/workspace-orchestrator/docs/OPERATOR-GUIDE.md" "$SOURCE/docs/ORCHESTRATION.md"
cp "$ROOT/.agents/skills/workspace-orchestrator/profiles/opencode-v1/"*.md "$SOURCE/.opencode/agents/"
git -C "$SOURCE" add .
git -C "$SOURCE" commit -q -m 'test: source fixture'
printf dirty >> "$SOURCE/docs/ORCHESTRATION.md"

out="$("$ROOT/scripts/import-workspace-orchestrator.sh" "$SOURCE")"
staged="$(printf '%s\n' "$out" | sed -n 's/^STAGED=//p')"
[[ -f "$staged/SOURCE-SHA256SUMS" ]]
[[ -f "$staged/IMPORT-METADATA.json" ]]
grep -q 'SOURCE_DIRTY=true' <<<"$out"
(cd "$staged" && shasum -a 256 -c SOURCE-SHA256SUMS >/dev/null)
[[ "$(find "$staged/profiles/opencode-v1" -type f -name '*.md' | wc -l | tr -d ' ')" == 6 ]]

# Exact profile set and source path symlink checks fail closed.
printf extra > "$SOURCE/.opencode/agents/extra.md"
set +e; "$ROOT/scripts/import-workspace-orchestrator.sh" "$SOURCE" >/dev/null 2>&1; rc=$?; set -e
[[ "$rc" -eq 3 ]]
rm "$SOURCE/.opencode/agents/extra.md"
mv "$SOURCE/docs" "$SOURCE/docs.real"; ln -s docs.real "$SOURCE/docs"
set +e; "$ROOT/scripts/import-workspace-orchestrator.sh" "$SOURCE" >/dev/null 2>&1; rc=$?; set -e
[[ "$rc" -eq 3 ]]
rm "$SOURCE/docs"; mv "$SOURCE/docs.real" "$SOURCE/docs"
mv "$SOURCE/tests/fixtures/orchestrator-monitor-bin" "$SOURCE/tests/fixtures/orchestrator-monitor-bin.real"
ln -s orchestrator-monitor-bin.real "$SOURCE/tests/fixtures/orchestrator-monitor-bin"
set +e; "$ROOT/scripts/import-workspace-orchestrator.sh" "$SOURCE" >/dev/null 2>&1; rc=$?; set -e
[[ "$rc" -eq 3 ]]
rm "$SOURCE/tests/fixtures/orchestrator-monitor-bin"
mv "$SOURCE/tests/fixtures/orchestrator-monitor-bin.real" "$SOURCE/tests/fixtures/orchestrator-monitor-bin"

consumer="$(mktemp -d "${TMPDIR:-/tmp}/maintainers-sync.XXXXXX")"
consumer="$(cd "$consumer" && pwd -P)"
printf '# consumer\n' > "$consumer/AGENTS.md"
mkdir -p "$consumer/.agents/skills/sibling"
printf keep > "$consumer/.agents/skills/sibling/KEEP"
"$ROOT/scripts/sync-agentic-workspace.sh" "$consumer" workspace-orchestrator >/dev/null
[[ -f "$consumer/.agents/skills/workspace-orchestrator/SKILL.md" ]]
[[ -f "$consumer/.agents/skills/sibling/KEEP" ]]
# Install the shipped command in a minimal consumer, which intentionally lacks
# maintainer-only root docs. Verify the actual sync output and portable contract;
# this is static command packaging evidence, not an LLM behavior assertion.
mkdir -p "$consumer/.opencode/commands"
cp "$consumer/.agents/skills/workspace-orchestrator/examples/commands/orchestrate-start.md" "$consumer/.opencode/commands/"
python3 -I -B - "$ROOT" "$consumer" <<'PY'
import pathlib
import sys

repo, consumer = (pathlib.Path(path).resolve() for path in sys.argv[1:])
skill = consumer / ".agents/skills/workspace-orchestrator"
installed = consumer / ".opencode/commands/orchestrate-start.md"
assert installed.read_bytes() == (skill / "examples/commands/orchestrate-start.md").read_bytes()
assert installed.read_bytes() == (repo / ".opencode/commands/orchestrate-start.md").read_bytes()
assert (skill / "docs/OPERATOR-GUIDE.md").is_file()
assert not (consumer / "docs/HUMAN-REVIEWED-DELIVERY.md").exists()
text = installed.read_text()
assert "If the\nconsumer repository contains `docs/HUMAN-REVIEWED-DELIVERY.md`" in text
assert "Its absence is expected in other consumers" in text
assert "shipped guide and applicable repository instructions" in text
# A consumer with optional local guidance retains it on a subsequent sync.
local = consumer / "docs/HUMAN-REVIEWED-DELIVERY.md"
local.parent.mkdir()
local.write_text("Consumer-owned delivery guidance.\n")
PY
expected_dirty=false
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=all -- .agents/skills/workspace-orchestrator)" ]] || expected_dirty=true
sync_out="$("$ROOT/scripts/sync-agentic-workspace.sh" "$consumer" workspace-orchestrator)"
grep -q "SOURCE_DIRTY=$expected_dirty" <<<"$sync_out"
outbox="$(sed -n 's/^DISPOSAL_OUTBOX=//p' <<<"$sync_out")"
[[ -n "$outbox" && -f "$outbox/MANIFEST.md" && -f "$outbox/previous/SKILL.md" ]]
[[ ! -e "$consumer/.agents/skills/.workspace-orchestrator.sync-lock" ]]
[[ ! -e "$consumer/.agents/skills/.workspace-orchestrator.sync-in-progress" ]]
[[ -d "$outbox/marker" && -d "$outbox/lock" ]]
[[ "$outbox" == "$consumer/tmp/cleanup/"* ]]
[[ -f "$outbox/manifest.json" && -d "$outbox/cleanup-lock" ]]
[[ ! -e "$consumer/deleteme" && ! -e "$consumer/tmp/cleanup/.lock" ]]
grep -q 'old consumer skill' "$outbox/MANIFEST.md"
grep -qx 'Consumer-owned delivery guidance.' "$consumer/docs/HUMAN-REVIEWED-DELIVERY.md"
cmp -s "$consumer/.opencode/commands/orchestrate-start.md" "$consumer/.agents/skills/workspace-orchestrator/examples/commands/orchestrate-start.md"

set +e
ln -s /tmp "$consumer/.agents/skills/cross-repo-epic"
"$ROOT/scripts/sync-agentic-workspace.sh" "$consumer" cross-repo-epic >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 3 ]]
rm "$consumer/.agents/skills/cross-repo-epic"

# A stale symlink inside the old selected skill is refused during cleanup and is
# never followed to mutate its target.
target="$(mktemp -d "${TMPDIR:-/tmp}/maintainers-sync-target.XXXXXX")"
printf keep > "$target/KEEP"
ln -s "$target" "$consumer/.agents/skills/workspace-orchestrator/stale-link"
printf original > "$consumer/.agents/skills/workspace-orchestrator/ORIGINAL"
set +e
"$ROOT/scripts/sync-agentic-workspace.sh" "$consumer" workspace-orchestrator >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 3 ]]
[[ -f "$target/KEEP" ]]
[[ -f "$consumer/.agents/skills/workspace-orchestrator/ORIGINAL" ]]
[[ -z "$(find "$consumer/.agents/skills" -maxdepth 1 \( -name '.workspace-orchestrator.previous.*' -o -name '.workspace-orchestrator.sync.*' -o -name '.workspace-orchestrator.sync-in-progress' -o -name '.workspace-orchestrator.sync-lock' \) -print)" ]]
find "$consumer/tmp/cleanup" -name MANIFEST.md -type f -print | grep -q .

# A pre-existing uncertain marker is not deleted by a later refused invocation.
mkdir "$consumer/.agents/skills/.cross-repo-epic.sync-in-progress"
printf 'prior-evidence\n' > "$consumer/.agents/skills/.cross-repo-epic.sync-in-progress/owner"
set +e
"$ROOT/scripts/sync-agentic-workspace.sh" "$consumer" cross-repo-epic >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 3 ]]
grep -q prior-evidence "$consumer/.agents/skills/.cross-repo-epic.sync-in-progress/owner"

# A PID-named pre-existing backup belongs to a prior recovery attempt. The
# refused invocation must not stage or consume it as if this run created it.
rm "$consumer/.agents/skills/workspace-orchestrator/stale-link"
set +e
collision_out="$(bash -c '
  set -eu
  collision="$2/.agents/skills/.workspace-orchestrator.previous.$$"
  mkdir "$collision"
  printf "prior recovery evidence\n" > "$collision/KEEP"
  printf "COLLISION=%s\n" "$collision"
  exec "$1/scripts/sync-agentic-workspace.sh" "$2" workspace-orchestrator
' fixture "$ROOT" "$consumer" 2>&1)"
rc=$?
set -e
collision="$(sed -n 's/^COLLISION=//p' <<<"$collision_out")"
[[ "$rc" -eq 3 && -f "$collision/KEEP" ]]
grep -Fq "sync backup already exists: $collision" <<<"$collision_out"
grep -qx 'prior recovery evidence' "$collision/KEEP"
outbox="$(sed -n 's/^DISPOSAL_OUTBOX=//p' <<<"$collision_out")"
[[ -d "$outbox/lock" && -d "$outbox/cleanup-lock" ]]
[[ ! -e "$outbox/previous" && ! -e "$outbox/stage" && ! -e "$outbox/marker" ]]
[[ -f "$consumer/.agents/skills/workspace-orchestrator/SKILL.md" ]]

# Git consumers must opt into the shared store before any skill/lock mutation.
git_consumer="$(mktemp -d "${TMPDIR:-/tmp}/maintainers-sync-git.XXXXXX")"
git_consumer="$(cd "$git_consumer" && pwd -P)"
git -C "$git_consumer" init -q --template="$SOURCE-empty-template"
git -C "$git_consumer" config user.name 'Sync Test'
git -C "$git_consumer" config user.email 'sync-test@example.invalid'
printf '# consumer\n' > "$git_consumer/AGENTS.md"
set +e
"$ROOT/scripts/sync-agentic-workspace.sh" "$git_consumer" cross-repo-epic >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 3 && ! -e "$git_consumer/.agents" && ! -e "$git_consumer/tmp" ]]
printf '/tmp/\n' > "$git_consumer/.gitignore"
git -C "$git_consumer" add .
git -C "$git_consumer" commit -qm 'test: consumer ignore policy'
# Redirection cannot bypass consumer policy or redirect canonical provenance.
sync_out="$(GIT_DIR=/missing GIT_WORK_TREE=/missing GIT_INDEX_FILE=/missing/index \
  "$ROOT/scripts/sync-agentic-workspace.sh" "$git_consumer" cross-repo-epic)"
outbox="$(sed -n 's/^DISPOSAL_OUTBOX=//p' <<<"$sync_out")"
[[ "$outbox" == "$git_consumer/tmp/cleanup/"* && -f "$outbox/MANIFEST.md" ]]
[[ ! -e "$git_consumer/deleteme" ]]

# Preserve an uncertain prior per-skill lock; only this invocation's root lock
# is moved to its new outbox when the sync is refused.
mkdir "$git_consumer/.agents/skills/.cross-repo-epic.sync-lock"
printf keep > "$git_consumer/.agents/skills/.cross-repo-epic.sync-lock/KEEP"
set +e
"$ROOT/scripts/sync-agentic-workspace.sh" "$git_consumer" cross-repo-epic >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 3 ]]
[[ -f "$git_consumer/.agents/skills/.cross-repo-epic.sync-lock/KEEP" ]]
[[ ! -e "$git_consumer/tmp/cleanup/.lock" ]]

# A prior marker is preserved even when no symlink short-circuits the sync.
mkdir "$git_consumer/.agents/skills/.workspace-orchestrator.sync-in-progress"
printf prior > "$git_consumer/.agents/skills/.workspace-orchestrator.sync-in-progress/owner"
set +e
"$ROOT/scripts/sync-agentic-workspace.sh" "$git_consumer" workspace-orchestrator >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 3 ]]
grep -qx prior "$git_consumer/.agents/skills/.workspace-orchestrator.sync-in-progress/owner"
[[ ! -e "$git_consumer/.agents/skills/.workspace-orchestrator.sync-lock" ]]

# Linked worktrees have a .git file, not a directory.
linked="$git_consumer-linked"
git -C "$git_consumer" worktree add -q -b fixture-linked "$linked"
"$ROOT/scripts/sync-agentic-workspace.sh" "$linked" cross-repo-epic >/dev/null
[[ -f "$linked/.agents/skills/cross-repo-epic/SKILL.md" && ! -e "$linked/deleteme" ]]

# HEAD paths remain protected even after staging their deletion.
printf keep > "$linked/tmp/tracked"
git -C "$linked" add -f tmp/tracked
git -C "$linked" commit -qm 'test: tracked tmp guard'
git -C "$linked" rm --cached -q tmp/tracked
set +e
"$ROOT/scripts/sync-agentic-workspace.sh" "$linked" workspace-orchestrator >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 3 && -f "$linked/tmp/tracked" ]]
[[ ! -e "$linked/.agents/skills/workspace-orchestrator" ]]

# Installation failure retains the existing rollback contract and outbox evidence.
rollback_consumer="$(mktemp -d "${TMPDIR:-/tmp}/maintainers-sync-rollback.XXXXXX")"
printf '# consumer\n' > "$rollback_consumer/AGENTS.md"
mkdir -p "$rollback_consumer/.agents/skills/cross-repo-epic"
printf original > "$rollback_consumer/.agents/skills/cross-repo-epic/ORIGINAL"
shim="$(mktemp -d "${TMPDIR:-/tmp}/maintainers-sync-shim.XXXXXX")"
cat > "$shim/mv" <<'SH'
#!/usr/bin/env bash
case "$1" in
  */.cross-repo-epic.sync.*) exit 1 ;;
esac
exec /bin/mv "$@"
SH
chmod +x "$shim/mv"
set +e
sync_out="$(PATH="$shim:$PATH" "$ROOT/scripts/sync-agentic-workspace.sh" "$rollback_consumer" cross-repo-epic)"
rc=$?
set -e
[[ "$rc" -eq 3 ]]
outbox="$(sed -n 's/^DISPOSAL_OUTBOX=//p' <<<"$sync_out")"
[[ -f "$rollback_consumer/.agents/skills/cross-repo-epic/ORIGINAL" ]]
grep -q 'rollback: RESTORED' "$outbox/MANIFEST.md"
[[ -d "$outbox/lock" && -d "$outbox/marker" && -d "$outbox/cleanup-lock" ]]
# The shim refuses disposal of that stage as well: preserve it, report failure.
grep -q 'disposal: FAILED_STAGE' "$outbox/MANIFEST.md"
find "$rollback_consumer/.agents/skills" -maxdepth 1 -name '.cross-repo-epic.sync.*' -type d -print | grep -q .

# An occupied destination during failed installation must not consume the backup.
cat > "$shim/mv" <<'SH'
#!/usr/bin/env bash
case "$1" in
  */.cross-repo-epic.sync.*)
    case "$2" in
      */cross-repo-epic) mkdir "$2"; printf conflict > "$2/CONFLICT"; exit 1 ;;
    esac ;;
esac
exec /bin/mv "$@"
SH
set +e
sync_out="$(PATH="$shim:$PATH" "$ROOT/scripts/sync-agentic-workspace.sh" "$rollback_consumer" cross-repo-epic)"
rc=$?
set -e
[[ "$rc" -eq 3 ]]
outbox="$(sed -n 's/^DISPOSAL_OUTBOX=//p' <<<"$sync_out")"
grep -q 'rollback: BLOCKED' "$outbox/MANIFEST.md"
[[ -f "$rollback_consumer/.agents/skills/cross-repo-epic/CONFLICT" ]]
find "$rollback_consumer/.agents/skills" -path '*/.cross-repo-epic.previous.*/ORIGINAL' -type f -print | grep -q .
[[ -d "$outbox/lock" && -d "$outbox/cleanup-lock" ]]

# Fail only the final shared-lock move, after a successful installation and
# manifest write. The record must be rewritten as failure, not stale success.
cat > "$shim/mv" <<'SH'
#!/usr/bin/env bash
if [[ "$1" == "$FAIL_ROOT_LOCK" ]]; then
  if [[ "${FAIL_MANIFEST_UPDATE:-false}" == true ]]; then
    : > "$FAIL_ROOT_LOCK/fail-manifest-update"
  fi
  exit 1
fi
exec /bin/mv "$@"
SH
lock_consumer="$(mktemp -d "${TMPDIR:-/tmp}/maintainers-sync-lock-failure.XXXXXX")"
lock_consumer="$(cd "$lock_consumer" && pwd -P)"
printf '# consumer\n' > "$lock_consumer/AGENTS.md"
set +e
sync_out="$(PATH="$shim:$PATH" FAIL_ROOT_LOCK="$lock_consumer/tmp/cleanup/.lock" \
  "$ROOT/scripts/sync-agentic-workspace.sh" "$lock_consumer" cross-repo-epic)"
rc=$?
set -e
[[ "$rc" -eq 3 ]]
outbox="$(sed -n 's/^DISPOSAL_OUTBOX=//p' <<<"$sync_out")"
[[ -d "$lock_consumer/tmp/cleanup/.lock" && ! -e "$outbox/cleanup-lock" ]]
[[ -d "$outbox/lock" && -d "$outbox/marker" ]]
[[ -f "$lock_consumer/.agents/skills/cross-repo-epic/SKILL.md" ]]
grep -q 'Outcome: INSTALLED; exit: 3; rollback: NOT_NEEDED; disposal: FAILED_CLEANUP_LOCK;' "$outbox/MANIFEST.md"
if grep -Eq 'exit: 0;|disposal: COMPLETE;' "$outbox/MANIFEST.md"; then
  echo 'stale success in shared-lock failure manifest' >&2
  exit 1
fi

# Also fail only the subsequent manifest rewrite; retain the shared lock and
# emit a fixed diagnostic rather than letting errexit hide the double failure.
cat > "$shim/cat" <<'SH'
#!/usr/bin/env bash
if [[ -f "$FAIL_ROOT_LOCK/fail-manifest-update" ]]; then
  exit 1
fi
exec /bin/cat "$@"
SH
chmod +x "$shim/cat"
double_consumer="$(mktemp -d "${TMPDIR:-/tmp}/maintainers-sync-double-failure.XXXXXX")"
double_consumer="$(cd "$double_consumer" && pwd -P)"
printf '# consumer\n' > "$double_consumer/AGENTS.md"
set +e
sync_out="$(PATH="$shim:$PATH" FAIL_ROOT_LOCK="$double_consumer/tmp/cleanup/.lock" FAIL_MANIFEST_UPDATE=true \
  "$ROOT/scripts/sync-agentic-workspace.sh" "$double_consumer" cross-repo-epic 2>&1)"
rc=$?
set -e
[[ "$rc" -eq 3 ]]
outbox="$(sed -n 's/^DISPOSAL_OUTBOX=//p' <<<"$sync_out")"
[[ -d "$double_consumer/tmp/cleanup/.lock" && ! -e "$outbox/cleanup-lock" ]]
grep -Fq 'UNVERIFIED: cleanup-lock move and failure-manifest update failed; manifest is not success authority; inspect retained root lock and outbox' <<<"$sync_out"

# Unsafe shared hierarchy is refused before .agents or any transaction lock.
for unsafe in tmp-link cleanup-link permissions; do
  unsafe_consumer="$(mktemp -d "${TMPDIR:-/tmp}/maintainers-sync-unsafe.XXXXXX")"
  printf '# consumer\n' > "$unsafe_consumer/AGENTS.md"
  case "$unsafe" in
    tmp-link) ln -s "$target" "$unsafe_consumer/tmp" ;;
    cleanup-link) mkdir -m 700 "$unsafe_consumer/tmp"; ln -s "$target" "$unsafe_consumer/tmp/cleanup" ;;
    permissions) mkdir -m 755 "$unsafe_consumer/tmp" ;;
  esac
  set +e
  "$ROOT/scripts/sync-agentic-workspace.sh" "$unsafe_consumer" cross-repo-epic >/dev/null 2>&1
  rc=$?
  set -e
  [[ "$rc" -eq 3 && ! -e "$unsafe_consumer/.agents" ]]
  [[ -f "$target/KEEP" && ! -e "$unsafe_consumer/deleteme" ]]
done

# Unmanifested symlinks in the canonical source are never copied.
target2="$(mktemp -d "${TMPDIR:-/tmp}/maintainers-canonical-target.XXXXXX")"
printf keep > "$target2/KEEP"
ln -s "$target2" "$ROOT/.agents/skills/workspace-orchestrator/canonical-link"
set +e
"$ROOT/scripts/sync-agentic-workspace.sh" "$consumer" workspace-orchestrator >/dev/null 2>&1
rc=$?
set -e
rm "$ROOT/.agents/skills/workspace-orchestrator/canonical-link"
[[ "$rc" -eq 3 ]]
[[ -f "$target2/KEEP" ]]
[[ ! -e "$consumer/.agents/skills/workspace-orchestrator/canonical-link" ]]

printf 'import-sync tests: PASS\n'
