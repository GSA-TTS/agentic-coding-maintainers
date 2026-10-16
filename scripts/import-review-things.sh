#!/usr/bin/env bash
set -euo pipefail

[[ $# -eq 1 ]] || { echo "usage: $0 /path/to/review_things" >&2; exit 2; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$(cd "$1" && pwd)"
IMPORT_ROOT="$ROOT/.import"

required=(
  .agents/skills/cross-repo-epic/SKILL.md
  bin/portfolio-status.sh
  bin/portfolio-status.py
  bin/epic-status.sh
  bin/epic-status.py
  tests/portfolio-status-test.sh
  tests/epic-status-test.sh
  tests/fixtures/portfolio-bin/gh
  tests/fixtures/epic-status-bin/gh
)

for path in "${required[@]}"; do
  [[ -f "$SOURCE/$path" ]] || { echo "missing source file: $path" >&2; exit 3; }
done

[[ ! -L "$IMPORT_ROOT" ]] || { echo "import root must not be a symlink" >&2; exit 3; }
mkdir -p "$IMPORT_ROOT"
STAGING="$(mktemp -d "$IMPORT_ROOT/review-things.XXXXXX")"
DEST="$STAGING/cross-repo-epic"
install -d -m 0755 \
  "$DEST/bin" \
  "$DEST/tests/fixtures/portfolio-bin" \
  "$DEST/tests/fixtures/epic-status-bin"

install -m 0644 "$SOURCE/.agents/skills/cross-repo-epic/SKILL.md" "$DEST/SKILL.md"
for name in portfolio-status.sh portfolio-status.py epic-status.sh epic-status.py; do
  install -m 0755 "$SOURCE/bin/$name" "$DEST/bin/$name"
done
install -m 0755 "$SOURCE/tests/portfolio-status-test.sh" "$DEST/tests/portfolio-status-test.sh"
install -m 0755 "$SOURCE/tests/epic-status-test.sh" "$DEST/tests/epic-status-test.sh"
install -m 0755 "$SOURCE/tests/fixtures/portfolio-bin/gh" "$DEST/tests/fixtures/portfolio-bin/gh"
install -m 0755 "$SOURCE/tests/fixtures/epic-status-bin/gh" "$DEST/tests/fixtures/epic-status-bin/gh"

printf 'STAGED=%s\n' "$DEST"
