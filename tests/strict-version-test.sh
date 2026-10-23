#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/strict-check.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/strict-version.XXXXXX")"
printf '{"trivy":""}\n' > "$TMP/empty.json"
printf '{"trivy":"0.76.1"}\n' > "$TMP/good.json"
printf 'not-json\n' > "$TMP/malformed.json"

assert_rc() {
  local want="$1"; shift
  set +e
  "$@" >/dev/null 2>&1
  local got=$?
  set -e
  [[ "$got" -eq "$want" ]] || { printf 'strict-version: expected rc=%s, got %s\n' "$want" "$got" >&2; exit 1; }
}

assert_rc 3 env STRICT_CHECK_VALIDATE_ONLY=1 STRICT_CHECK_PIN_FILE="$TMP/empty.json" "$SCRIPT" trivy ''
assert_rc 3 env STRICT_CHECK_VALIDATE_ONLY=1 STRICT_CHECK_PIN_FILE="$TMP/empty.json" "$SCRIPT" trivy '0.76.1'
assert_rc 3 env STRICT_CHECK_VALIDATE_ONLY=1 STRICT_CHECK_PIN_FILE="$TMP/malformed.json" "$SCRIPT" trivy '0.76.1'
assert_rc 3 env STRICT_CHECK_VALIDATE_ONLY=1 STRICT_CHECK_PIN_FILE="$TMP/good.json" "$SCRIPT" trivy ''
assert_rc 3 env STRICT_CHECK_VALIDATE_ONLY=1 STRICT_CHECK_PIN_FILE="$TMP/good.json" "$SCRIPT" trivy '0.76.0'
assert_rc 0 env STRICT_CHECK_VALIDATE_ONLY=1 STRICT_CHECK_PIN_FILE="$TMP/good.json" "$SCRIPT" trivy '0.76.1'
printf 'strict-version tests: PASS\n'
