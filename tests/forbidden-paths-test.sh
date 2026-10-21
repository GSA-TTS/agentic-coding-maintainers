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
# -i mirrors the gate: scripts/forbidden-paths.sh --check uses grep -Ei.
matches() { printf '%s\n' "$1" | grep -qEi "$PATTERN"; }

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

# Key material with no extension, and credential stores. An SSH private key
# carries NO extension, which made it the likeliest accidental key commit and
# the widest hole in the original rule.
must_refuse 'id_rsa'                            'SSH private key, no extension'
must_refuse 'id_dsa'                            'SSH private key, no extension'
must_refuse 'id_ecdsa'                          'SSH private key, no extension'
must_refuse 'id_ed25519'                        'SSH private key, no extension'
must_refuse 'a/b/id_rsa'                        'nested SSH private key'
must_refuse '.netrc'                            'plaintext host credentials'
must_refuse '.npmrc'                            'may carry a registry token'
must_refuse '.pypirc'                           'may carry a registry token'
must_refuse '.htpasswd'                         'password hashes'
must_refuse 'credentials'                       'credential store'
must_refuse 'docs/credentials'                  'nested credential store'
must_refuse 'service-account.json'              'cloud service-account key'
must_refuse 'gcp-service-account-prod.json'     'cloud service-account key'
must_refuse 'cluster.kubeconfig'                'cluster credentials'
must_refuse 'app.jks'                           'Java keystore'
must_refuse 'store.keystore'                    'Java keystore'
must_refuse 'vpn.ovpn'                          'VPN profile with inline keys'
must_refuse 'key.p8'                            'PKCS#8 private key'
must_refuse 'cert.cer'                          'certificate'
must_refuse 'cert.der'                          'certificate'
must_refuse 'key.ppk'                           'PuTTY private key'
must_refuse 'signed.asc'                        'PGP material'
must_refuse 'secret.gpg'                        'PGP material'

# Case: an accidental commit does not respect the casing a rule assumes.
must_refuse 'HANDOFF.MD'                        'uppercase scratchpad'
must_refuse 'Handoff.md'                        'mixed-case scratchpad'
must_refuse '.ENV'                              'uppercase environment file'
must_refuse 'ISSUE-DRAFT.md'                    'uppercase issue draft'
must_refuse 'Docs/Issue_Draft.md'               'mixed-case issue draft'
must_refuse 'ID_RSA'                            'uppercase SSH key'

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
must_allow 'docs/CREDENTIALS-POLICY.md'         'documentation ABOUT credentials is not a credential'
must_allow 'scripts/credentials-helper.sh'      'a helper script is not a credential store'
must_allow 'docs/key-rotation.md'               'documentation about keys is not a key'
must_allow '.gitleaks.toml'                     'scanner config'
must_allow 'tests/fixtures/portfolio-bin/gh'    'test fixture binary stub'

echo
echo "== forbidden paths: --check agrees with --pattern =="
# A fixture that matches must actually make --check fail, so the two entry
# points cannot disagree. Use an untracked file: --check reads --others too.
#
# The probe name matches the rule, so LEAVING IT BEHIND would make every later
# `make check` fail with a forbidden-path error pointing at a test artifact.
# Register the cleanup in a trap BEFORE creating the file, so an interrupt or an
# unexpected error cannot leak it, and give it a unique destination so repeated
# runs cannot clobber one another.
probe="$ROOT/.forbidden-probe-issue-draft.md"
probe_dest=""
cleanup_probe() {
  [[ -e "$probe" ]] || return 0
  mkdir -p "$ROOT/.import"
  probe_dest="$(mktemp "$ROOT/.import/forbidden-probe-removed.XXXXXX")"
  mv -f "$probe" "$probe_dest"
}
trap cleanup_probe EXIT HUP INT TERM
printf 'probe\n' > "$probe"
set +e
"$ROOT/scripts/forbidden-paths.sh" --check >/dev/null 2>&1
rc=$?
set -e
cleanup_probe
if [[ -e "$probe" ]]; then
  bad "probe file survived cleanup at $probe (would break later make check runs)"
elif [[ "$rc" -ne 0 ]]; then
  ok "--check fails when a forbidden path is present"
else
  bad "--check passed with a forbidden path present (rule not wired to the gate)"
fi
trap - EXIT HUP INT TERM

echo
echo "== $pass passed, $fail failed =="
[[ "$fail" -eq 0 ]]
