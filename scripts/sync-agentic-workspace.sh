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
if find "$SOURCE" -type l -print -quit | grep -q .; then
  echo "canonical skill contains a symlink" >&2
  exit 3
fi
if find "$SOURCE" ! -type f ! -type d -print -quit | grep -q .; then
  echo "canonical skill contains an unsupported entry type" >&2
  exit 3
fi
git_safe() {
  env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_OBJECT_DIRECTORY \
    -u GIT_ALTERNATE_OBJECT_DIRECTORIES -u GIT_COMMON_DIR \
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 \
    git -c core.fsmonitor=false -c core.hooksPath=/dev/null -C "$ROOT" "$@"
}
source_commit="$(git_safe rev-parse HEAD)" || { echo "canonical commit is unavailable" >&2; exit 3; }
source_dirty=false
source_status="$(git_safe status --porcelain --untracked-files=all -- "$SOURCE")" || { echo "canonical status is unavailable" >&2; exit 3; }
[[ -z "$source_status" ]] || source_dirty=true
if [[ "$SKILL" == workspace-orchestrator ]]; then
  tmp_manifest="$(mktemp)"
  (cd "$SOURCE" && find . -type d -name __pycache__ -prune -o -type f ! -name CANONICAL-SHA256SUMS ! -name '*.pyc' ! -name '*.pyo' -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > "$tmp_manifest"
  diff -u "$SOURCE/CANONICAL-SHA256SUMS" "$tmp_manifest" >/dev/null || { rm -f "$tmp_manifest"; echo "canonical skill manifest mismatch" >&2; exit 3; }
  rm -f "$tmp_manifest"
fi

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
marker_token="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
installed=false
marker_created=false
restore() {
  if [[ "$installed" != true && -e "$backup" && ! -e "${DEST%/}" ]]; then
    mv "$backup" "${DEST%/}"
  fi
  if [[ "$marker_created" == true && -f "$marker/owner" && "$(cat "$marker/owner")" == "$marker_token" ]]; then
    rm -f "$marker/owner"
    rmdir "$marker"
  fi
  rmdir "$lock" 2>/dev/null || true
}
trap restore EXIT HUP INT TERM
[[ ! -e "$backup" ]] || { echo "sync backup already exists: $backup" >&2; exit 3; }
if ! mkdir "$marker" 2>/dev/null; then
  echo "prior sync marker exists: $marker" >&2
  exit 3
fi
printf '%s\n' "$marker_token" > "$marker/owner"
marker_created=true
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
if find "$stage" -type l -print -quit | grep -q .; then
  echo "staged skill contains a symlink" >&2
  exit 3
fi
if find "$stage" ! -type f ! -type d -print -quit | grep -q .; then
  echo "staged skill contains an unsupported entry type" >&2
  exit 3
fi
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
rm -f "$marker/owner"
rmdir "$marker"
rmdir "$lock"
trap - EXIT HUP INT TERM

printf 'Synced skill to %s\n' "$DEST"
printf 'SOURCE_COMMIT=%s\n' "$source_commit"
printf 'SOURCE_DIRTY=%s\n' "$source_dirty"
printf 'Record this commit/dirty state in destination PROVENANCE.md after review.\n'
