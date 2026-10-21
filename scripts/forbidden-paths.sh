#!/usr/bin/env bash
# Single definition of path patterns this repository must never track.
#
# Both `make check` and tests/forbidden-paths-test.sh consume this, so the rule
# has ONE definition. An inline copy in the Makefile plus a second copy in a
# test would let the two drift, and the test would then assert the copy rather
# than the gate that actually runs.
#
# Usage:
#   scripts/forbidden-paths.sh --pattern     # print the ERE
#   scripts/forbidden-paths.sh --check       # exit 1 if any tracked/untracked
#                                            # path matches; print the matches
#
# WHAT BELONGS HERE: material that is unsafe or meaningless to publish —
# credentials and key material, rolling session scratchpads, unposted issue
# drafts, and tool caches.
#
# WHAT DOES NOT: maintainer run records, journals, orchestration state
# snapshots, and other operational notes about maintaining the agentic-coding
# repositories. Refusing those would refuse this repository's own purpose; it
# exists to hold maintainer workflow, which produces exactly such records.
# Genuinely sensitive content is excluded by the patterns below and by the
# separate secret-content scan, not by guessing from a filename.
set -euo pipefail

# Tool caches and external tool state, at any depth.
PATTERN='(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.nexus-agents)(/|$)'
# Session scratchpads, key material, and unposted issue drafts, at any depth.
PATTERN+='|(^|/)(HANDOFF(-ARCHIVE)?\.md|[^/]+\.(pem|key|crt|p12|pfx)|.*issue[-_]?draft.*)$'
# Environment files. Kept SEPARATE because `.env` needs a suffix wildcard that
# the group above anchors away: inside `(...)$`, the branch `\.env($|\.)` can
# only ever match exactly `.env`, so `.env.local` and `.env.production` were
# NOT refused (verified against the pre-existing inline rule). `.env.example`
# is deliberately exempt so a documented placeholder stays trackable.
# POSIX ERE has no negative lookahead, so express "any .env suffix except
# .example" as an explicit alternation over the first character.
PATTERN+='|(^|/)\.env($|\.([^e]|e($|[^x])|ex($|[^a])|exa($|[^m])|exam($|[^p])|examp($|[^l])|exampl($|[^e])|example.))'

case "${1:---check}" in
  --pattern) printf '%s\n' "$PATTERN" ;;
  --check)
    ROOT="$(cd "$(dirname "$0")/.." && pwd)"
    if git -C "$ROOT" ls-files --cached --others --exclude-standard | grep -E "$PATTERN"; then
      printf 'forbidden path(s) present (see scripts/forbidden-paths.sh)\n' >&2
      exit 1
    fi
    ;;
  *) printf 'usage: %s [--pattern|--check]\n' "$0" >&2; exit 2 ;;
esac
