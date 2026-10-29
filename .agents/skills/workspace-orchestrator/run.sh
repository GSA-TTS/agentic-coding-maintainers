#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
[[ $# -ge 1 ]] || {
  echo "usage: $0 state|monitor|review-packet|review-evidence|review-run|demo [args...]" >&2
  exit 2
}

command="$1"
shift
case "$command" in
  state) exec "$ROOT/bin/orchestrator-state.sh" "$@" ;;
  monitor) exec "$ROOT/bin/orchestrator-monitor.sh" "$@" ;;
  review-packet) exec python3 -I -B "$ROOT/bin/review-packet.py" "$@" ;;
  review-evidence) exec python3 -I -B "$ROOT/bin/review-evidence.py" "$@" ;;
  review-run) exec python3 -I -B "$ROOT/bin/review-run.py" "$@" ;;
  demo) exec bash "$ROOT/tests/orchestrator-demo.sh" "$@" ;;
  *) echo "unknown workspace-orchestrator command: $command" >&2; exit 2 ;;
esac
