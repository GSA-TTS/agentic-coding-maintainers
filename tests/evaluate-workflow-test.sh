#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVAL="$ROOT/scripts/evaluate-workflow.py"
# Use Python's system temporary path, which is also the root the canonical
# test-mode state tool accepts. A fixture is created in its FINAL dated path;
# there is never a second active directory to move on failure or interrupt.
# Use the approved system temporary parent, independent of inherited Python
# temp redirects. /tmp may be an OS-managed symlink on macOS; resolve it and
# require the owner to be root or this user and a world-writable parent to be
# sticky before allocating anything.
TEMP_ROOT="$(python3 -I -B -c 'import os; print(os.path.realpath("/tmp"))')"
OUTBOX="$TEMP_ROOT/maintainer-evaluation-disposal"
if [[ -L "$OUTBOX" ]]; then
  echo 'UNVERIFIED: evaluation disposal outbox is a symlink' >&2
  exit 3
fi
umask 077
python3 -I -B - "$TEMP_ROOT" <<'PY' || { echo 'UNVERIFIED: temporary root is unsafe' >&2; exit 3; }
import os
import stat
import sys
info = os.stat(sys.argv[1])
assert stat.S_ISDIR(info.st_mode) and info.st_uid in (0, os.getuid())
assert not info.st_mode & 0o002 or info.st_mode & stat.S_ISVTX
PY
mkdir -p "$OUTBOX"
python3 -I -B - "$OUTBOX" <<'PY' || { echo 'UNVERIFIED: evaluation disposal outbox is not private' >&2; exit 3; }
import os
import stat
import sys
info = os.lstat(sys.argv[1])
assert stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o077
PY
export TMPDIR="$TEMP_ROOT/"
FIXTURE="$(mktemp -d "$OUTBOX/$(date -u +%Y-%m-%d)-evaluation.XXXXXX")"
CHECKS="not_started"
finish_fixture() {
  result=$?
  trap - EXIT HUP INT TERM
  if ! printf '\nExit: %s; checks: %s\n' "$result" "$CHECKS" >> "$FIXTURE/MANIFEST.md"; then
    echo 'UNVERIFIED: evaluation fixture manifest could not be finalized' >&2
    exit 3
  fi
  printf 'evaluation_fixture_staged=%s\n' "$FIXTURE" >&2
  exit "$result"
}
trap finish_fixture EXIT
trap 'exit 3' HUP INT TERM
cat > "$FIXTURE/MANIFEST.md" <<'EOF'
# Evaluation test fixture

This dated directory was created by `tests/evaluate-workflow-test.sh`. Depending
on where the run stopped, it may contain a malicious-validator sentinel that
should never be imported, synthetic task state, and malformed synthetic task
records used to assert UNVERIFIED results. No real maintainer evidence is
referenced. Safe for the operator to delete. The exit status and check progress
below distinguish a completed run from an interrupted one. Stored outside the
repository because Gitleaks scans ignored files too.
EOF
CHECKS="fixture_created"
if [[ "${EVALUATION_TEST_ABORT_AFTER_FIXTURE:-}" == 1 ]]; then
  exit 17 # Test the EXIT trap's failure path without creating a task record.
fi
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
STATE="$FIXTURE/test-state-source"
export ORCHESTRATOR_STATE_DIR="$STATE" ORCHESTRATOR_TEST_MODE=1
export WORKSPACE_ORCHESTRATOR_ROOT="$FIXTURE"
python3 -I -B "$ROOT/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py" \
  create eval-case --scope 'evaluation:case:1' --kind review \
  --head-sha "$(printf 'a%.0s' {1..40})" >/dev/null
cp -R "$STATE/tasks/eval-case" "$FIXTURE/.orchestrator/tasks/"
report="$(python3 -I -B "$EVAL" --workspace "$FIXTURE")"
python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["coverage"]=="parsed_task_records" and d["task_count"]==1 and d["by_state"]=={"Ready":1}; assert d["cases"][0]["id"]=="eval-case" and "time in state" in d["unmeasured"] and "reservation/lease consistency" in d["unmeasured"]' <<<"$report"
[[ ! -e "$ROOT/.agents/skills/workspace-orchestrator/bin/__pycache__" ]]

