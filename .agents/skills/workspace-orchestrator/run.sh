#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
[[ $# -ge 1 ]] || {
  echo "usage: $0 state|monitor|demo [args...]" >&2
  exit 2
}

command="$1"
shift
case "$command" in
  state) exec "$ROOT/bin/orchestrator-state.sh" "$@" ;;
  monitor) exec "$ROOT/bin/orchestrator-monitor.sh" "$@" ;;
  demo) exec bash "$ROOT/tests/orchestrator-demo.sh" "$@" ;;
  *) echo "unknown workspace-orchestrator command: $command" >&2; exit 2 ;;
esac
