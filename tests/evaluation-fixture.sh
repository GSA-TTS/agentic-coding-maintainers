#!/usr/bin/env bash
# Shared only by the evaluator test: stage owned fixtures, never delete them.

evaluation_fixture_stage() {
  local fixture=$1 outbox=$2 result=$3 checks=$4 destination size
  if [[ ! -d "$fixture" || -L "$fixture" || ! -f "$fixture/MANIFEST.md" || -L "$fixture/MANIFEST.md" ]]; then
    builtin printf 'UNVERIFIED: evaluation fixture or manifest is unavailable; retained_active=%s; synthetic evaluator test data, operator disposal required\n' "$fixture" >&2
    return 3
  fi
  size="$(du -sk "$fixture")" || {
    echo 'UNVERIFIED: evaluation fixture size could not be measured' >&2
    return 3
  }
  if ! printf '\nExit: %s; checks: %s\nSize before staging (KiB and source): %s\n' "$result" "$checks" "$size" >> "$fixture/MANIFEST.md"; then
    builtin printf 'UNVERIFIED: evaluation fixture manifest could not be finalized; retained_active=%s; synthetic evaluator test data, operator disposal required\n' "$fixture" >&2
    return 3
  fi
  destination="$(mktemp -d "$outbox/$(date -u +%Y-%m-%d)-evaluation.XXXXXX")" || {
    echo 'UNVERIFIED: evaluation disposal destination could not be created' >&2
    return 3
  }
  # Put the rationale at the disposal root too, before moving the working tree.
  if ! cp "$fixture/MANIFEST.md" "$destination/MANIFEST.md"; then
    echo "UNVERIFIED: evaluation disposal manifest unavailable; destination=$destination" >&2
    return 3
  fi
  if ! mv "$fixture" "$destination/fixture"; then
    echo "UNVERIFIED: evaluation fixture move failed; active=$fixture destination=$destination" >&2
    return 3
  fi
  if [[ -e "$fixture" || -L "$fixture" || ! -d "$destination/fixture" || -L "$destination/fixture" ]]; then
    echo "UNVERIFIED: evaluation active path survived disposal; active=$fixture destination=$destination" >&2
    return 3
  fi
  printf 'evaluation_fixture_staged=%s\n' "$destination" >&2
}

evaluation_fixture_initial_manifest() {
  if ! printf '# Evaluation test fixture\n\nCreated by tests/evaluate-workflow-test.sh. All contents are synthetic test data. No real maintainer evidence or user files are referenced. Safe for operator disposal.\n' > "$1/MANIFEST.md"; then
    builtin printf 'UNVERIFIED: evaluation initial manifest failed; retained_active=%s; synthetic evaluator test data, operator disposal required\n' "$1" >&2
    return 3
  fi
}

evaluation_fixture_finish() {
  local result=$?
  trap - EXIT HUP INT TERM
  # Globals are intentionally supplied by the caller before installing the trap.
  # shellcheck disable=SC2153
  evaluation_fixture_stage "$FIXTURE" "$OUTBOX" "$result" "$CHECKS" || exit 3
  exit "$result"
}
