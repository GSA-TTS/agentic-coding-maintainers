# First-slice design and acceptance

Issue: GSA-TTS/agentic-coding-maintainers#112.

The canonical asset is an originally authored reusable skill. Its first slice
contains a read-only, standard-library validator and research/impact protocols.
It does not fetch sources, mutate rules, run daemons, certify legal currency,
or automate impact comparisons. Those capabilities require separately reviewed
input-binding implementations.

## Records

An authority bundle links claims to versioned source records. Sources retain
publisher, URI, locator, exact quote, artifact digest/version, retrieval time,
effective interval, review due date, status and supersession link. Claims retain
rule identity, authority kind, applicability, exceptions, status and source IDs.
Quotes and digests are assertions: this slice does not authenticate them.

## Validation

Reject unknown fields, duplicate JSON keys/IDs, dangling references,
supersession cycles, malformed dates/digests, future retrieval relative to an
explicit cutoff and claims marked verified without verified evidence. Bound
input size and refuse symlink inputs. Current metadata returns 0; stale or
unverified metadata returns 3; malformed input returns 4. None means legal truth.

## Impact protocol

Freeze rule/base/head bytes, engine, configuration, corpus manifest and expected
fixtures. Compare finding identity multisets and severities, not aggregate
counts. Review each added/removed/changed identity against its authority claim,
retain true-positive controls and include corrected-negative, historical,
statutory, quotation, identifier and context cases. Invalid/empty execution
cannot pass. The first slice documents this protocol rather than pretending a
comparison engine exists.

## Workflow and delivery

Primary-source research precedes naming changes. Review source scope and
effective dates, conflicting evidence and unresolved OMB text explicitly.
Event-triggered reviews and monthly foreground checkpoints identify stale
records; no continued monitoring is inferred from an old checkpoint.
Nexus query/discovery/expert analysis is optional supporting evidence, followed
by a bounded artifact-backed design vote and recorded finding dispositions.
No vote establishes law or substitutes for fixed-head QA/security.

Offline fixtures and repository checks are required. Independent fixed-head
reviews precede a PR. This maintainer repository retains its own human-review
merge requirements; the style-management-service solo exception does not apply.

## Iteration evidence

2026-11-05: Nexus registry query returned no matches; GitHub discovery returned
zero items; research expert execution timed out. Initial quick consensus had
three unverifiable abstentions and no quorum because no artifact was inlined.
Re-run with this artifact; missing access is degraded evidence, never approval.

## Revision after artifact-backed vote

The second panel approved proceeding 2–1, not code acceptance. The scope reviewer
requested a concrete consumer, contract and reuse audit. The intended consumer
is cloud-gov/style-management-service authority baseline issue 405 and pack
roadmap issue 390, maintained from this repository's canonical skill collection.
Existing `tools.validate_vale_rules` checks YAML/configuration identity and
`tools.project_metrics` counts tests/corpus; neither records authority quotes,
effective intervals or source supersession. Existing maintainer review packets
bind code-review evidence, not legal-source claims. They remain unchanged.

The frozen contract is `docs/CONTRACT.md`, with `examples/SYNTHETIC.json` and
47 subprocess fixtures in `tests/validate-test.py`. The Makefile test entry
invokes that suite. No JSON Schema dependency is added: standard-library
object-pairs parsing catches duplicate JSON keys before dictionary construction;
the small domain checks validate source references and supersession graphs.
Invalidity takes precedence over stale metadata. Unexpected internal crashes
remain nonzero tool failures, not ordinary 0/3/4 validation verdicts.

Review schedule is policy supplied in each record, not fetched from a clock.
Symlink components are inspected before a no-follow open; concurrent ancestor
replacement must be excluded by the execution environment. This is not a host
sandbox. Fixture evidence is structural only; real authority artifacts and
reviewer decisions must be bound in a later consumer application, not inferred
from an illustrative quote or hash.

## Final vote and v1 lifecycle revision

The final third vote returned no quorum. Retain that degraded outcome after the
second panel's 2–1 plan decision; it is not a replacement approval or code
acceptance. Neither outcome establishes authority truth or completes review gates.

The draft-review revision introduces integer schema version 1 and explicit
`active_claim_ids`. Validate every record structurally, but assess operational
currency only for selected claims and their sources; retain predecessor history.
Review timestamps/references are separate from retrieval, unknown effective
starts are nullable and selected-unverified, and reason objects identify distinct
lifecycle failures. The contract and expanded fixtures supersede the earlier
47-fixture contract description above; no new passing run is asserted here.
Impact evidence must bind authority-bundle bytes/digest, cutoff and document-period
decisions. Future schema changes require separate review; there is no migration,
automatic historical mode, or source authentication in this slice.

## Revised size bound

The operator explicitly revised the validator bound to **at most 400 lines**
for the cohesive version 1 implementation. The original 250-line estimate
preceded selected-view lifecycle validation and separate review metadata. Keep
the single stdlib file readable rather than compressing formatting or extracting
premature abstractions solely to meet that estimate. This revision does not add
runtime dependencies or relax input, scope, or validation gates. The PR must
disclose the revised bound and rationale accurately; the prior 250-line target
must not be represented as met. The operator reported 64 isolated tests passing
before the subsequent dictionary-iteration lint fix; that report is not a new
post-fix validation transcript.
