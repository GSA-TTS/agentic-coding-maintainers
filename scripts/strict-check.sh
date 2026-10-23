#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

require_version() {
  local tool="$1" actual="$2" expected
  if ! expected="$(python3 -I -B -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' \
    "${STRICT_CHECK_PIN_FILE:-tools/precommit-versions.json}" "$tool")"; then
    printf 'UNVERIFIED: %s pin could not be read\n' "$tool" >&2
    exit 3
  fi
  [[ -n "$actual" && -n "$expected" && "$expected" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    printf 'UNVERIFIED: %s version measurement or pinned value is empty/malformed\n' "$tool" >&2
    exit 3
  }
  [[ "$actual" == "$expected" ]] || {
    printf 'ERROR: %s version %s; expected %s\n' "$tool" "$actual" "$expected" >&2
    exit 3
  }
}

if [[ "${STRICT_CHECK_VALIDATE_ONLY:-}" == 1 ]]; then
  # Test-only entry: exercise the same version guard without invoking local
  # scanners or external services. Never used by the pre-commit hook.
  [[ $# -eq 2 ]] || { echo 'UNVERIFIED: version test needs tool and actual value' >&2; exit 3; }
  require_version "$1" "$2"
  exit 0
fi

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
