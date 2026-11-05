#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$(mktemp -d "${TMPDIR:-/tmp}/orchestrator-monitor.XXXXXX")"
FIXTURE="$ROOT/tests/fixtures/orchestrator-monitor-bin"
MON="$ROOT/bin/orchestrator-monitor.py"
CMD="$ROOT/bin/orchestrator-state.sh"
CONFIG="$STATE/monitor-config.json"
export ORCHESTRATOR_STATE_DIR="$STATE"
export ORCHESTRATOR_TEST_MODE=1
mkdir "$STATE-work"
cat > "$CONFIG" <<'JSON'
{
  "schema_version": 1,
  "repositories": ["example/one", "example/two"],
  "project": {"owner": "example", "number": 42}
}
JSON
"$CMD" create monitor-test --scope 'monitor:test' --kind monitor --worktree "$STATE-work" >/dev/null
"$CMD" claim monitor-test --owner test-monitor --pid $$ >/dev/null

run_monitor() {
  local mode="$1"; shift
  PATH="$FIXTURE:/usr/bin:/bin" MONITOR_STUB_MODE="$mode" \
    python3 "$MON" --task-id monitor-test --config "$CONFIG" "$@"
}

out="$(run_monitor success)"
grep -q 'monitor: CHANGED' <<<"$out"
[[ -f "$STATE/monitor/checkpoint.json" ]]
success_at="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["last_success_at"])' "$STATE/monitor/checkpoint.json")"

# Same observation is quiet.
[[ -z "$(run_monitor success)" ]]
success_at="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["last_success_at"])' "$STATE/monitor/checkpoint.json")"

# A failed query is UNVERIFIED, does not advance the success checkpoint, and
# records a separate failed attempt without raw ANSI control characters.
set +e
err="$(run_monitor failure 2>&1 >/dev/null)"; rc=$?
set -e
[[ "$rc" -eq 3 ]]

# Symlinked checkpoints are rejected by the bounded reader.
mv "$STATE/monitor/checkpoint.json" "$STATE/monitor/checkpoint.real.json"
ln -s checkpoint.real.json "$STATE/monitor/checkpoint.json"
set +e
run_monitor success >/dev/null 2>&1; rc=$?
set -e
[[ "$rc" -eq 3 ]]
rm "$STATE/monitor/checkpoint.json"
mv "$STATE/monitor/checkpoint.real.json" "$STATE/monitor/checkpoint.json"
grep -q UNVERIFIED <<<"$err"
if printf '%s' "$err" | LC_ALL=C grep -q $'\033'; then
  echo 'raw ANSI leaked from monitor failure' >&2; exit 1
fi
[[ "$success_at" == "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["last_success_at"])' "$STATE/monitor/checkpoint.json")" ]]
grep -q 'UNVERIFIED' "$STATE/monitor/last-failure.json"

# Malformed successful output is still UNVERIFIED.
for mode in missing-draft null-draft string-draft; do
  set +e
  err="$(run_monitor "$mode" 2>&1 >/dev/null)"; rc=$?
  set -e
  [[ "$rc" -eq 3 && "$err" == *UNVERIFIED* && "$err" == *draft* ]]
done
set +e
run_monitor malformed >/dev/null 2>&1; rc=$?
set -e
[[ "$rc" -eq 3 ]]

# Valid JSON with the wrong checkpoint shape is UNVERIFIED, not a traceback or
# an invented no-change result.
os_checkpoint="$STATE/monitor/checkpoint.json"
cp "$os_checkpoint" "$STATE/monitor/checkpoint.backup.json"
printf '[]\n' > "$os_checkpoint"
set +e
run_monitor success >/dev/null 2>&1; rc=$?
set -e
[[ "$rc" -eq 3 ]]
# Restore a valid checkpoint for the remaining lock test.
mv "$STATE/monitor/checkpoint.backup.json" "$STATE/monitor/checkpoint.json"

# Lock contention is "not checked", never no-change.
mkdir "$STATE/monitor/poll.lock"
set +e
run_monitor success >/dev/null 2>&1; rc=$?
set -e
[[ "$rc" -eq 3 ]]
rmdir "$STATE/monitor/poll.lock"

