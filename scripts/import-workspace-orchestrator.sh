#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 1 ]] || { echo "usage: $0 /path/to/review_things" >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ ! -L "$1" ]] || { echo "source root must not be a symlink" >&2; exit 3; }
SOURCE="$(cd "$1" && pwd)"
IMPORT_ROOT="$ROOT/.import"

required=(
  bin/orchestrator-state.sh
  bin/orchestrator-state.py
  bin/orchestrator-monitor.sh
  bin/orchestrator-monitor.py
  tests/orchestrator-state-test.sh
  tests/orchestrator-monitor-test.sh
  tests/orchestrator-demo.sh
  tests/fixtures/orchestrator-monitor-bin/gh
  docs/ORCHESTRATION.md
  .opencode/agents/backlog-project-monitor.md
  .opencode/agents/implementation-worker.md
  .opencode/agents/orchestration-qa.md
  .opencode/agents/pr-review-coordinator.md
  .opencode/agents/qa-reviewer.md
  .opencode/agents/security-reviewer.md
)
for path in "${required[@]}"; do
  [[ -f "$SOURCE/$path" ]] || { echo "missing source file: $path" >&2; exit 3; }
  [[ ! -L "$SOURCE/$path" ]] || { echo "source file must not be a symlink: $path" >&2; exit 3; }
done
for path in "$SOURCE/bin" "$SOURCE/tests" "$SOURCE/tests/fixtures" "$SOURCE/tests/fixtures/orchestrator-monitor-bin" "$SOURCE/docs" "$SOURCE/.opencode" "$SOURCE/.opencode/agents"; do
  [[ ! -L "$path" ]] || { echo "source path must not be a symlink: $path" >&2; exit 3; }
done
expected_profiles=(backlog-project-monitor.md implementation-worker.md orchestration-qa.md pr-review-coordinator.md qa-reviewer.md security-reviewer.md)
profiles="$(find "$SOURCE/.opencode/agents" -mindepth 1 -maxdepth 1 -exec basename {} \; | LC_ALL=C sort | tr '\n' ' ')"
expected="${expected_profiles[*]} "
[[ "$profiles" == "$expected" ]] || { echo "unexpected OpenCode profile set" >&2; exit 3; }

[[ ! -L "$IMPORT_ROOT" ]] || { echo "import root must not be a symlink" >&2; exit 3; }
mkdir -p "$IMPORT_ROOT"
STAGING="$(mktemp -d "$IMPORT_ROOT/workspace-orchestrator.XXXXXX")"
DEST="$STAGING/workspace-orchestrator"
install -d -m 0755 "$DEST/bin" "$DEST/tests/fixtures/orchestrator-monitor-bin" "$DEST/docs" "$DEST/profiles/opencode-v1"

for name in orchestrator-state.sh orchestrator-state.py orchestrator-monitor.sh orchestrator-monitor.py; do
  install -m 0755 "$SOURCE/bin/$name" "$DEST/bin/$name"
done
for name in orchestrator-state-test.sh orchestrator-monitor-test.sh orchestrator-demo.sh; do
  install -m 0755 "$SOURCE/tests/$name" "$DEST/tests/$name"
done
install -m 0755 "$SOURCE/tests/fixtures/orchestrator-monitor-bin/gh" "$DEST/tests/fixtures/orchestrator-monitor-bin/gh"
install -m 0644 "$SOURCE/docs/ORCHESTRATION.md" "$DEST/docs/OPERATOR-GUIDE.md"
for name in "${expected_profiles[@]}"; do
  install -m 0644 "$SOURCE/.opencode/agents/$name" "$DEST/profiles/opencode-v1/$name"
done

(
  cd "$DEST"
  manifest="$(mktemp "$STAGING/source-sha256.XXXXXX")"
  find . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256 > "$manifest"
  mv "$manifest" SOURCE-SHA256SUMS
)
git -C "$SOURCE" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "source Git metadata is unavailable" >&2; exit 3; }
base_commit="$(git -C "$SOURCE" rev-parse HEAD)" || { echo "source HEAD is unavailable" >&2; exit 3; }
dirty=false
status="$(git -C "$SOURCE" status --porcelain --untracked-files=all)" || { echo "source status is unavailable" >&2; exit 3; }
[[ -z "$status" ]] || dirty=true
cat > "$DEST/IMPORT-METADATA.json" <<JSON
{
  "schema_version": 1,
  "source_base_commit": "$base_commit",
  "source_dirty": $dirty,
  "source_mappings": {
    "docs/ORCHESTRATION.md": "docs/OPERATOR-GUIDE.md",
    ".opencode/agents/*.md": "profiles/opencode-v1/*.md"
  }
}
JSON
printf 'SOURCE_BASE_COMMIT=%s\n' "$base_commit"
printf 'SOURCE_DIRTY=%s\n' "$dirty"
printf 'STAGED=%s\n' "$DEST"
