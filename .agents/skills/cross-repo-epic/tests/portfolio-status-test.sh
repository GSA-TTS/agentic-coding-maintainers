#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fixture_bin="$ROOT/tests/fixtures/portfolio-bin"
# Config-driven now: the tools read which repositories and which Project v2
# board to use. Point them at a fixture config so the suite never depends
# on the operator having a real orchestrator.json.
export CROSS_REPO_EPIC_CONFIG="$ROOT/tests/fixtures/portfolio-config.json"

output="$(cd / && PATH="$fixture_bin:/usr/bin:/bin" PORTFOLIO_STUB_MODE=success bash "$ROOT/run.sh" portfolio-status)"
grep -q 'Coverage: 3 epic candidate(s) across 3 repo(s)' <<<"$output"
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
grep -q 'Coverage: 3 epic candidate(s) across 3 repo(s)' <<<"$output"
grep -q 'Parent/Sub-issues progress: unavailable' <<<"$output"

# A complete first:1 presence probe identifies an unlabeled ordinary parent
# as a CANDIDATE, not a verified epic. Missing or contradictory presence data
# must never silently mean "not an epic".
candidate="$(PATH="$fixture_bin:/usr/bin:/bin" PORTFOLIO_STUB_MODE=subissue-candidate "$ROOT/bin/portfolio-status.sh")"
grep -q 'patterns#77' <<<"$candidate"
grep -q 'EPIC CANDIDATE (sub-issues): 2 child(ren)' <<<"$candidate"
grep -q 'Coverage: 1 epic candidate(s)' <<<"$candidate"
for mode in no-subissues missing-subissues contradictory-subissues null-child-probe bad-subissue-page missing-subissue-cursor; do
  set +e
  diagnostic="$(PATH="$fixture_bin:/usr/bin:/bin" PORTFOLIO_STUB_MODE="$mode" "$ROOT/bin/portfolio-status.sh" 2>&1)"
  rc=$?
  set -e
  [[ "$rc" -eq 3 && "$diagnostic" == *UNVERIFIED* ]] || {
    printf 'portfolio mode %s reported rc=%s, expected UNVERIFIED\n' "$mode" "$rc" >&2
    exit 1
  }
done
grep -q 'EPIC CANDIDATE (label/title)' <<<"$output"
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

# ---------------------------------------------------------------------------
# Config-driven behaviour.
#
# Every assertion above uses a fixture whose repositories and board match the
# portfolio this skill was originally written for. That cannot distinguish
# "reads config" from "hardcodes the same values config happens to contain".
# The block below runs the SAME tool against a deliberately different
# portfolio: a USER-owned board, two distinct repository owners, and an alias
# set with no shared prefix.
# ---------------------------------------------------------------------------
generic_bin="$ROOT/tests/fixtures/generic-bin"
generic_cfg="$ROOT/tests/fixtures/generic-config.json"

generic_output="$(PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$generic_cfg" "$ROOT/bin/portfolio-status.sh")"
grep -q 'Project v2 acme-dev/#7 epic coordination view' <<<"$generic_output"
grep -q 'Todo         api#11' <<<"$generic_output"
grep -q 'In Progress  infra#22' <<<"$generic_output"
grep -q 'https://github.com/other-org/infra/issues/22' <<<"$generic_output"
# SCOPE CONTROL first, and with its own message. The derived allow-set is the
# one security-relevant part of this change: a board item from an unconfigured
# repository must never be rendered. Ordering matters — when this regressed, the
# leak also changed the epic count, so a coverage assertion placed first failed
# instead and reported a count mismatch rather than naming the scope leak. An
# assertion that only catches a regression via a side effect stops being
# load-bearing the moment someone updates the expected count.
if grep -q 'stranger/repo' <<<"$generic_output"; then
  printf 'board item from an unconfigured repository leaked into output\n' >&2
  exit 1
fi
if grep -q '#99' <<<"$generic_output"; then
  printf 'unconfigured epic number leaked into output\n' >&2
  exit 1
fi
# The original portfolio must NOT appear when another one is configured.
if grep -qE 'GSA-TTS|patterns#|quickstart#|playbook#' <<<"$generic_output"; then
  printf 'output references the original portfolio despite a different config\n' >&2
  exit 1
fi

grep -q 'Coverage: 2 epic candidate(s) across 2 repo(s)' <<<"$generic_output"
grep -q 'Coverage note: no epic candidate on the board for web' <<<"$generic_output"