# Reject an interval that would accidentally hammer GitHub.
set +e
PATH="$FIXTURE:/usr/bin:/bin" python3 "$MON" --task-id monitor-test --config "$CONFIG" --loop --interval 10 >/dev/null 2>&1; rc=$?
set -e
[[ "$rc" -eq 2 ]]

# A successful but truncated Project response is UNVERIFIED, not unchanged.
set +e
err="$(run_monitor project-incomplete 2>&1 >/dev/null)"; rc=$?
set -e
[[ "$rc" -eq 3 && "$err" == *"coverage is incomplete"* ]]

# Config is data, not a command surface: bad repo names, duplicate repos, and
# malformed project identities all fail UNVERIFIED before gh runs.
printf '{"schema_version":1,"repositories":["../escape"]}\n' > "$CONFIG"
set +e
run_monitor success >/dev/null 2>&1; rc=$?
set -e
[[ "$rc" -eq 3 ]]

printf '{"schema_version":1,"repositories":["example/one","example/one"]}\n' > "$CONFIG"
set +e; run_monitor success >/dev/null 2>&1; rc=$?; set -e
[[ "$rc" -eq 3 ]]

printf '{"schema_version":1,"repositories":["example/one"],"unexpected":true}\n' > "$CONFIG"
set +e; run_monitor success >/dev/null 2>&1; rc=$?; set -e
[[ "$rc" -eq 3 ]]

printf '{"schema_version":1,"repositories":["example/one"],"project":{"owner":"bad/owner","number":0}}\n' > "$CONFIG"
set +e; run_monitor success >/dev/null 2>&1; rc=$?; set -e
[[ "$rc" -eq 3 ]]

mv "$CONFIG" "$CONFIG.real"
ln -s "$(basename "$CONFIG.real")" "$CONFIG"
set +e; run_monitor success >/dev/null 2>&1; rc=$?; set -e
[[ "$rc" -eq 3 ]]
rm "$CONFIG"; mv "$CONFIG.real" "$CONFIG"

set +e
PATH="$FIXTURE:/usr/bin:/bin" python3 "$MON" --task-id '../escape' --config "$CONFIG" >/dev/null 2>&1; rc=$?
set -e
[[ "$rc" -eq 3 ]]

# No network or backoff delays: test retry decisions and observation boundaries.
python3 -I -B - "$MON" <<'PY'
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("monitor_retry", sys.argv[1])
assert spec and spec.loader
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)
query = ["gh", "pr", "list", "-R", "example/one"]

def response(code, stderr="", stdout=""):
    return subprocess.CompletedProcess(query, code, stdout, stderr)

for status in (502, 503, 504):
    for prefix in ("", "gh: "):
        with patch.object(monitor.subprocess, "run", side_effect=[
            response(1, f"{prefix}HTTP {status}: gateway", "partial"), response(0, stdout="[]")
        ]) as call, patch.object(monitor.time, "sleep") as sleep:
            assert monitor.run(query) == "[]"
            assert call.call_count == 2
            sleep.assert_called_once_with(1)
    code = f"import sys; print('HTTP {status}: gateway', file=sys.stderr); sys.exit(1)"
    try:
        monitor._bounded_run_once([sys.executable, "-c", code], 5)
        raise AssertionError("bounded gateway error was accepted")
    except monitor.GatewayError:
        pass

