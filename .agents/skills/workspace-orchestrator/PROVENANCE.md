# Provenance

This skill was copied with the source author's authorization from the
`review_things` repository on 2026-10-16.

- Source base commit: `c9248ac748ee3835df5b837ae8009fce4c3a389b`
- Source author: William Zujkowski
- Source state: orchestration files were uncommitted at import; the commit above
  is the recorded base revision and `SOURCE-SHA256SUMS` binds every imported file
- Original capability: host-local multi-agent task ownership, bounded worker
  admission, foreground GitHub monitoring, OpenCode role profiles, recovery,
  and independent review gates
- Destination adaptations: self-contained dispatcher; explicit consumer
  workspace root; generic validated repository/project monitor config; GSA
  Project 120 as an example only; reusable OpenCode v1 profile pack; canonical
  maintainer-repository ownership after import

The source author and accountable contributor explicitly authorized this copied
material and the listed destination adaptations for release under this
repository's CC0-1.0 dedication. This statement does not change the license of
other content in the source repository.

## Canonical adaptation: cooperative lifecycle binding pilot

### Assignment-first adapter candidate

Issue #117 candidate based on canonical revision
`7c6f71c7956e9b064180999c7b5bd29fa799d4b2`: narrowly qualified schema-3
`assignment_dispatch` reservation, lifecycle/release/recovery guards and journal
v6 typed requests, attempts, evidence and settlements. The permanent anchor is
written first; intermediate failure remains fenced. Existing immutable intent
rows retain exact v2 original-task equality, with a separate prospective reserved
task bound to interactive approval. All journal readers preserve v6 and reserve
assignment identifiers against observation and acknowledgment identifiers.

The consumer runner and fixtures are `scripts/assignment-dispatch.py`,
`scripts/publish-github-assignment.py`, `scripts/github-assignment-transport.py`,
`tests/assignment-dispatch-test.py`, `tests/publish-github-assignment-test.py`, and
the cooperative lifecycle fixture. Runtime validation belongs in the primary's
independently isolated guest. UNKNOWN arbitration remains unsupported without
qualified containment/termination evidence; no PID/boot-ID declaration releases
it. This candidate does not activate automatic claims or comment publication.
Original import history and `SOURCE-SHA256SUMS` remain preserved.

On 2026-11-09 the operator explicitly selected assignment-only delivery with
permanently fenced UNKNOWN, deferring abandonment release while issue #117 stays
open. Hardening reuses the core raw-byte whole-checkout verifier through a
credential-free, no-fsmonitor/hooks/filters/lazy-fetch Git probe. The runner's
process identity probe also receives a minimal environment. A rolled-back typed
insertion rehearsal precedes the marker, checking actual namespace/capacity/page
allocation before repeating the same checks in the real reservation transaction.

Fixed-head review rework from `15c12b27369040bf56ffe86be8eda2994723b364`
requires complete HTTP framing before JSON acceptance (including strict chunk
termination), and allows stopped-worker settlement only from already retained,
validated closed-producer evidence with known completion. Original task/lease
bindings remain exact; missing or UNKNOWN evidence stays fenced. Fixtures use
real HTTPResponse parsing over bounded synthetic socket streams and real reaped
workers for terminal acknowledgment and confirmed GET-only recovery.

Diagnostic hardening based on canonical revision
`b6345eec1b4abfe55051ad6013d68db487701a45` adds typed evidence document v2
within journal v6: at most two allowlisted stage/reason/status diagnostics,
preserving the primary POST failure before any correlation failure. The typed
reader accepts immutable document v1 unchanged; monitor validation delegates to
that reader, and dispatch/recovery continue hashing the exact retained document.
Known capacity/identifier preflight refusals receive fixed codes. The publisher
flushes final JSON explicitly and reports output failure without changing durable
state. Consumer fixtures exercise the actual CLI/output boundary and legacy v6
evidence. RFC 9110 sections 10.2.2 and 15.3.2 justify inert Location metadata only
on the expected POST 201; redirects remain refused. This compatibility defect is
a pilot-cause hypothesis, not a demonstrated explanation of the historical
UNKNOWN or missing stdout. No historical attempt is rewritten or replayed.

