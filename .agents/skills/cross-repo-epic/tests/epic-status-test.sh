#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fixture_bin="$ROOT/tests/fixtures/epic-status-bin"

output="$(cd / && PATH="$fixture_bin:/usr/bin:/bin" EPIC_STUB_MODE=success bash "$ROOT/run.sh" epic-status patterns#357)"
grep -q 'Coverage: COMPLETE' <<<"$output"
output="$(PATH="$fixture_bin:/usr/bin:/bin" EPIC_STUB_MODE=success "$ROOT/bin/epic-status.sh" patterns#357)"
grep -Eq '^Evidence timestamp: [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' <<<"$output"
grep -q 'GSA-TTS/agentic-coding-patterns#357' <<<"$output"
grep -q '2 total; 1 open; 1 closed' <<<"$output"
grep -q 'GSA-TTS/agentic-coding-quickstart#503' <<<"$output"
grep -q 'https://github.com/GSA-TTS/agentic-coding-patterns/issues/357' <<<"$output"
grep -q 'https://github.com/GSA-TTS/agentic-coding-quickstart/issues/503' <<<"$output"
grep -q 'Project 120 Flag: Blocked' <<<"$output"
grep -q 'Coverage: COMPLETE' <<<"$output"
grep -q 'PR reviews/checks/mergeability: NOT CHECKED' <<<"$output"

empty_output="$(PATH="$fixture_bin:/usr/bin:/bin" EPIC_STUB_MODE=no-children "$ROOT/bin/epic-status.sh" patterns#357)"
grep -q '0 total; 0 open; 0 closed' <<<"$empty_output"

control_output="$(PATH="$fixture_bin:/usr/bin:/bin" EPIC_STUB_MODE=control-title "$ROOT/bin/epic-status.sh" patterns#357)"
if printf '%s' "$control_output" | LC_ALL=C grep -q $'\033'; then
  printf 'raw ANSI escape leaked into epic output\n' >&2
  exit 1
fi
grep -q 'FORGED?' <<<"$control_output"

for ref in \
  GSA-TTS/agentic-coding-patterns#357 \
  https://github.com/GSA-TTS/agentic-coding-patterns/issues/357; do
  PATH="$fixture_bin:/usr/bin:/bin" EPIC_STUB_MODE=success "$ROOT/bin/epic-status.sh" "$ref" >/dev/null
done

start="$(python3 -c 'import time; print(time.monotonic())')"
set +e
PATH="$fixture_bin:/usr/bin:/bin" EPIC_STUB_MODE=sleep CROSS_REPO_EPIC_TEST_TIMEOUT_SECONDS=0.1 "$ROOT/bin/epic-status.sh" patterns#357 >/dev/null 2>&1
rc=$?
set -e
elapsed="$(python3 -c "import time; print(time.monotonic() - $start)")"
[[ "$rc" -eq 3 ]]
python3 -c "import sys; sys.exit(0 if $elapsed < 1.5 else 1)"

for timeout in 0 6 invalid; do
  set +e
  PATH="$fixture_bin:/usr/bin:/bin" CROSS_REPO_EPIC_TEST_TIMEOUT_SECONDS="$timeout" "$ROOT/bin/epic-status.sh" patterns#357 >/dev/null 2>&1
  rc=$?
  set -e
  [[ "$rc" -eq 3 ]]
done

for ref in 357 other#357 patterns#0 patterns#2147483648 "patterns#$(printf '9%.0s' {1..100})" https://github.com/GSA-TTS/agentic-coding-patterns/pull/357; do
  set +e
  PATH="$fixture_bin:/usr/bin:/bin" "$ROOT/bin/epic-status.sh" "$ref" >/dev/null 2>&1
  rc=$?
  set -e
  [[ "$rc" -eq 2 ]]
done

for mode in failure malformed errors bad-errors missing repeated-cursor truncated-fields wrong-project malformed-project malformed-field malformed-field-name malformed-field-value malformed-label-name bad-total wrong-initial bad-state bad-issue-number bad-child-number bad-page-info bad-sub-page bad-project-page bad-field-page falsey-project duplicate-child changing-total identity-change title-change outside-child; do
  set +e
  PATH="$fixture_bin:/usr/bin:/bin" EPIC_STUB_MODE="$mode" "$ROOT/bin/epic-status.sh" patterns#357 >/dev/null 2>&1
  rc=$?
  set -e
  [[ "$rc" -eq 3 ]]
done

set +e
stderr="$(PATH="$fixture_bin:/usr/bin:/bin" EPIC_STUB_MODE=failure "$ROOT/bin/epic-status.sh" patterns#357 2>&1 >/dev/null)"
rc=$?
set -e
[[ "$rc" -eq 3 ]]
if printf '%s' "$stderr" | LC_ALL=C grep -q $'\033'; then
  printf 'raw ANSI escape leaked into epic error output\n' >&2
  exit 1
fi
if printf '%s' "$stderr" | LC_ALL=C grep -q $'\302\233'; then
  printf 'raw C1 CSI leaked into epic error output\n' >&2
  exit 1
fi

set +e
PATH="$fixture_bin:/usr/bin:/bin" EPIC_STUB_MODE=non-epic "$ROOT/bin/epic-status.sh" patterns#357 >/dev/null 2>&1
rc=$?
set -e
[[ "$rc" -eq 2 ]]

printf 'epic-status tests: PASS\n'
