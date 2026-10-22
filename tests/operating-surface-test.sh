#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
profiles="$ROOT/.agents/skills/workspace-orchestrator/profiles/opencode-v1"
agents="$ROOT/.opencode/agents"
pass=0
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

# A missing copy or a changed permission in either direction must not silently
# drift from the canonical role pack. Refuse an empty directory as unmeasured.
count=0
for source in "$profiles"/*.md; do
  [[ -f "$source" ]] || fail 'no canonical agent profiles found'
  target="$agents/${source##*/}"
  [[ -f "$target" && ! -L "$target" ]] || fail "missing or symlinked installed profile: ${source##*/}"
  cmp -s "$source" "$target" || fail "installed profile differs: ${source##*/}"
  count=$((count+1))
done
[[ "$count" -gt 0 ]] || fail 'zero profiles compared'
for target in "$agents"/*.md; do
  [[ -f "$target" ]] || fail 'no installed agent profiles found'
  [[ -f "$profiles/${target##*/}" ]] || fail "unreviewed installed agent: ${target##*/}"
done
pass=$((pass+1))

# Run a real dispatcher without network; verify it operates in this repository.
"$ROOT/bin/orchestrator-state.sh" reconcile >/dev/null || fail 'state reconcile failed'
pass=$((pass+1))

# Never fall back to the example. The absent-config state must say UNVERIFIED.
set +e
message="$(ORCHESTRATOR_CONFIG="$ROOT/.nonexistent-monitor-config.json" "$ROOT/bin/orchestrator-monitor.sh" --task-id probe 2>&1)"
rc=$?
set -e
[[ "$rc" -eq 3 && "$message" == *UNVERIFIED* ]] || fail "missing config: rc=$rc, output=$message"
pass=$((pass+1))

# The tracked example must be parseable and declare a bounded portfolio.
python3 - "$ROOT/orchestrator.example.json" <<'PY' || fail 'invalid example config'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data["schema_version"] == 1
assert 1 <= len(data["repositories"]) <= 50
assert len(set(data["repositories"])) == len(data["repositories"])
assert data["project"]["owner_type"] in ("organization", "user")
PY
pass=$((pass+1))
printf 'operating surface: PASS (%s measured checks, %s profiles)\n' "$pass" "$count"
