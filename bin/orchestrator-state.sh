#!/usr/bin/env bash
set -euo pipefail
refuse() {
  printf '%s\n' 'orchestrator: UNVERIFIED - shared authority root required' >&2
  exit 3
}

# Only this exact help invocation bypasses admission; it never dispatches state.
if [[ $# -eq 1 && $1 == --help ]]; then
  printf '%s\n' 'usage: orchestrator-state.sh [state arguments]' \
    'Linked worktrees require WORKSPACE_ORCHESTRATOR_ROOT naming their physical primary checkout.'
  exit 0
fi

ROOT="$(cd -- "$(dirname "$0")/.." 2>/dev/null && pwd -P)" || refuse

common_dir() (
  # Metadata-only Git: no inherited identity/config, discovery, hooks or monitor.
  for name in ${!GIT_@}; do unset "$name"; done
  export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
  export GIT_CONFIG_NOSYSTEM=1 GIT_OPTIONAL_LOCKS=0
  git -c core.fsmonitor=false -c core.hooksPath=/dev/null \
    --git-dir="$1/.git" --work-tree="$1" \
    rev-parse --path-format=absolute --git-common-dir 2>/dev/null
)

if [[ ${WORKSPACE_ORCHESTRATOR_ROOT+x} ]]; then
  authority="$WORKSPACE_ORCHESTRATOR_ROOT"
  [[ $authority == /* && -d $authority && $authority != / ]] || refuse
  physical="$(cd -- "$authority" 2>/dev/null && pwd -P)" || refuse
  [[ $authority == "$physical" && -d $authority/.git ]] || refuse
  [[ -d $ROOT/.git || -f $ROOT/.git ]] || refuse
  source_common="$(common_dir "$ROOT")" || refuse
  authority_common="$(common_dir "$authority")" || refuse
  source_common="$(cd -- "$source_common" 2>/dev/null && pwd -P)" || refuse
  authority_common="$(cd -- "$authority_common" 2>/dev/null && pwd -P)" || refuse
  [[ $authority_common == "$authority/.git" && $source_common == "$authority_common" ]] || refuse
else
  # list/show also initialize state directories. Refuse before skill dispatch.
  [[ ! -f $ROOT/.git ]] || refuse
  authority="$ROOT"
fi

export WORKSPACE_ORCHESTRATOR_ROOT="$authority"
exec "$ROOT/.agents/skills/workspace-orchestrator/run.sh" state "$@"
