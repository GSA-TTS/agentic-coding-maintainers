#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVAL="$ROOT/scripts/evaluate-workflow.py"
FIXTURE="$(mktemp -d "${TMPDIR:-/tmp}/maintainer-evaluation.XXXXXX")"
mkdir -p "$FIXTURE/.agents/skills/workspace-orchestrator/bin" "$FIXTURE/.orchestrator/tasks"
printf 'raise RuntimeError("workspace-selected code executed")\n' > \
  "$FIXTURE/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py"
chmod 700 "$FIXTURE/.orchestrator" "$FIXTURE/.orchestrator/tasks"

# Absent and empty stores must not turn into a false measured zero.
set +e
absent="$(python3 -I -B "$EVAL" --workspace "$FIXTURE/missing" 2>&1)"
absent_rc=$?
empty="$(python3 -I -B "$EVAL" --workspace "$FIXTURE")"
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
report="$(python3 -I -B "$EVAL" --workspace "$FIXTURE")"
python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["coverage"]=="parsed_task_records" and d["task_count"]==1 and d["by_state"]=={"Ready":1}; assert d["cases"][0]["id"]=="eval-case" and "time in state" in d["unmeasured"] and "reservation/lease consistency" in d["unmeasured"]' <<<"$report"
[[ ! -e "$ROOT/.agents/skills/workspace-orchestrator/bin/__pycache__" ]]

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
corrupt="$(python3 -I -B "$EVAL" --workspace "$FIXTURE" 2>&1)"
rc=$?
set -e
[[ "$rc" -eq 3 && "$corrupt" == *UNVERIFIED* ]]
# A malformed type formerly raised an uncaught TypeError inside the canonical
# validator. It must produce the same bounded UNVERIFIED response, not traceback.
cp "$STATE/tasks/eval-case/task.json" "$FIXTURE/.orchestrator/tasks/eval-case/task.json"
python3 - "$FIXTURE/.orchestrator/tasks/eval-case/task.json" <<'PY'
import json
import sys
path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
data["state"] = []
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle)
PY
set +e
wrong_type="$(python3 -I -B "$EVAL" --workspace "$FIXTURE" 2>&1)"
rc=$?
set -e
[[ "$rc" -eq 3 && "$wrong_type" == *UNVERIFIED* && "$wrong_type" != *Traceback* ]]
# Legacy schema-1 records were upgraded with a DEFAULT rework_count=0. A
# default is not evidence of zero rework and must render as null.
cp "$STATE/tasks/eval-case/task.json" "$FIXTURE/.orchestrator/tasks/eval-case/task.json"
python3 - "$FIXTURE/.orchestrator/tasks/eval-case/task.json" <<'PY'
import json
import sys
path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
data["schema_version"] = 1
for field in ("tracker_type", "tracker_number", "head_sha", "reviewed_sha", "transition_intent", "rework_count"):
    data.pop(field, None)
with open(path, "w", encoding="utf-8") as handle:
    json.dump(data, handle)
PY
legacy="$(python3 -I -B "$EVAL" --workspace "$FIXTURE")"
python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["cases"][0]["recorded_rework_count"] is None' <<<"$legacy"
# A symlinked task file cannot redirect a host read outside the workspace.
mv "$FIXTURE/.orchestrator/tasks/eval-case/task.json" "$FIXTURE/.orchestrator/tasks/eval-case/task.original.json"
ln -s "$FIXTURE/.orchestrator/tasks/eval-case/task.original.json" "$FIXTURE/.orchestrator/tasks/eval-case/task.json"
set +e
linked="$(python3 -I -B "$EVAL" --workspace "$FIXTURE" 2>&1)"
rc=$?
set -e
[[ "$rc" -eq 3 && "$linked" == *UNVERIFIED* ]]
printf 'evaluate-workflow tests: PASS\n'
