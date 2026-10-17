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
printf '# consumer\n' > "$consumer/AGENTS.md"
mkdir -p "$consumer/.agents/skills/sibling"
printf keep > "$consumer/.agents/skills/sibling/KEEP"
"$ROOT/scripts/sync-agentic-workspace.sh" "$consumer" workspace-orchestrator >/dev/null
[[ -f "$consumer/.agents/skills/workspace-orchestrator/SKILL.md" ]]
[[ -f "$consumer/.agents/skills/sibling/KEEP" ]]
expected_dirty=false
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=all -- .agents/skills/workspace-orchestrator)" ]] || expected_dirty=true
sync_out="$("$ROOT/scripts/sync-agentic-workspace.sh" "$consumer" workspace-orchestrator)"
grep -q "SOURCE_DIRTY=$expected_dirty" <<<"$sync_out"

set +e
ln -s /tmp "$consumer/.agents/skills/cross-repo-epic"
"$ROOT/scripts/sync-agentic-workspace.sh" "$consumer" cross-repo-epic >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 3 ]]

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

# A pre-existing uncertain marker is not deleted by a later refused invocation.
mkdir "$consumer/.agents/skills/.cross-repo-epic.sync-in-progress"
printf 'prior-evidence\n' > "$consumer/.agents/skills/.cross-repo-epic.sync-in-progress/owner"
set +e
"$ROOT/scripts/sync-agentic-workspace.sh" "$consumer" cross-repo-epic >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 3 ]]
grep -q prior-evidence "$consumer/.agents/skills/.cross-repo-epic.sync-in-progress/owner"

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