# Resolve-step failure modes. Each must be UNVERIFIED (exit 3), never an empty
# board rendered as a clean run.
# The resolved node id is interpolated into the NEXT GraphQL query, so it is
# shape-checked before reuse. Assert that specific refusal: without it the id
# still fails later (the stub rejects an unknown id), which looks like a pass
# while the guard is gone. Mutation-verified — deleting PROJECT_ID_RE changes
# this message from "unexpected shape" to "could not read the project board".
set +e
badid_err="$(PATH="$fixture_bin:/usr/bin:/bin" PORTFOLIO_STUB_MODE=resolve-bad-id "$ROOT/bin/portfolio-status.sh" 2>&1 >/dev/null)"
badid_rc=$?
set -e
if [[ "$badid_rc" -ne 3 ]]; then
  printf 'resolve-bad-id gave rc=%s, want 3\n' "$badid_rc" >&2
  exit 1
fi
if ! grep -q 'unexpected shape' <<<"$badid_err"; then
  printf 'a malformed node id was not refused by shape; got: %s\n' "$badid_err" >&2
  exit 1
fi

for mode in resolve-failure resolve-malformed resolve-missing resolve-bad-id resolve-errors; do
  set +e
  resolve_err="$(PATH="$fixture_bin:/usr/bin:/bin" PORTFOLIO_STUB_MODE="$mode" "$ROOT/bin/portfolio-status.sh" 2>&1 >/dev/null)"
  rc=$?
  set -e
  if [[ "$rc" -ne 3 ]]; then
    printf 'resolve mode %s gave rc=%s, want 3\n' "$mode" "$rc" >&2
    exit 1
  fi
  if ! grep -q 'UNVERIFIED' <<<"$resolve_err"; then
    printf 'resolve mode %s did not report UNVERIFIED\n' "$mode" >&2
    exit 1
  fi
done

# Config failure modes. A missing or malformed config must refuse, because an
# unreadable portfolio and an empty one look identical in output.
tmp_cfg_dir="$(mktemp -d)"
printf 'not json\n' > "$tmp_cfg_dir/malformed.json"
printf '{"schema_version":1,"repositories":["acme/api"],"project":null}\n' > "$tmp_cfg_dir/noboard.json"
printf '{"schema_version":1,"repositories":["acme/api"],"project":{"owner":"o","number":1,"owner_type":"neither"}}\n' > "$tmp_cfg_dir/badtype.json"
printf '{"schema_version":1,"repositories":[["acme/api"]],"project":{"owner":"o","number":1}}\n' > "$tmp_cfg_dir/unhashable.json"
for cfg in "$tmp_cfg_dir/absent.json" "$tmp_cfg_dir/malformed.json" "$tmp_cfg_dir/noboard.json" "$tmp_cfg_dir/badtype.json" "$tmp_cfg_dir/unhashable.json"; do
  set +e
  cfg_err="$(PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$cfg" "$ROOT/bin/portfolio-status.sh" 2>&1 >/dev/null)"
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
# A symlinked config must be REFUSED. Whatever can write the workspace could
# otherwise redirect which repositories this tool treats as in-scope, which is
# a scope-confinement bypass rather than a convenience. Mutation-verified:
# removing the refusal makes this assertion fail.
ln -s "$generic_cfg" "$tmp_cfg_dir/linked.json"
set +e
link_err="$(PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$tmp_cfg_dir/linked.json" "$ROOT/bin/portfolio-status.sh" 2>&1 >/dev/null)"
link_rc=$?
set -e
if [[ "$link_rc" -ne 3 ]]; then
  printf 'symlinked config gave rc=%s, want 3\n' "$link_rc" >&2
  exit 1
fi
if ! grep -q 'symlink' <<<"$link_err"; then
  printf 'symlinked config was not refused as a symlink; got: %s\n' "$link_err" >&2
  exit 1
fi

# The absent-config message must tell an operator what to do about it.
set +e
absent_err="$(PATH="$generic_bin:/usr/bin:/bin" CROSS_REPO_EPIC_CONFIG="$tmp_cfg_dir/absent.json" "$ROOT/bin/portfolio-status.sh" 2>&1 >/dev/null)"
set -e
if ! grep -q 'orchestrator.example.json' <<<"$absent_err"; then
  printf 'absent-config error does not name the example to copy\n' >&2
  exit 1
fi
rm -rf "$tmp_cfg_dir"

printf 'portfolio-status tests: PASS\n'
