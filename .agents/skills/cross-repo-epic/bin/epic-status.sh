#!/usr/bin/env bash
# epic-status.sh — authoritative live state for one agentic-coding epic.
# Exit: 0 = complete requested coverage; 2 = invalid input; 3 = UNVERIFIED.
set -uo pipefail

[[ $# -eq 1 ]] || { echo "usage: bin/epic-status.sh <patterns#N|quickstart#N|playbook#N|issue-url>" >&2; exit 2; }
command -v gh >/dev/null 2>&1 || { echo "epic: UNVERIFIED — gh is not installed" >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "epic: UNVERIFIED — python3 is not installed" >&2; exit 3; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/epic-status.py" "$1"
