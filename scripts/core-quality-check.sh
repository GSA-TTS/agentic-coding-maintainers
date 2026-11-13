#!/usr/bin/env bash
set -euo pipefail

python_roots=(
  .agents/skills/cross-repo-epic/bin
  .agents/skills/workspace-orchestrator/bin
  .agents/skills/federal-authority-research/bin
  scripts
)
ruff check --isolated --select E4,E7,E9,F,I "${python_roots[@]}"
pyright "${python_roots[@]}"
bandit -q -ll -r "${python_roots[@]}" -x '*/tests/*'
git ls-files -z -- '*.sh' '.agents/skills/*/tests/fixtures/*/gh' | xargs -0 shellcheck

shopt -s nullglob
workflows=(.github/workflows/*.yml .github/workflows/*.yaml)
((${#workflows[@]})) || { echo 'ERROR: no workflows found for actionlint/zizmor' >&2; exit 3; }
actionlint "${workflows[@]}"
zizmor --offline --format plain "${workflows[@]}"

echo 'core quality checks: PASS'
