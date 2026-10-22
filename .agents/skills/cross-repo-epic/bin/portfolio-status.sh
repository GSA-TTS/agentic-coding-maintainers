#!/usr/bin/env bash
# portfolio-status.sh — read-only epic view from the configured Project v2 board.
# Exit: 0 = coverage printed; 2 = usage; 3 = UNVERIFIED.
set -uo pipefail

[[ $# -eq 0 ]] || { echo "usage: bin/portfolio-status.sh" >&2; exit 2; }
command -v gh >/dev/null 2>&1 || { echo "portfolio: UNVERIFIED — gh is not installed" >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo "portfolio: UNVERIFIED — python3 is not installed" >&2; exit 3; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/portfolio-status.py"
