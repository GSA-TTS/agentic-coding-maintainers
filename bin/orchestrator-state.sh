#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export WORKSPACE_ORCHESTRATOR_ROOT="${WORKSPACE_ORCHESTRATOR_ROOT:-$ROOT}"
exec "$ROOT/.agents/skills/workspace-orchestrator/run.sh" state "$@"
