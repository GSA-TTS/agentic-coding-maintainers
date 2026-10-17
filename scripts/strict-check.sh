#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

require_version() {
  local tool="$1" actual="$2" expected
  expected="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' \
    tools/precommit-versions.json "$tool")"
  [[ "$actual" == "$expected" ]] || {
    printf 'ERROR: %s version %s; expected %s\n' "$tool" "$actual" "$expected" >&2
    exit 3
  }
}

for tool in pre-commit ruff pyright bandit shellcheck gitleaks trivy actionlint zizmor; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: missing required tool: $tool" >&2; exit 3; }
done

require_version pre-commit "$(pre-commit --version | awk '{print $2}')"
require_version ruff "$(ruff --version | awk '{print $2}')"
require_version pyright "$(pyright --version | awk '{print $2}')"
require_version bandit "$(bandit --version | awk 'NR==1{print $2}')"
require_version shellcheck "$(shellcheck --version | awk '/^version:/{print $2}')"
require_version gitleaks "$(gitleaks version)"
require_version trivy "$(trivy --version | awk 'NR==1{print $2}')"
require_version actionlint "$(actionlint --version | awk 'NR==1{print $1}')"
require_version zizmor "$(zizmor --version | awk '{print $2}')"

make check
bash scripts/core-quality-check.sh
gitleaks git . --pre-commit --staged --config .gitleaks.toml --redact --no-banner
gitleaks git . --config .gitleaks.toml --redact --no-banner
trivy fs --scanners secret --exit-code 1 --quiet .

echo 'strict checks: PASS'
