#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVAL="$ROOT/scripts/evaluate-workflow.py"
FIXTURE="$(mktemp -d "${TMPDIR:-/tmp}/maintainer-evaluation.XXXXXX")"
mkdir -p "$FIXTURE/.agents/skills/workspace-orchestrator/bin" "$FIXTURE/.orchestrator/tasks"
cp "$ROOT/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py" \
  "$FIXTURE/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py"
chmod 700 "$FIXTURE/.orchestrator" "$FIXTURE/.orchestrator/tasks"

# Absent and empty stores must not turn into a false measured zero.
set +e
absent="$(python3 "$EVAL" --workspace "$FIXTURE/missing" 2>&1)"
absent_rc=$?
empty="$(python3 "$EVAL" --workspace "$FIXTURE")"
empty_rc=$?
set -e
[[ "$absent_rc" -eq 3 && "$absent" == *UNVERIFIED* ]]
[[ "$empty_rc" -eq 3 ]]
python3 -c 'import json,sys; assert json.load(sys.stdin)["coverage"] == "no_evidence"' <<<"$empty"

# Emit a record through the canonical state tool in its sanctioned temporary
# test mode, then copy only the task record into the disposable consumer.
STATE="$FIXTURE/test-state"
export ORCHESTRATOR_STATE_DIR="$STATE" ORCHESTRATOR_TEST_MODE=1
export WORKSPACE_ORCHESTRATOR_ROOT="$FIXTURE"
python3 "$ROOT/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py" \
  create eval-case --scope 'evaluation:case:1' --kind review \
  --head-sha "$(printf 'a%.0s' {1..40})" >/dev/null
cp -R "$STATE/tasks/eval-case" "$FIXTURE/.orchestrator/tasks/"
report="$(python3 "$EVAL" --workspace "$FIXTURE")"
python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["coverage"]=="measured" and d["task_count"]==1 and d["by_state"]=={"Ready":1}; assert d["cases"][0]["id"]=="eval-case" and "time in state" in d["unmeasured"]' <<<"$report"

# A malformed record invalidates the entire report; it cannot be dropped from
# a denominator. Stage the fixture for operator disposal, never use rm.
python3 - "$FIXTURE/.orchestrator/tasks/eval-case/task.json" <<'PY'
import json
import sys
path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
data["rework_count"] = -1
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle)
PY
set +e
corrupt="$(python3 "$EVAL" --workspace "$FIXTURE" 2>&1)"
rc=$?
set -e
[[ "$rc" -eq 3 && "$corrupt" == *UNVERIFIED* ]]
printf 'evaluate-workflow tests: PASS\n'
