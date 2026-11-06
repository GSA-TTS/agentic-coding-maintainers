# Actionable review output

## Two audiences, unchanged safety contract

The **internal handoff to the orchestrator** remains complete: exact reviewed
head and comparison base, acceptance criteria and obligation coverage, findings,
evidence and validation references, all UNVERIFIED coverage and limitations,
finding dispositions, status, and next action. Preserve any required structured
report fields and runtime bindings. A concise human-facing review does not
replace that handoff, waive acceptance gates, or turn missing evidence into a
clean result. Internal passing checks and resolved findings remain evidence even
when omitted from the outward review.

The **final human-facing review** contains actionable, unresolved findings in
severity order: Blocker, Should-fix, then Nit. Each finding gives a verified
`file:line` (or short range), the trigger, impact, and a concise concrete fix.
Include only evidence and uncertainty that change the finding's credibility,
scope, severity, or required action. Do not invent a line number when source
mapping is unavailable: name the known path or symbol, state that the line is
unavailable, and identify the missing source needed to verify it. Distinguish
base-side deleted lines from head-side lines; never map guest paths by guesswork.

Omit passing-check inventories, resolved-finding recaps, review-process narration,
assignments, merge administration, and generic reassurance from outward reviews.
Retain brief required AI attribution and exact-head binding. With verified
coverage and no actionable findings, say so once; add a scope caveat only if it
materially limits that conclusion. With missing required coverage, say
**UNVERIFIED**, identify the missing evidence and next verification step, and
never label the review clean or imply approval. Known actionable findings may
still be reported alongside that limitation. If the head itself is unverified,
label the supplied SHA as claimed, not reviewed.

## Synthetic examples

These fictional paths, lines, and SHAs illustrate presentation only. They are
not repository findings, executed reviews, or acceptance evidence. The static
fixture checks example structure, not whether an LLM follows these rules.

### One defect with material uncertainty

```text
Should-fix — src/cache.py:42 — When a cache entry expires during lookup, the
missing-value branch returns HTTP 500 instead of fetching the origin, dropping
otherwise valid requests. Fetch on a cache miss before decoding the value.
The branch is visible in the inspected source; runtime impact is UNVERIFIED
because no expiry-path transcript was supplied. Verify with an expiry fixture.

AI-assisted review of head 1111111111111111111111111111111111111111.
```

### No actionable findings

```text
No actionable findings.

AI-assisted review of head 2222222222222222222222222222222222222222.
```

Only when material, add a caveat such as “Scope: CLI parsing only; the unchanged
server is outside this review.” If the server was required coverage but not
reviewed, use UNVERIFIED instead of this no-findings example.

### Required coverage unavailable

```text
UNVERIFIED — The supplied diff omits src/auth.py, which is required to assess
the changed authorization path. Supply that source at the bound head for review;
authorization coverage cannot be concluded from this diff.

AI-assisted partial review of head 3333333333333333333333333333333333333333.
```

## Installation and verification

Keep the three reviewer/coordinator profiles compact and self-contained: their
bodies must carry the two-audience distinction, actionable-output rules, and
fail-closed handling even when this document is not read at runtime. Link this
packaged document for examples, not as a substitute for those instructions.
Install canonical profiles as byte-identical `.opencode/agents/` copies with
this skill's documentation. Quit and restart OpenCode after installation or
profile changes; running sessions retain their loaded instructions.

This is output guidance only. Permissions, fixed-head review requirements,
independence, sandbox requirements, and publication authority are unchanged.
Static fixtures can verify packaging, links, profile parity, and synthetic
example invariants; they cannot establish model compliance or review quality.