Bounded issue #116 pilot based on canonical maintainer revision `00091f99`
(approved 2026-11-05): opt-in schema-3 cooperative task/worker session and retained
generation, explicit lock-held lifecycle comparisons, complete capacity metadata
checks, and fail-closed reconciliation. Schema 2 remains default; schema-1
migration and the imported source history above are preserved. Public core
readers/writers reject bound tasks unless explicitly opted in by the core CLI.
This is declared local correlation, not native authentication. The standalone
monitor now refuses schema 3 before poll configuration/state effects, and execution
observation refuses before definition/runtime work and runtime-config creation.
Full bound domain dispatch remains pending. Interrupted-bound-intent recovery is
limited to the explicit adaptation below.
The canonical
repository adds `tests/cooperative-session-binding-test.py` and registers it in
`Makefile`; copied-skill consumers must separately carry/run that fixture when
validating this pilot. `CANONICAL-SHA256SUMS` binds the adapted skill assets.

Independent-review correction: validate the complete prospective bound record
and exact legacy scope metadata under lock before opt-in reserves capacity or
persists a claim. Schema 3 allows only base task fields, cooperative binding,
and the core legacy-finding disposition ledger; unsupported retained domain or
unknown extensions are refused on opt-in and subsequent reads without coercion.

## Explicit interrupted-bound-task recovery adaptation

Issue #116 bounded recovery slice based on canonical revision
`aeaa68ce36ab515d76640205326be0e4df8142ad`: explicit single-task
`reconcile --recover` with operator declaration and current revision/generation,
exact retained scope and full bidirectional capacity ownership preflight, verified
absent worker, and existing execution/repair guards. A private bounded
pending/settled task receipt precedes capacity cleanup and binds original intent,
worker/lease snapshots, rationale and revision for guarded retry. Settlement is
only `Blocked`, preserving generation and already-recorded rework count. Automatic
reconciliation, native authentication, and domain activation are unchanged.
Missing scope, empty remnants and pre-intent lane acquisition remain unsupported.
The canonical cooperative fixture adds actual interrupted-transition boundaries
through fixture-local interception and real claimed/reaped children. Runtime
validation must occur in an independently justified isolated environment; static
inspection alone does not establish passing runtime coverage. Original source
revision and `SOURCE-SHA256SUMS` are preserved.

Independent candidate-2 P2 corrections: bind actual original capacity-presence
observations into the receipt and enforce slot-first/lane-second cleanup on
original full release and pending retry. Preserve the original Reviewing
lane-only exception only when the receipt observed that lane already absent;
refuse reappearing capacity and impossible observation combinations. Document
that pending and settled receipts require the receipt-aware core: the previous
schema-3 validator at the base above rejects the extension. An offline pinned
source excerpt checks this extension rejection without claiming a complete
previous-core reader or requiring Git history inside archive validation guests.

## Actionable review output adaptation

Issue 111 adaptation on canonical base `f21052d`: adds packaged human-facing
review guidance and synthetic example/wiring assertions while preserving the
complete internal fixed-head, evidence, acceptance, and UNVERIFIED handoff
contract. Output guidance grants no new permissions or publication authority.
The original import revision and `SOURCE-SHA256SUMS` remain unchanged. This base
identifies the starting revision, not a new canonical revision for these edits;
`CANONICAL-SHA256SUMS` must be regenerated for the completed skill assets.

## Durable historical claim observation receipts

