# Collected review acceptance trial — 2026-10-29

AI-assisted continuation of #63 after PR77 merged at
`23cf6c5f6de847d33e3e63ef3fc9c3f89c163383`.

## Implemented behavior

The `review-accept` controller derives report identity from the retained
admission and parses only the collected final response's coverage, findings,
dispositions and limitations. Report, protocol receipt and collection link are
written atomically. Collected provenance is retained in reports and operation
receipts so deleting a link/table does not silently downgrade evidence to legacy
manual claims. Assessment and correction CLI paths validate retained artifacts.
The public manual-accept boundary rejects supplied collection provenance and
checks existing collected evidence before mutations/retries.

The runner's optional `--obligation` arguments request only the exact structured
schema accepted by this controller. Nonconforming output remains retained but
cannot become an accepted claim. Review-only access and no readiness credit
remain unchanged.

## Real qualified observation

The operator authorized one two-guest MSB pilot using the previous pinned Node
image, OpenCode 2.0.32 and MSB 0.7.11. The controller-test guest had no network;
the reviewer guest had only DNS/USAi HTTPS, the explicitly authorized managed
network rebind setting, source read-only, no controller state or GitHub credential.
Both used restricted security, UID 1000 and bounded resources.

An actual packet and assignment preceded the runtime invocation. The runner
requested five explicit baseline obligations and returned a conforming response.
Observed results:

```text
COLLECTION_ADMITTED: task revision 3
session: ses_structured_acceptance_20261029
REVIEW_OBSERVED
OBSERVATION_COLLECTED: task revision 4
input tokens: 4599
output tokens: 324
CLAIM_ACCEPTED: task revision 5
replay: identical, no mutation
assessment: UNVERIFIED
missing_obligations: [test-adequacy]
unresolved_findings: []
candidate_ready: false
execution_credit: false
delivery_credit: false
```

The reviewer did not receive test files and correctly reported test adequacy
unverified. The controller preserved that gap; successful claim ingestion was
not mistaken for completed review coverage. This was an isolated controller
test harness using the actual modules, not production scheduler admission or a
complete unattended acq workflow. The final manual-boundary hardening happened
after this pilot and was validated with regression tests.

## Verification and reviews

Docker network-off acceptance tests covered clean claims, defect-to-owner
correction, strict-parser refusal, stale/cancelled attempts, exact retry,
artifact loss, link/table deletion, manual provenance refusal and the public
CLI's atomic write/replay. The acceptance suite runs 21 cases, of which 12 are
inherited collection regressions, not 21 wholly new tests. The separate legacy
evidence suite passed all 18 tests.

The full Docker `make check` passed before the provenance repair; its initial
run exposed a checksum-manifest ordering error, subsequently corrected. Generic
OpenCode compatibility probes explicitly skipped and are not counted as live
qualification. Ruff/Pyright/Bandit passed before the final manual-boundary repair;
Ruff/Pyright and targeted tests passed after it.

Independent static review at `4720012ace2d807603fd0c0eb568288e34750b20` found
deletable link provenance and conflicting strict prompt fields. Both were
repaired and re-reviewed at `c51e68743311f6b11845e1c73b74fa8f6089d578`.
That review found the public manual-accept provenance path, now rejected with
CLI regressions. All findings remain documented rather than erased.

## Remaining scope

This accepts **claims**, not authenticated execution. No test execution receipts,
trusted launch attestation, automatic owner patch transport, GitHub effects,
service monitoring, approval/merge authority or polyrepo delivery is activated.
Structured findings can reach the existing bounded correction projection, but
the original owner must still claim rework under coordinator control.
