#!/usr/bin/env bash
# Exit: 0 = verified operation; 2 = invalid input; 3 = UNKNOWN/UNVERIFIED;
#       4 = verified contention or policy refusal.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
command -v python3 >/dev/null 2>&1 || {
  echo "orchestrator: UNVERIFIED - python3 is not installed" >&2
  exit 3
}
exec python3 "$SCRIPT_DIR/orchestrator-state.py" "$@"
