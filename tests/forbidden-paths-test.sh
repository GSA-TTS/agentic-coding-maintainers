#!/usr/bin/env bash
# The forbidden-path rule was previously an inline Makefile grep with NO test.
# An unexercised refusal is indistinguishable from an absent one: it can stop
# refusing (a pattern edit, an escaping mistake) and every run still prints
# PASS, because nothing in the tree happens to match.
#
# So assert BOTH directions against the one shared definition:
#   - each hazard class is still refused
#   - maintainer run records / journals are NOT refused
# The second direction is the point of the SOC-adjacent relaxation: this
# repository holds maintainer workflow for the agentic-coding repositories, and
# a filename rule that refuses operational records refuses its own purpose.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PATTERN="$("$ROOT/scripts/forbidden-paths.sh" --pattern)"
pass=0
fail=0

ok()  { printf '  ok   %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  FAIL %s\n' "$1"; fail=$((fail+1)); }

# matches <path> — does the shared pattern reject it?
matches() { printf '%s\n' "$1" | grep -qE "$PATTERN"; }

must_refuse() {
  if matches "$1"; then ok "refuses $1"; else bad "does NOT refuse $1 ($2)"; fi
}
must_allow() {
  if matches "$1"; then bad "refuses $1 — but $2"; else ok "allows $1"; fi
}

echo "== forbidden paths: hazards stay refused =="
must_refuse 'HANDOFF.md'                        'rolling session scratchpad'
must_refuse 'HANDOFF-ARCHIVE.md'                'archived scratchpad'
must_refuse 'docs/HANDOFF.md'                   'nested scratchpad'
must_refuse '.env'                              'environment secrets'
must_refuse '.env.local'                        'environment secrets'
must_refuse 'tools/ci/.env.production'          'nested environment secrets'
must_refuse '.env.staging'                      'any .env suffix is secrets'
must_refuse '.env.example.bak'                  'a backup of an example is not an example'
must_refuse 'host.pem'                          'key material'
must_refuse 'certs/corp.crt'                    'key material'
must_refuse 'a/b/client.key'                    'key material'
must_refuse 'bundle.p12'                        'key material'
must_refuse 'bundle.pfx'                        'key material'
must_refuse 'issue-draft-357.md'                'unposted issue draft'
must_refuse 'docs/issue_draft_notes.md'         'unposted issue draft'
must_refuse 'notes-issuedraft.txt'              'unposted issue draft'
must_refuse '__pycache__/x.pyc'                 'tool cache'
must_refuse 'a/__pycache__/x.pyc'               'nested tool cache'
must_refuse '.pytest_cache/v/x'                 'tool cache'
must_refuse '.mypy_cache/x'                     'tool cache'
must_refuse '.ruff_cache/x'                     'tool cache'
must_refuse '.nexus-agents/state.json'          'external tool state'

echo
echo "== forbidden paths: maintainer workflow records stay allowed =="
must_allow 'docs/journal/2026-09.md'            'a maintainer run journal is this repo purpose'
must_allow 'docs/journal/engagement-2026-09.md' 'naming a maintenance engagement is not a hazard'
must_allow 'docs/ENGAGEMENT-RUNBOOK.md'         'a runbook is workflow, not an artifact leak'
must_allow 'orchestrator.example.json'          'a placeholder config must be trackable'
must_allow '.env.example'                       'a documented example env must be trackable'
must_allow 'docs/MACOS-GITHUB-TLS.md'           'ordinary documentation'
must_allow 'scripts/forbidden-paths.sh'         'the rule definition itself'
must_allow 'tools/precommit-versions.json'      'pinned tool versions'

echo
echo "== forbidden paths: --check agrees with --pattern =="
# A fixture that matches must actually make --check fail, so the two entry
# points cannot disagree. Use an untracked file: --check reads --others too.
probe="$ROOT/.forbidden-probe-issue-draft.md"
printf 'probe\n' > "$probe"
set +e
"$ROOT/scripts/forbidden-paths.sh" --check >/dev/null 2>&1
rc=$?
set -e
mkdir -p "$ROOT/.import"
mv "$probe" "$ROOT/.import/forbidden-probe-removed.md"
if [[ "$rc" -ne 0 ]]; then
  ok "--check fails when a forbidden path is present"
else
  bad "--check passed with a forbidden path present (rule not wired to the gate)"
fi

echo
echo "== $pass passed, $fail failed =="
[[ "$fail" -eq 0 ]]
