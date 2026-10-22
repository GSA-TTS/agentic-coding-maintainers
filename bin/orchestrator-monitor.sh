#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export WORKSPACE_ORCHESTRATOR_ROOT="${WORKSPACE_ORCHESTRATOR_ROOT:-$ROOT}"
for arg in "$@"; do
  if [[ "$arg" == --config ]]; then
    exec "$ROOT/.agents/skills/workspace-orchestrator/run.sh" monitor "$@"
  fi
done
config="${ORCHESTRATOR_CONFIG:-$ROOT/orchestrator.json}"
if [[ ! -f "$config" || -L "$config" ]]; then
  printf 'monitor: UNVERIFIED - missing or invalid monitor config: %s\n' "$config" >&2
  printf 'Copy orchestrator.example.json to orchestrator.json and review its targets.\n' >&2
  exit 3
fi
exec "$ROOT/.agents/skills/workspace-orchestrator/run.sh" monitor --config "$config" "$@"
