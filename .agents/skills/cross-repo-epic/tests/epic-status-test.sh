#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fixture_bin="$ROOT/tests/fixtures/epic-status-bin"
# Config-driven now: the tools read which repositories and which Project v2
# board to use. Point them at a fixture config so the suite never depends
# on the operator having a real orchestrator.json.
export CROSS_REPO_EPIC_CONFIG="$ROOT/tests/fixtures/epic-config.json"

output="$(cd / && PATH="$fixture_bin:/usr/bin:/bin" EPIC_STUB_MODE=success bash "$ROOT/run.sh" epic-status patterns#357)"
grep -q 'Coverage: COMPLETE' <<<"$output"
output="$(PATH="$fixture_bin:/usr/bin:/bin" EPIC_STUB_MODE=success "$ROOT/bin/epic-status.sh" patterns#357)"
grep -Eq '^Evidence timestamp: [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' <<<"$output"
grep -q 'GSA-TTS/agentic-coding-patterns#357' <<<"$output"
grep -q '2 total; 1 open; 1 closed' <<<"$output"
grep -q 'GSA-TTS/agentic-coding-quickstart#503' <<<"$output"
grep -q 'https://github.com/GSA-TTS/agentic-coding-patterns/issues/357' <<<"$output"
grep -q 'https://github.com/GSA-TTS/agentic-coding-quickstart/issues/503' <<<"$output"
grep -q 'Board Flag: Blocked' <<<"$output"
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

# ---------------------------------------------------------------------------
# Config-driven behaviour and scope confinement.
#
# Every assertion above uses a fixture matching the portfolio this skill was
# originally written for, which cannot distinguish "reads config" from
# "hardcodes the same values config happens to contain". Mutation testing
# proved the gap: removing the allow-set check, the board-identity check, or
# the regex escaping left the suite GREEN. Four of those are security controls.
#
# The block below runs the same tool against a different portfolio — a
# USER-owned board, repositories in two owners — and asserts each control.
# ---------------------------------------------------------------------------
generic_bin="$ROOT/tests/fixtures/generic-bin"
generic_cfg="$ROOT/tests/fixtures/generic-config.json"

generic_output="$(PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$generic_cfg" "$ROOT/bin/epic-status.sh" api#11)"
# A configured alias resolves to its full owner/name.
grep -q 'Epic: acme/api#11' <<<"$generic_output"
# Board metadata comes from the configured board.
grep -q 'Board Status: Todo' <<<"$generic_output"
# A sub-issue in a DIFFERENT owner than the epic still resolves.
grep -q 'other-org/infra#5' <<<"$generic_output"
# The original portfolio must not appear when another one is configured.
if grep -qE 'GSA-TTS|patterns#|quickstart#|playbook#' <<<"$generic_output"; then
  printf 'output references the original portfolio despite a different config\n' >&2
  exit 1
fi

# SCOPE: a reference to an unconfigured repository must be refused BEFORE any
# network call, and the usage hint must list the operator's own aliases.
set +e
unconf_err="$(PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$generic_cfg" "$ROOT/bin/epic-status.sh" stranger/repo#99 2>&1 >/dev/null)"
unconf_rc=$?
set -e
if [[ "$unconf_rc" -ne 2 ]]; then
  printf 'unconfigured repository reference gave rc=%s, want 2\n' "$unconf_rc" >&2
  exit 1
fi
grep -q 'api#N' <<<"$unconf_err" || {
  printf 'usage hint does not list configured aliases\n' >&2
  exit 1
}

# BOARD IDENTITY: a board item with the configured NUMBER but a different owner
# login, or the same login with a different owner kind, must not match. A bare
# number is ambiguous — two owners can each have a project #7 — so forging
# either half must fail.
for mode in board-wrong-owner board-wrong-kind; do
  set +e
  board_err="$(PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$generic_cfg" GENERIC_STUB_MODE="$mode" "$ROOT/bin/epic-status.sh" api#11 2>&1 >/dev/null)"
  board_rc=$?
  set -e
  if [[ "$board_rc" -eq 0 ]]; then
    printf 'board mode %s was accepted as the configured board\n' "$mode" >&2
    exit 1
  fi
  if ! grep -q 'not present on the configured board' <<<"$board_err"; then
    printf 'board mode %s gave an unexpected error: %s\n' "$mode" "$board_err" >&2
    exit 1
  fi
done