Canonical base `70496835`: explicit consumer GET collector adds immutable bounded
historical receipts in the existing shared SQLite store. Only receipt recording
migrates schema 3 to 4, transactionally retaining intents and binding acknowledgments.
Packaged validation checks the exact version/table pair, reference, canonical
receipt digest, intent request digest/store incarnation, bounded complete observer
summary, UTC finish timestamp and known identifier separation. Existing intent
and monitor APIs preserve 4; candidate binding's original orphan-ack guard extends
from 2/3 to 2/3/4. No remote success, task authority or second outbox is added.
The consumer fixture is `tests/record-claim-observation-test.py`; it reuses actual
task/intent CLI and REST fixture helpers and is registered in `Makefile`.
Runtime validation is assigned to the primary's independent isolated guest;
static edits are not passing execution evidence. Imported source history and
`SOURCE-SHA256SUMS` remain preserved.

Receipt review corrections: reserve observation IDs symmetrically before future
intent insertion and before candidate-binding task authority writes, with a repeat
guard inside acknowledgment transactions. Historical validation includes both
acknowledgment incarnation and operation identifiers, and conflict summaries must
contain at least one recognized claim. Actual schema-4 observer fixtures reset
the fake GET call log between collections and assert unchanged private storage.
Collision fixtures exercise actual candidate binding refusal before task mutation,
noncolliding binding/ack append and retained-history validation.

## Bounded local public-claim intent persistence

Canonical base `cb5323f6219f2c7787b487b4895b175b2f75479c`: shared monitor
SQLite schema 3 adds bounded immutable `claim_intents` and always retains
`binding_acks`. Only the explicit local intent API migrates existing versions;
observation opens accept 3 without upgrading, and existing acknowledgment writes
preserve 3. Candidate binding's missing-authoritative-task-receipt guard applies
to both acknowledgment-bearing versions 2 and 3 before any task authority write.
The consumer fixture exercises actual binding retries against restored task bytes
around migration by a different actual issue-backed task, plus transaction-context
commit failure and rollback of migration/intent without an acknowledgment.
Packaged validation checks every intent's canonical request, exact
public wire body/digest, private task/session/worker fences and store incarnation.
Observation replay and intent APIs remain separate. Database identity checks
surround open/validation; the consumer completes commit/replay fsync barriers.
No task authority, remote effects, readiness, terminal replay or second outbox is
introduced. Older schema guards reject 3; archive complete stores for rollback.

The canonical consumer adds `scripts/journal-claim-intent.py` and
`tests/journal-claim-intent-test.py`, composing the existing preparation and core
coordinator lock. The packaged wire validator is intentionally independent of
consumer scripts; the fixture compares it with the consumer's actual codec.
Consumers must carry/run that fixture separately in an independently justified
isolated environment. Original import history and `SOURCE-SHA256SUMS` remain
unchanged. `CANONICAL-SHA256SUMS` binds the adapted sources and provenance;
static inspection alone is not passing runtime validation.

## Identity-bound local claim intent adaptation

Issue #117 based on canonical revision
`3eb8fb1af5c201739f443f561b2be0f611f5f221`: explicit consumer binder records
fresh private identity observations and unauthenticated exact-text declarations
as request v2. Only explicit v2 insertion advances the shared SQLite header to
version 5, with the existing v4 tables/columns. Packaged strict validation accepts
unchanged v1 rows and v2 only in v5; old readers reject the new version boundary.
Migration and insertion are one transaction. Existing monitor, v1 intent,
receipt and acknowledgment writes preserve v5; candidate binding retains its
pre-authority missing-task-receipt guard and observation-ID reservations.
The consumer's actual GET transport is identity-gated against persisted numeric
and node IDs before comment traversal. Receipt schema remains v1 and binds the
complete request digest plus conditional immutable target IDs. No row becomes
publishable or confers authentication, issuance, publisher or mutation authority.
The consumer adds `tests/journal-approved-claim-test.py`, registered in `Makefile`,
using existing actual core/intent/receipt/REST/binding fixtures. Execution is
reserved for an independently justified isolated guest; static inspection is
not passing runtime evidence. Original source history and `SOURCE-SHA256SUMS`
remain unchanged; `CANONICAL-SHA256SUMS` binds the adapted skill assets.
