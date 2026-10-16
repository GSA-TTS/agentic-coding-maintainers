#!/usr/bin/env bash
# Skill-local dispatcher. Resolve this file by its discovered absolute skill path.
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
command_name="${1:-}"
[[ $# -gt 0 ]] && shift

case "$command_name" in
  portfolio-status) exec "$SKILL_DIR/bin/portfolio-status.sh" "$@" ;;
  epic-status) exec "$SKILL_DIR/bin/epic-status.sh" "$@" ;;
  *)
    echo "usage: $0 <portfolio-status|epic-status> [epic-reference]" >&2
    exit 2
    ;;
esac