# SCOPE: a sub-issue outside the configured portfolio must be refused, not
# silently listed. Sub-issues are attacker-adjacent: anyone who can file an
# issue in a watched repo can add a child pointing anywhere.
set +e
child_err="$(PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$generic_cfg" GENERIC_STUB_MODE=child-outside "$ROOT/bin/epic-status.sh" api#11 2>&1 >/dev/null)"
child_rc=$?
set -e
if [[ "$child_rc" -ne 3 ]]; then
  printf 'out-of-portfolio sub-issue gave rc=%s, want 3\n' "$child_rc" >&2
  exit 1
fi
grep -q 'outside the allowed portfolio' <<<"$child_err" || {
  printf 'out-of-portfolio sub-issue was not refused by scope: %s\n' "$child_err" >&2
  exit 1
}

# Config failure modes: an unreadable portfolio must never render as an empty
# one, and a symlinked config must be refused (it could redirect scope).
epic_cfg_dir="$(mktemp -d)"
printf 'not json\n' > "$epic_cfg_dir/malformed.json"
ln -s "$generic_cfg" "$epic_cfg_dir/linked.json"
for cfg in "$epic_cfg_dir/absent.json" "$epic_cfg_dir/malformed.json" "$epic_cfg_dir/linked.json"; do
  set +e
  cfg_err="$(PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$cfg" "$ROOT/bin/epic-status.sh" api#11 2>&1 >/dev/null)"
  rc=$?
  set -e
  if [[ "$rc" -ne 3 ]]; then
    printf 'config %s gave rc=%s, want 3\n' "$(basename "$cfg")" "$rc" >&2
    exit 1
  fi
  if ! grep -q 'UNVERIFIED' <<<"$cfg_err"; then
    printf 'config %s did not report UNVERIFIED\n' "$(basename "$cfg")" >&2
    exit 1
  fi
done
rm -rf "$epic_cfg_dir"

# REGEX ESCAPING: repository names may contain regex metacharacters (the schema
# permits `.`, `-`, `_`). An unescaped alternation would turn `acme/a.i` into
# the pattern `a.i`, where `.` matches ANY character — so `aXi#1` would resolve
# to a repository the operator never configured. This is the only assertion
# that can kill the re.escape call, because it needs a metachar in the config.
metachar_cfg="$ROOT/tests/fixtures/metachar-config.json"
set +e
metachar_err="$(PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$metachar_cfg" "$ROOT/bin/epic-status.sh" 'aXi#1' 2>&1 >/dev/null)"
metachar_rc=$?
set -e
if [[ "$metachar_rc" -ne 2 ]]; then
  printf 'a wildcard-expanded alias was accepted (rc=%s): %s\n' "$metachar_rc" "$metachar_err" >&2
  exit 1
fi
if ! grep -q 'expected ' <<<"$metachar_err"; then
  printf 'alias aXi was not refused by the parser: %s\n' "$metachar_err" >&2
  exit 1
fi
# The same hazard exists in the FULL owner/name pattern and in the URL form,
# which reuse the other alternation. Three references, three branches.
for hostile in 'acme/aXi#1' 'https://github.com/acme/aXi/issues/1'; do
  set +e
  PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$metachar_cfg" "$ROOT/bin/epic-status.sh" "$hostile" >/dev/null 2>&1
  hostile_rc=$?
  set -e
  if [[ "$hostile_rc" -ne 2 ]]; then
    printf 'wildcard-expanded reference %s accepted (rc=%s); re.escape missing?\n' "$hostile" "$hostile_rc" >&2
    exit 1
  fi
  # Both guards exit 2, so the rc alone cannot tell which refused. Require the
  # PARSE refusal: if escaping regressed, parse_ref would accept the reference
  # and the allow-set check downstream would report "unsupported repository"
  # instead. Asserting the message is what makes the escaping killable.
  set +e
  hostile_err="$(PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$metachar_cfg" "$ROOT/bin/epic-status.sh" "$hostile" 2>&1 >/dev/null)"
  set -e
  if ! grep -q 'expected ' <<<"$hostile_err"; then
    printf 'reference %s was not refused by the parser (escaping regressed?): %s\n' "$hostile" "$hostile_err" >&2
    exit 1
  fi
done

# The legitimate dotted alias must still work, so escaping did not over-reject.
set +e
metachar_ok="$(PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$metachar_cfg" "$ROOT/bin/epic-status.sh" 'a.i#1' 2>&1 >/dev/null)"
metachar_ok_rc=$?
set -e
if [[ "$metachar_ok_rc" -eq 2 ]]; then
  printf 'the configured dotted alias was rejected as a usage error: %s\n' "$metachar_ok" >&2
  exit 1
fi

printf 'epic-status tests: PASS\n'
