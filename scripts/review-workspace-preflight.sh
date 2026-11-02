#!/bin/sh
# Supported entry point: isolate Python before interpreter startup/imports.
# Usage: sh scripts/review-workspace-preflight.sh --source ... --consumer ... --expected-source ...
set -eu
case "$0" in
    */*) script_dir=${0%/*} ;;
    *) script_dir=. ;;
esac
exec python3 -I -B "$script_dir/review-workspace-preflight.py" "$@"
