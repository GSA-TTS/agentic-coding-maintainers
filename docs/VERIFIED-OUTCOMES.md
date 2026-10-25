# Outcome evidence — delivery policy adopted, attestation pending

**Status:** operator decisions recorded 2026-10-25, version `decision-1`; attestation **not implemented**. The merged `draft-1` PR #42 called itself decision-pending despite issue #31 being closed; the operator has now explicitly decided the five policy points below. The existing cohort reader MUST still return `verified_completion_ids: []` until a separately reviewed read-only attestor implements and tests these decisions. The ledger `outcome` event remains an operator claim, not attestation.

## Operator decisions: two axes, not one pass/fail verdict

1. **Delivered** for implementation, routine dependency updates and documentation means an owning-repository **merge or publication event**. Capture its repository object, exact delivered revision and timestamp. Missing or unverifiable delivery evidence is `UNVERIFIED_DELIVERY`. A bypassed or failing merge can still be *delivered*, but it must not be presented as compliant.
2. **Review work delivered** at a submitted, attributable review of the head examined at submission time. A later push cannot erase that completed review work; it can make the review inapplicable to the *current PR head*. Finding resolution is a separate measure and follow-up obligation.
3. **Security-assessment work delivered** when an authorized assessment is delivered privately with a fixed-head coverage and finding-disposition record. Pending remediation is a **separate unresolved case**, not retroactive non-delivery of the assessment. Do not disclose exploitable findings to a public thread to prove delivery.
4. **Historical current-state proxy:** when contemporaneous policy/check/review evidence was not retained, a present-day GitHub query may be reported only as `HISTORICAL_PROXY`, with query time, source and unavailable at-merge evidence. It must **never** be renamed `historically compliant` or used as proof that required checks/review passed at merge time. A proxy must not silently upgrade `UNVERIFIED` compliance.
5. **Zero confirmed escapes after 30 days** requires evidenced coverage of the agreed follow-up sources for the full window. An elapsed window with missing source coverage is `UNVERIFIED_FOLLOW_UP`, not zero.

For every delivery outcome, report **separate fields**: `delivery_evidence` (observed/unverified), `policy_compliance` (observed/failed/unknown/historical_proxy), `finding_disposition` (resolved/pending/unknown), and `follow_up_coverage` (pending/covered/unverified). A single green badge or composite score must never combine them. The categories and precise source evidence remain to be implemented; these names state the reporting contract, not present CLI output.

## Adopted delivery criteria; evidence mapping still to specify

For each case type, decide which **owning-repository evidence at a fixed evaluation time** establishes delivery. Evidence must identify the intake case, exact repository object, timestamp and head SHA where applicable. Record provenance and a private, sanitized evidence reference; never copy a PR body, vulnerability detail, token or employee identity into a cohort report. Capture what was observed at that time; a later query may reveal a revert, dismissed review, or moved head and must not silently rewrite the old observation.

| Case type | Delivery evidence under decision-1 | Separate validation and compliance evidence |
|---|---|---|
| Implementation | Linked merge/publication object at an exact delivered revision and time. Open PR, draft, local commit or handoff alone is not delivery. | Applicability of checks, exact-head reviews, rulesets and merge method; missing/skipped/failing required checks or bypass are reported independently. |
| Routine dependency update | Same merge/publication evidence as implementation; updates stay eligible intake work. | Exact manifest/lockfile versions and source, vulnerability scan, installer hooks and license disposition where applicable. Absence is a validation gap, not proof of non-delivery. |
| Documentation | Published or merged revision identified by repository event, SHA and time. Draft-only document or issue closure is not delivery. | Rendering/link validation and independent review where required, independently reported rather than silently required for the delivered axis. |
| PR review | Submitted review record, reviewer attribution, timestamp and exact head examined **then**; no PR merge implied. | Finding resolution and whether that review still covers the current PR head are independent follow-up facts. |
| Security assessment | Authorized private delivery of a fixed-head assessment with measured coverage and private finding-disposition record. | Remediation and any required sign-off remain separate obligations/cases; unavailable coverage is a validation gap. |

The existing schema has no distinct `dependency` case type and its `outcome` requires a handoff-linked head and repository-event ID. A versioned category/outcome mapping for review, security and non-PR publication is therefore a prerequisite to implementation. `not_applicable` needs an explicit reason and is never a synonym for passing.

## Common constraints proposed for all types

