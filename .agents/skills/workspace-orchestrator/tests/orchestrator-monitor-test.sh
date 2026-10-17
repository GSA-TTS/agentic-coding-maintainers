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

# Reject an interval that would accidentally hammer GitHub.
set +e
PATH="$FIXTURE:/usr/bin:/bin" python3 "$MON" --task-id monitor-test --config "$CONFIG" --loop --interval 10 >/dev/null 2>&1; rc=$?
set -e
[[ "$rc" -eq 2 ]]

# A successful but truncated Project response is UNVERIFIED, not unchanged.
set +e
run_monitor project-incomplete >/dev/null 2>&1; rc=$?
set -e
[[ "$rc" -eq 3 ]]

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

printf 'orchestrator-monitor tests: PASS\n'
