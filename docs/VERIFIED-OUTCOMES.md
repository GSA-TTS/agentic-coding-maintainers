# Verified outcomes — proposed evidence contract (decision pending)

**Status:** proposal for [maintainer issue #31](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/31), version `draft-1`. This document does not authorize crediting any completion. The existing cohort reader MUST continue to return `verified_completion_ids: []` until a maintainer accepts the applicable rules and a separately reviewed read-only attestor implements and tests them. The ledger `outcome` event is an operator claim, not an attestation.

## Decision to make

For each case type, decide which **owning-repository evidence at a fixed evaluation time** establishes delivery. Evidence must identify the intake case, exact repository object, timestamp and head SHA where applicable. Record provenance and a private, sanitized evidence reference; never copy a PR body, vulnerability detail, token or employee identity into a cohort report. Capture what was observed at that time; a later query may reveal a revert, dismissed review, or moved head and must not silently rewrite the old observation.

| Case type | Proposed positive outcome evidence | Keep UNVERIFIED when |
|---|---|---|
| Implementation | Linked, merged PR; exact reviewed head; successful *applicable required* checks for that head; valid independent current-head approval if required by the repo; permitted merge method; actual merge commit. | Open/draft PR, only a handoff or commit, checks absent/skipped/action-required, failed or not bound to head, dismissed/stale approval, unresolved blocker, missing merge commit, bypassed required independent review. |
| Routine dependency update | Implementation evidence **plus** exact manifest/lockfile versions and source, vulnerability scan and license disposition where applicable. Dependency updates remain eligible intake work. | Lockfile mismatch, floating update against pin policy, scan unavailable, installer hook unexamined, or license decision absent. |
| Documentation | Published or merged revision identified by SHA and repository event; content/rendered-link checks where applicable; current-head independent review if required. | Draft-only doc, issue closure alone, missing publication record, applicable checks unavailable or skipped. |
| PR review | Submitted review at the exact head examined, independently attributable to the reviewer, with a recorded advisory/formal disposition and follow-up handoff if findings remain. A review outcome does **not** imply the PR was merged. | Draft/unposted findings, review of an earlier head, missing reviewer or submitted timestamp, or unresolved required finding disposition. |
| Security assessment | Fixed-head assessment and coverage record; private disposition of applicable findings, including safe handling for embargoed vulnerabilities; independently attributable sign-off where required and repository evidence of authorized remediation or completed advisory. | “No findings” without measured coverage, unposted exploitable finding presented as public evidence, unresolved blocker, stale head, or unavailable validation. |

This is a **proposal**, including the dependency and security rows. The maintainer must decide whether each applicable validation is a completion requirement, whether a published advisory without remediation counts, and how to classify findings awaiting a third-party response. `not_applicable` must be justified per check; it is not a synonym for passing.

## Common constraints proposed for all types

1. **Cohort denominator is frozen at first intake.** Keep open, blocked, cancelled and abandoned eligible cases visible alongside verified outcomes. Eligibility changes are separate append-only corrections; do not backdate the original cohort.
2. **No evidence, no credit.** Required checks, reviewer independence, object identity and final repository action must be measured independently of the ledger entry. Missing, malformed, unreachable or contradictory evidence is `UNVERIFIED`, never measured zero, pass, or automatic exclusion.
3. **Head binding is explicit.** An approval or check on SHA A does not certify SHA B. A merge of B after review of A requires a fresh applicability assessment of intervening changes. Do not guess from green historical checks.
4. **Governance is part of the result.** Record a merge performed with unmet required checks or independent review as `merged-with-bypass`, not a verified policy-compliant completion. This preserves actual delivery evidence without manufacturing review evidence. GitHub self-approval cannot satisfy independent review.
5. **Outcomes can be superseded.** A revert or reopened finding is a new event. Keep the original outcome and its evidence, and show supersession at later `as_of` snapshots. The first 30 days following an outcome remain `follow_up_pending`; do not treat them as zero escapes.
6. **No composite productivity score.** Report per-type numerator and eligible denominator case labels, unfinished cases and evidence coverage; compare comparable cohorts. Do not optimize raw merge count, PR count, model tokens or worker utilization.

## Counterexample fixtures a future attestor MUST reject or classify

| Fixture | Expected classification, never a verified success |
|---|---|
| SHA A has approval and passing checks; SHA B is merged | `UNVERIFIED_STALE_HEAD` until B has applicable review/check evidence |
| A required check is absent, SKIPPED, action_required, or timed out | `UNVERIFIED_CHECK_COVERAGE` (state and source retained) |
| Administrator merged with unmet required independent review | `MERGED_WITH_BYPASS`, not policy-compliant verified completion |
| Author approval is the sole recorded approval | `UNVERIFIED_INDEPENDENT_REVIEW` |
| Ruleset absent: GitHub says mergeable, no checks or review recorded | `UNVERIFIED_POLICY_EVIDENCE`; mergeability is not proof of validation |
| Review dismissed after head changed | `UNVERIFIED_STALE_REVIEW` |
| Issue closed without category-specific publication/merge/review event | `UNVERIFIED_OUTCOME` |
| Qualifying merge reverted two weeks later | Preserve first event; report `REVERTED` at later snapshot, not a durable success |
| Merge three days ago without post-merge problems reported | `follow_up_pending`, not zero confirmed escapes |
| Unposted security finding awaiting response | Keep private, `UNVERIFIED_DISPOSITION`; do not leak details into public PR or cohort artifact |

## Review gates before implementation

- Approve or amend the per-type decision table above. In particular: which review requests end at a **submitted review**, which at **finding resolution**; whether a security assessment can complete while remediation is pending; which validations are truly applicable to docs/dependencies.
- Identify the authoritative repository event and timestamp for each type, and decide what constitutes independent reviewer identity under the organization’s rules. Do not infer it from a ledger string.
- Define the permitted evidence retention and private storage location, follow-up maturity window, and how changes in branch protection are evaluated **as of** the relevant event.
- Only then build a separate, read-only current-head GitHub attestor. It must have bounded pagination, explicit errors/coverage, synthetic positive and negative fixtures above, and no remote-write path. Compare the attestor’s output with source objects before adding any verified completion count to the existing reflection CLI.

**Until those gates are met:** issue #31 stays open; `verified_completion_ids` remains empty; a green CI badge or a manually entered `outcome` is not a completion verdict.