for runner, target in (
    (monitor.run, "subprocess"), (monitor.bounded_run, "bounded")
):
    # Exercise both runners with the same exhaustion and budget expectations.
    obj, name = (monitor.subprocess, "run") if target == "subprocess" else (monitor, "_bounded_run_once")
    def fail(*args, **kwargs):
        if target == "subprocess":
            return response(1, "HTTP 504: gateway", "[]")
        raise monitor.GatewayError("gateway")
    with patch.object(obj, name, side_effect=fail) as call, patch.object(monitor.time, "sleep") as sleep:
        try:
            runner(query, 30)
            raise AssertionError("exhaustion passed")
        except monitor.MonitorError as exc:
            assert "3 attempt(s)" in str(exc)
        assert call.call_count == 3
        assert [c.args[0] for c in sleep.call_args_list] == [1, 2]
    with patch.object(obj, name, side_effect=fail) as call, \
         patch.object(monitor.time, "monotonic", side_effect=[0, 0, 29]), \
         patch.object(monitor.time, "sleep") as sleep:
        try:
            runner(query, 30)
            raise AssertionError("deadline was extended")
        except monitor.MonitorError:
            pass
        assert call.call_count == 1
        sleep.assert_not_called()
    for command in (["gh", "pr", "merge", "1"], ["gh", "api", "--method", "POST"]):
        with patch.object(obj, name, side_effect=fail) as call, patch.object(monitor.time, "sleep") as sleep:
            try:
                runner(command, 30)
                raise AssertionError("write unexpectedly succeeded")
            except monitor.MonitorError:
                pass
            assert call.call_count == 1
            sleep.assert_not_called()

for message in ("HTTP 401: auth", "HTTP 403: forbidden", "HTTP 429: rate limit", "HTTP 500: server",
                "message mentions HTTP 504: not HTTP diagnostic", "GraphQL: malformed query"):
    with patch.object(monitor.subprocess, "run", return_value=response(1, message)) as call:
        try:
            monitor.run(query)
            raise AssertionError("permanent error passed")
        except monitor.MonitorError:
            pass
        assert call.call_count == 1

with patch.object(monitor.subprocess, "run", side_effect=[response(1, "HTTP 504: gateway"), response(0, stdout="[]")]) as call, \
     patch.object(monitor.time, "monotonic", side_effect=[0, 0, 10, 11]), patch.object(monitor.time, "sleep"):
    assert monitor.run(query) == "[]"
    assert [c.kwargs["timeout"] for c in call.call_args_list] == [90, 79]

with patch.object(monitor, "_bounded_run_once", side_effect=[monitor.GatewayError("gateway"), "[]"]) as call, \
     patch.object(monitor.time, "monotonic", side_effect=[0, 0, 8, 9]), patch.object(monitor.time, "sleep"):
    assert monitor.bounded_run(query, 30) == "[]"
    assert [c.args[1] for c in call.call_args_list] == [30, 21]

with patch.object(monitor.subprocess, "run", side_effect=subprocess.TimeoutExpired(query, 90)) as call:
    try:
        monitor.run(query)
        raise AssertionError("timeout passed")
    except monitor.MonitorError:
        pass
    assert call.call_count == 1

for failure in (monitor.MonitorError("output exceeds bound"), monitor.MonitorError("timeout")):
    with patch.object(monitor, "_bounded_run_once", side_effect=failure) as call:
        try:
            monitor.bounded_run(query, 30)
            raise AssertionError("invalid observation passed")
        except monitor.MonitorError:
            pass
        assert call.call_count == 1

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    config = {"repositories": ["example/one", "example/two"], "project": None}
    with patch.object(monitor.subprocess, "run", return_value=response(0, stdout="[]")):
        monitor.poll(root, config)
    original = (root / "checkpoint.json").read_bytes()
    for results in ([response(0, stdout="[]")] + [response(1, "HTTP 504: gateway", "[]")] * 3,
                    [response(0, stdout="not JSON")]):
        with patch.object(monitor.subprocess, "run", side_effect=results) as call, patch.object(monitor.time, "sleep"):
            try:
                monitor.poll(root, config)
                raise AssertionError("partial/malformed portfolio passed")
            except monitor.MonitorError:
                pass
            assert call.call_count == len(results)
        assert (root / "checkpoint.json").read_bytes() == original

with patch.object(monitor.subprocess, "run", side_effect=[response(1, "HTTP 503: gateway"),
        response(0, stdout=json.dumps({"items": [], "totalCount": 0}))]) as call, patch.object(monitor.time, "sleep"):
    monitor.project_snapshot({"owner": "example", "number": 42})
    assert call.call_count == 2
print("monitor gateway retry tests: PASS")
PY

printf 'orchestrator-monitor tests: PASS\n'
