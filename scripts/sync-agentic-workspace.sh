#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 1 ]] || { echo "usage: $0 /path/to/agentic" >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="$(cd "$1" && pwd)"
SOURCE="$ROOT/.agents/skills/cross-repo-epic/"
DEST="$WORKSPACE/.agents/skills/cross-repo-epic/"

[[ -f "$WORKSPACE/AGENTS.md" ]] || { echo "destination is not an agentic workspace" >&2; exit 3; }
for path in "$WORKSPACE/.agents" "$WORKSPACE/.agents/skills" "${DEST%/}"; do
  [[ ! -L "$path" ]] || { echo "destination path must not contain a symlink: $path" >&2; exit 3; }
done
mkdir -p "$DEST"
find "$DEST" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$DEST" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
rsync -a --delete --exclude '__pycache__/' --exclude '*.py[co]' "$SOURCE" "$DEST"

printf 'Synced skill to %s\n' "$DEST"
printf 'Record canonical commit %s in destination PROVENANCE.md after review.\n' \
  "$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || printf 'UNCOMMITTED')"
