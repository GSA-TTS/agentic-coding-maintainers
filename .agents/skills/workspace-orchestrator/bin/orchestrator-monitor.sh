#!/usr/bin/env bash
# Foreground only. Exit 0 = current/changed; 2 = usage; 3 = UNVERIFIED.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
command -v python3 >/dev/null 2>&1 || {
  echo "monitor: UNVERIFIED - python3 is not installed" >&2
  exit 3
}
exec python3 "$SCRIPT_DIR/orchestrator-monitor.py" "$@"
