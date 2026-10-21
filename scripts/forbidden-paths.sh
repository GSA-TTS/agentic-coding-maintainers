#!/usr/bin/env bash
# Single definition of path patterns this repository must never track.
#
# Both `make check` and tests/forbidden-paths-test.sh consume this, so the rule
# has ONE definition. An inline copy in the Makefile plus a second copy in a
# test would let the two drift, and the test would then assert the copy rather
# than the gate that actually runs.
#
# Usage:
#   scripts/forbidden-paths.sh --pattern     # print the ERE (case-insensitive)
#   scripts/forbidden-paths.sh --check       # exit 1 if any tracked/untracked
#                                            # path matches; print the matches
#
# Matching is CASE-INSENSITIVE (`grep -Ei`). `HANDOFF.MD`, `Handoff.md`,
# `.ENV` and `ISSUE-DRAFT.md` were all accepted before that was added, and an
# accidental commit does not respect the casing a rule happens to assume. Any
# consumer of --pattern MUST therefore also use -i.
#
# WHAT BELONGS HERE: material that is unsafe or meaningless to publish —
# credentials and key material, rolling session scratchpads, unposted issue
# drafts, and tool caches.
#
# WHAT DOES NOT: maintainer run records, journals, orchestration state
# snapshots, and other operational notes about maintaining the agentic-coding
# repositories. Refusing those would refuse this repository's own purpose; it
# exists to hold maintainer workflow, which produces exactly such records.
#
# SCOPE LIMIT, stated so it is not mistaken for more than it is: this is a
# FILENAME rule. It cannot see content. Genuine protection against committed
# secrets comes from the pinned Gitleaks scan in CI (`gitleaks dir .`), and the
# narrower token grep in `make check` misses several common formats — measured:
# it catches `BEGIN ... PRIVATE KEY` but NOT `aws_secret_access_key=...` or a
# `xoxb-` Slack token, both of which Gitleaks does catch. Nothing here or in
# either scan detects prose-shaped sensitive material such as host inventories
# or embargoed findings; that remains a human review judgment.
set -euo pipefail

# Tool caches and external tool state, at any depth.
PATTERN='(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.nexus-agents)(/|$)'
# Session scratchpads and unposted issue drafts, at any depth.
PATTERN+='|(^|/)(HANDOFF(-ARCHIVE)?\.md|.*issue[-_]?draft.*)$'
# Key material and credential stores. Extension list, at any depth. `id_rsa`
# and `id_ed25519` are named explicitly because SSH private keys carry NO
# extension, which made them the most likely accidental key commit of all.
PATTERN+='|(^|/)([^/]+\.(pem|key|crt|cer|der|p8|p12|pfx|jks|keystore|ovpn|kubeconfig|asc|gpg|ppk)'
PATTERN+='|id_rsa|id_dsa|id_ecdsa|id_ed25519|\.netrc|\.npmrc|\.pypirc|\.htpasswd'
PATTERN+='|credentials|.*service[-_]?account.*\.json)$'
# Environment files. Kept SEPARATE because `.env` needs a suffix wildcard that
# the group above anchors away: inside `(...)$`, the branch `\.env($|\.)` can
# only ever match exactly `.env`, so `.env.local` and `.env.production` were
# NOT refused (verified against the pre-existing inline rule). `.env.example`
# is deliberately exempt so a documented placeholder stays trackable.
# POSIX ERE has no negative lookahead, so express "any .env suffix except
# .example" as an explicit alternation over the first differing character.
PATTERN+='|(^|/)\.env($|\.([^e]|e($|[^x])|ex($|[^a])|exa($|[^m])|exam($|[^p])|examp($|[^l])|exampl($|[^e])|example.))'

case "${1:---check}" in
  --pattern) printf '%s\n' "$PATTERN" ;;
  --check)
    ROOT="$(cd "$(dirname "$0")/.." && pwd)"
    # -i: see the case-insensitivity note above.
    if git -C "$ROOT" ls-files --cached --others --exclude-standard | grep -Ei "$PATTERN"; then
      printf 'forbidden path(s) present (see scripts/forbidden-paths.sh)\n' >&2
      exit 1
    fi
    ;;
  *) printf 'usage: %s [--pattern|--check]\n' "$0" >&2; exit 2 ;;
esac
