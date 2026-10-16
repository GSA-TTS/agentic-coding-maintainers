#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fixture_bin="$ROOT/tests/fixtures/portfolio-bin"

output="$(cd / && PATH="$fixture_bin:/usr/bin:/bin" PORTFOLIO_STUB_MODE=success bash "$ROOT/run.sh" portfolio-status)"
grep -q 'Coverage: 3 epic issue(s) across 3 repo(s)' <<<"$output"
output="$(PATH="$fixture_bin:/usr/bin:/bin" PORTFOLIO_STUB_MODE=success "$ROOT/bin/portfolio-status.sh")"
grep -Eq '^Evidence timestamp: [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' <<<"$output"
grep -q 'In Progress  patterns#357' <<<"$output"
grep -q 'patterns#357 \[Blocked\]' <<<"$output"
grep -q 'Catalog epic ?\[31mFORGED' <<<"$output"
grep -q 'FORGED?' <<<"$output"
grep -q 'https://github.com/GSA-TTS/agentic-coding-patterns/issues/357' <<<"$output"
if grep -q 'attacker.invalid' <<<"$output"; then
  printf 'untrusted portfolio URL leaked into output\n' >&2
  exit 1
fi
if printf '%s' "$output" | LC_ALL=C grep -q $'\033'; then
  printf 'raw ANSI escape leaked into portfolio output\n' >&2
  exit 1
fi
grep -q 'Cancelled    playbook#999.*BOARD/LIVE MISMATCH' <<<"$output"
grep -q 'Todo         quickstart#235' <<<"$output"
grep -q 'quickstart#235.*BOARD/LIVE MISMATCH' <<<"$output"
grep -q 'type=Test; area=SBX/Environment' <<<"$output"
grep -q 'Coverage: 3 epic issue(s) across 3 repo(s)' <<<"$output"
grep -q 'Parent/Sub-issues progress: unavailable' <<<"$output"
if grep -q 'other/repo' <<<"$output"; then
  printf 'unexpected repository leaked into portfolio output\n' >&2
  exit 1
fi
if grep -q 'patterns#230' <<<"$output"; then
  printf 'epic-labeled PR leaked into portfolio output\n' >&2
  exit 1
fi

set +e
PATH="$fixture_bin:/usr/bin:/bin" PORTFOLIO_STUB_MODE=malformed "$ROOT/bin/portfolio-status.sh" >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 3 ]]

for mode in empty failure malformed-shape errors bad-errors truncated malformed-field malformed-field-name malformed-field-value malformed-label-name bad-total repeated-cursor bad-state bad-number bad-title bad-page-info; do
  set +e
  PATH="$fixture_bin:/usr/bin:/bin" PORTFOLIO_STUB_MODE="$mode" "$ROOT/bin/portfolio-status.sh" >/dev/null 2>&1
  rc=$?
  set -e
  [[ "$rc" -eq 3 ]]
done

start="$(python3 -c 'import time; print(time.monotonic())')"
set +e
PATH="$fixture_bin:/usr/bin:/bin" PORTFOLIO_STUB_MODE=sleep CROSS_REPO_EPIC_TEST_TIMEOUT_SECONDS=0.1 "$ROOT/bin/portfolio-status.sh" >/dev/null 2>&1
rc=$?
set -e
elapsed="$(python3 -c "import time; print(time.monotonic() - $start)")"
[[ "$rc" -eq 3 ]]
python3 -c "import sys; sys.exit(0 if $elapsed < 1.5 else 1)"

for timeout in 0 6 invalid; do
  set +e
  PATH="$fixture_bin:/usr/bin:/bin" CROSS_REPO_EPIC_TEST_TIMEOUT_SECONDS="$timeout" "$ROOT/bin/portfolio-status.sh" >/dev/null 2>&1
  rc=$?
  set -e
  [[ "$rc" -eq 3 ]]
done

set +e
stderr="$(PATH="$fixture_bin:/usr/bin:/bin" PORTFOLIO_STUB_MODE=failure "$ROOT/bin/portfolio-status.sh" 2>&1 >/dev/null)"
rc=$?
set -e
[[ "$rc" -eq 3 ]]
if printf '%s' "$stderr" | LC_ALL=C grep -q $'\033'; then
  printf 'raw ANSI escape leaked into portfolio error output\n' >&2
  exit 1
fi

draft_output="$(PATH="$fixture_bin:/usr/bin:/bin" PORTFOLIO_STUB_MODE=draft-item "$ROOT/bin/portfolio-status.sh")"
grep -q 'patterns#1' <<<"$draft_output"

printf 'portfolio-status tests: PASS\n'
