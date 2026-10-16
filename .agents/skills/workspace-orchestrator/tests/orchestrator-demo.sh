#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$(mktemp -d "${TMPDIR:-/tmp}/orchestrator-demo.XXXXXX")"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/orchestrator-demo-work.XXXXXX")"
mkdir "$WORK/alpha" "$WORK/beta" "$WORK/review"
export ORCHESTRATOR_STATE_DIR="$STATE"
export ORCHESTRATOR_TEST_MODE=1
CMD="$ROOT/bin/orchestrator-state.sh"

echo '== simulated two nonconflicting implementation lanes (test mode) =='
for t in alpha beta; do
  sha="$(printf 'a%.0s' {1..40})"
  "$CMD" create "$t" --scope "demo:path:$t" --kind implementation --worktree "$WORK/$t" \
    --head-sha "$sha" --owned-path "$t.txt" --acceptance "$t validated" >/dev/null
  "$CMD" claim "$t" --owner "worker-$t" --pid $$ >/dev/null
  "$CMD" transition "$t" Implementing >/dev/null
done
python3 - "$STATE" <<'PY'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1])
lanes=[]
for task in ("alpha", "beta"):
    d=json.load(open(root/"tasks"/task/"task.json"))
    lanes.append(d["leases"]["implementation_lane"])
assert sorted(lanes)==[0,1], lanes
print("two lanes admitted:", lanes)
PY

echo '== simulated exact resource conflict =='
"$CMD" create owner --scope 'demo:shared-interface' --kind review --worktree "$WORK/review" >/dev/null
set +e
"$CMD" create conflict --scope 'demo:shared-interface' --kind implementation --worktree "$WORK" >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 4 ]]
echo 'overlap refused (rc=4)'

echo '== independent review and interrupted worker =='
"$CMD" transition alpha Reviewing >/dev/null
sha="$(printf 'a%.0s' {1..40})"
"$CMD" record alpha reviewer qa-reviewer --reviewed-sha "$sha" >/dev/null
"$CMD" record alpha validation 'demo acceptance checks passed' >/dev/null
"$CMD" transition alpha 'Ready for human review' >/dev/null
mv "$WORK/beta" "$WORK/beta.gone"
"$CMD" reconcile beta >/dev/null
grep -q '"state": "Blocked"' "$STATE/tasks/beta/task.json"
echo 'alpha ready for human review; beta blocked after worktree loss'

echo 'orchestrator dry-run demonstration: PASS (production Git enforcement not exercised)'
