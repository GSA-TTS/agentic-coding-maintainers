# Assignment-bound collection trial — 2026-10-29

AI-assisted continuation of #63 after PR76 merged at
`b4d3e8ad48f3a7fe9b328ad617f60af79b1cd47e`.

## Implemented

Controller admission binds an existing native-session assignment, current task
revision/generation, source packet, selected source bytes, runtime binary,
profile, model and agent. Collection recomputes observations from bounded
artifacts, publishes content-addressed evidence before atomic task references,
and retains replay-safe operation receipts. Cross-protocol revision collisions,
late assignments, stale attempts and substituted profiles are refused.

The runner accepts a preassigned session ID and hashes the supplied installed
configuration before/after execution. Guest read paths are normalized lexically
so macOS controller aliases cannot change Linux guest evidence.

## Actual two-guest pilot

One network-off MSB controller-test guest created the packet and admission before
dispatch. A separate MSB reviewer guest had source read-only, no controller
state, no GitHub credential, and only gateway DNS plus USAi HTTPS access.
The managed-network rebind setting was explicitly authorized. Both used the
same pinned Node Linux ARM64 image, restricted security, UID 1000, 2 CPUs and
2 GiB RAM. Runtime was OpenCode 2.0.32 and MSB 0.7.11.

```text
COLLECTION_ADMITTED, resulting_revision: 3
session: ses_maintainer_collection_20261029
REVIEW_OBSERVED
OBSERVATION_COLLECTED, resulting_revision: 4
source_reads: /candidate/.agents/skills/workspace-orchestrator/bin/review-collect.py
tokens: input 7904, output 947
replay: identical result, no mutation
substitution: REFUSED
candidate_ready: false
execution_credit: false
delivery_credit: false
```

The pilot used an isolated controller test harness around the actual modules,
not production scheduler admission. The public CLI's authoritative persistence
and replay are covered separately by isolated fixture tests. This is not an
installed acq service, unattended repair, authenticated execution receipt, or
GitHub delivery proof.

## Review findings and dispositions

Independent fixed-revision review at `30de96b3a1560728e375f25be1b212e346fd7064`
found a cross-protocol chronology gap and controller-dependent guest pathname
resolution. Both were repaired with regressions. The actual model review found
interrupted artifact publication could block retries: publication now writes
and fsyncs a temporary file, then atomically links without overwriting the final
address. A reported ancestor-path race remains the explicitly documented
same-user/check-then-use limitation; it is not represented as an OS isolation
guarantee.

Independent re-review at `0296dd1db6605f3b9bce0c520c29959d5e806dfe` confirmed
the earlier repairs and found missing parent-directory fsync for first store
creation. The final fix syncs the parent on creation and retry before committing
references. Failure injection proves task state remains unchanged if it fails.

## Verification and limits

Full isolated Docker `make check` passed with 11 collection tests, 10 runner,
18 evidence, 10 packet, and all existing suites. After the parent-directory
durability fix, the targeted collection suite passed 12 tests. Static Ruff and
Pyright passed; Bandit passed before that five-line durability correction.
Generic OpenCode runtime probes in the repository suite explicitly SKIP; the
separate real pilot above provides only its stated coverage.

Matching artifacts remain internally consistent **worker-supplied observations**.
Collector output explicitly reports authenticity UNVERIFIED and grants no
readiness/execution/delivery credit. A trusted controller launch/transport,
meaningful execution receipts, automatic owner transport, durable monitoring,
bounded GitHub effects and polyrepo delivery remain subsequent work. No policy,
App, ruleset, service supervisor or merge authority was activated here.
