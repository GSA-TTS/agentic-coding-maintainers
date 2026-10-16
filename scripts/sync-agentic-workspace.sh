#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 1 || $# -eq 2 ]] || { echo "usage: $0 /path/to/agentic [skill-name]" >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORKSPACE="$(cd "$1" && pwd)"
SKILL="${2:-cross-repo-epic}"
case "$SKILL" in
  cross-repo-epic|workspace-orchestrator) ;;
  *) echo "unsupported skill: $SKILL" >&2; exit 2 ;;
esac
SOURCE="$ROOT/.agents/skills/$SKILL/"
DEST="$WORKSPACE/.agents/skills/$SKILL/"
[[ -f "$SOURCE/SKILL.md" ]] || { echo "canonical skill is missing: $SKILL" >&2; exit 3; }

[[ -f "$WORKSPACE/AGENTS.md" ]] || { echo "destination is not an agentic workspace" >&2; exit 3; }
for path in "$WORKSPACE/.agents" "$WORKSPACE/.agents/skills" "${DEST%/}"; do
  [[ ! -L "$path" ]] || { echo "destination path must not contain a symlink: $path" >&2; exit 3; }
done
mkdir -p "$WORKSPACE/.agents/skills"
parent="$WORKSPACE/.agents/skills"
lock="$parent/.${SKILL}.sync-lock"
if ! mkdir "$lock" 2>/dev/null; then
  echo "sync lock exists; inspect destination/backup before manual recovery: $lock" >&2
  exit 3
fi
stage=""
backup="$parent/.${SKILL}.previous.$$"
marker="$parent/.${SKILL}.sync-in-progress"
installed=false
restore() {
  if [[ "$installed" != true && -e "$backup" && ! -e "${DEST%/}" ]]; then
    mv "$backup" "${DEST%/}"
  fi
  rm -f "$marker"
  rmdir "$lock" 2>/dev/null || true
}
trap restore EXIT HUP INT TERM
[[ ! -e "$backup" ]] || { echo "sync backup already exists: $backup" >&2; exit 3; }
[[ ! -e "$marker" ]] || { echo "prior sync marker exists: $marker" >&2; exit 3; }
if [[ -e "${DEST%/}" ]]; then
  if find "${DEST%/}" -type l -print -quit | grep -q .; then
    echo "existing skill contains a symlink; refusing replacement" >&2
    exit 3
  fi
  if find "${DEST%/}" ! -type f ! -type d -print -quit | grep -q .; then
    echo "existing skill contains an unsupported entry type" >&2
    exit 3
  fi
fi
stage="$(mktemp -d "$parent/.${SKILL}.sync.XXXXXX")"
rsync -a --delete --exclude '__pycache__/' --exclude '*.py[co]' "$SOURCE" "$stage/"
printf '%s\n' "$backup" > "$marker"
if [[ -e "${DEST%/}" ]]; then mv "${DEST%/}" "$backup"; fi
if ! mv "$stage" "${DEST%/}"; then
  [[ ! -e "$backup" ]] || mv "$backup" "${DEST%/}"
  exit 3
fi
installed=true
if [[ -e "$backup" ]]; then
  find "$backup" -depth -type f -delete
  find "$backup" -depth -type d -exec rmdir {} +
fi
rm -f "$marker"
rmdir "$lock"
trap - EXIT HUP INT TERM

printf 'Synced skill to %s\n' "$DEST"
printf 'Record canonical commit %s in destination PROVENANCE.md after review.\n' \
  "$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || printf 'UNCOMMITTED')"