1. **Cohort denominator is frozen at first intake.** Keep open, blocked, cancelled and abandoned eligible cases visible alongside verified outcomes. Eligibility changes are separate append-only corrections; do not backdate the original cohort.
2. **No delivery event, no delivery credit.** Repository merge/publication or submitted-review evidence must be measured independently of the ledger claim. Checks/review compliance are different axes: missing, malformed, unreachable or contradictory evidence remains `UNVERIFIED` on the relevant axis, not an automatic exclusion or invented pass.
3. **Head binding is explicit.** An approval or check on SHA A does not certify SHA B. A merge of B after review of A requires a fresh applicability assessment of intervening changes. Do not guess from green historical checks.
4. **Governance is part of the result.** A merge performed with unmet required checks or independent review is *delivered* when the merge event is verified, and separately recorded `merged-with-bypass`/noncompliant. It is not policy-compliant delivery. GitHub self-approval cannot satisfy independent review.
5. **Outcomes can be superseded.** A revert or reopened finding is a new event. Keep the original outcome and its evidence, and show supersession at later `as_of` snapshots. The first 30 days following an outcome remain `follow_up_pending`. After 30 days, zero escapes requires an evidenced follow-up source, observation interval and complete coverage for that interval; without those, report `UNVERIFIED_FOLLOW_UP`, not zero.
6. **No composite productivity score.** Report per-type numerator and eligible denominator case labels, unfinished cases and evidence coverage; compare comparable cohorts. Do not optimize raw merge count, PR count, model tokens or worker utilization.

## Counterexample fixtures a future attestor MUST reject or classify

| Fixture | Required classification; do not conflate delivery with compliance |
|---|---|
| SHA A has approval and passing checks; SHA B is merged | Delivered if B's merge event is verified; `UNVERIFIED_STALE_HEAD` for B's review/check compliance |
| A required check is absent, SKIPPED, action_required, or timed out | Delivery is determined by repository event; check coverage is `UNVERIFIED_CHECK_COVERAGE` unless a required check's failure is measured |
| A required check explicitly failed at the delivered head | Delivery still follows the repository event; **policy compliance FAILED**. A known red check is not missing evidence. |
| Administrator merged with unmet required independent review | Delivered if merge event is verified; `MERGED_WITH_BYPASS`, not compliant |
| Author approval is the sole recorded approval | `UNVERIFIED_INDEPENDENT_REVIEW` |
| Ruleset absent: GitHub says mergeable, no checks or review recorded | Delivery requires repository event. Policy compliance is `UNVERIFIED_POLICY_EVIDENCE` without applicable at-merge policy evidence; current settings are only `HISTORICAL_PROXY`. |
| Review dismissed after head changed | `UNVERIFIED_STALE_REVIEW` |
| Issue closed without category-specific publication/merge/review event | `UNVERIFIED_DELIVERY` |
| Qualifying merge reverted two weeks later | Preserve delivered event; report `REVERTED` at later snapshot, not a durable result |
| Merge three days ago without post-merge problems reported | `follow_up_pending`, not zero confirmed escapes |
| Follow-up window matured, but monitoring/issue/revert sources were unavailable | `UNVERIFIED_FOLLOW_UP`, not zero confirmed escapes |
| Old merge has a present-day green check and approval but no at-merge capture | `HISTORICAL_PROXY` for compliance, never historically compliant |
| Unposted security finding awaiting response | Keep private, `UNVERIFIED_DISPOSITION`; do not leak details into public PR or cohort artifact |

## Implementation gates still open

- Map the now-decided delivery criteria into a versioned event schema. Specify authoritative repository event and timestamp per category, and what identifies an authorized private security-assessment delivery. The current PR-shaped ledger cannot express them all.
- Define and capture policy/review/check applicability separately from delivery. Decide the retention window, private storage location, how to record independent reviewer identity under organization rules, and how changes in branch protection are evaluated **as of** the merge event.
- Define the permitted evidence retention and private storage location, follow-up maturity window, and how changes in branch protection are evaluated **as of** the relevant event.
- Establish **contemporaneous** capture and retention of policy/ruleset, review, checks and repository object state at outcome time. A later query to current GitHub settings cannot reconstruct what was required at an earlier merge. Older cases without that evidence remain UNVERIFIED; distinguish a current-state recheck from historical attestation.
- Map each accepted case type to versioned event/evidence fields before attesting it. The current ledger does not represent dependency as a separate type and models outcomes as handoff-linked PR-shaped heads. Do not force a review or security advisory into that shape just to produce a numerator.
- Only then build a separate, read-only GitHub attestor. It must have bounded pagination, explicit errors/coverage, synthetic positive and negative fixtures above, and no remote-write path. Compare the attestor’s output with source objects before adding any verified completion count to the existing reflection CLI.

**Until those implementation gates are met:** issue #31 may be closed for the operator policy decision, but `verified_completion_ids` remains empty; a green CI badge, current-state historical proxy, or manually entered `outcome` is not an attested delivery verdict.
