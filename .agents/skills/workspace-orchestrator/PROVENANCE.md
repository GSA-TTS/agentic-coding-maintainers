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