# Retained findings are not an unresolved count. Exercise the scorecard CLI
# with exact, synthetic disposition records; no real review is attested here.
python3 -I -B - "$EVAL" "$FIXTURE" <<'PY'
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

script, workspace = sys.argv[1:]
path = Path(workspace) / ".orchestrator/tasks/eval-case/task.json"
original = path.read_bytes()
base = json.loads(original)
base.update(kind="implementation", owner="fixture-owner", revision=10,
            findings=["first retained finding", "second retained finding"])
history = [{
    "finding_index": index,
    "finding_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    "head_sha": base["head_sha"], "epoch": 0,
    "disposition": disposition, "reviewer": "fixture-qa",
    "implementation_owner": base["owner"], "evidence": "synthetic scorecard fixture",
    "revision": index + 1,
} for index, (text, disposition) in enumerate(zip(base["findings"], ("fixed", "refuted")))]

def score(record, expected=None):
    path.write_text(json.dumps(record), encoding="utf-8")
    result = subprocess.run([sys.executable, "-I", "-B", script, "--workspace", workspace],
                            text=True, capture_output=True)
    if expected is None:
        assert result.returncode == 3, (result.stdout, result.stderr)
        assert "UNVERIFIED" in result.stderr and not result.stdout
    else:
        assert result.returncode == 0, (result.stdout, result.stderr)
        report = json.loads(result.stdout)
        assert report["coverage"] == "parsed_task_records" and report["task_count"] == 1
        assert report["cases"][0]["unresolved_finding_count"] == expected, report
    assert json.loads(path.read_text())["findings"] == base["findings"]

try:
    score(base, 2)  # no extension resolves nothing
    partial = copy.deepcopy(base)
    partial["legacy_finding_dispositions"] = {"epoch": 0, "history": history[:1]}
    score(partial, 1)
    full = copy.deepcopy(base)
    full["legacy_finding_dispositions"] = {"epoch": 0, "history": history}
    score(full, 0)
    stale = copy.deepcopy(full)
    stale["head_sha"] = "b" * 40
    stale["legacy_finding_dispositions"]["epoch"] = 1
    score(stale, 2)
    stale["head_sha"] = base["head_sha"]  # A -> B -> A does not revive old claims
    stale["legacy_finding_dispositions"]["epoch"] = 2
    score(stale, 2)
    stale["legacy_finding_dispositions"]["history"].append(dict(history[1], epoch=2, revision=3))
    score(stale, 1)  # one current claim, one still historical
    corrupt = copy.deepcopy(full)
    corrupt["legacy_finding_dispositions"]["history"][0]["finding_sha256"] = "0" * 64
    score(corrupt)
    corrupt = copy.deepcopy(full)
    corrupt["legacy_finding_dispositions"]["epoch"] = 1
    corrupt["legacy_finding_dispositions"]["history"][1]["implementation_owner"] = "other-owner"
    score(corrupt)  # historical owner conflict invalidates the entire scorecard
finally:
    path.write_bytes(original)
PY

# A malformed record invalidates the entire report; it cannot be dropped from
# a denominator. Stage the fixture for operator disposal, never use rm.
python3 -I -B - "$FIXTURE/.orchestrator/tasks/eval-case/task.json" <<'PY'
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
cp "$FIXTURE/test-state-source/tasks/eval-case/task.json" "$FIXTURE/.orchestrator/tasks/eval-case/task.json"
python3 -I -B - "$FIXTURE/.orchestrator/tasks/eval-case/task.json" <<'PY'
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
cp "$FIXTURE/test-state-source/tasks/eval-case/task.json" "$FIXTURE/.orchestrator/tasks/eval-case/task.json"
python3 -I -B - "$FIXTURE/.orchestrator/tasks/eval-case/task.json" <<'PY'
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
CHECKS="passed"
printf 'evaluate-workflow tests: PASS\n'
