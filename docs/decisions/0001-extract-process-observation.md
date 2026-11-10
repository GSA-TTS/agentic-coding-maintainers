---
title: "Extract process observation behind a behavior-preserving seam"
description: "Move the bounded ps-based process probe into a sibling module behind an unchanged core wrapper, and bind it into the execution-plan controller hash"
status: "proposed"
tier: 2
date: "2026-11-10"
decision_makers: ["Maintainers (review pending)"]
category: "Audit and Monitoring"
nist_controls: ["AU-3", "AU-12", "CM-3", "SI-4"]
impact_level: "moderate"
ato_relevance: "no"
risk_treatment: "n/a"
---

# Extract process observation behind a behavior-preserving seam

**Status: proposed, pending maintainer review.** AI-assisted draft (Claude Sonnet
5.5 in OpenCode) for issue
[#161](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/161), a
follow-up to merged proposal
[#138](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/138)
(`.scratch/portable-team-as-code/proposal.md`, which marks `process_identity` to
"decouple, retain as a runtime implementation"). Nothing here is accepted until a
human maintainer accepts it.

## Context and Problem Statement

`orchestrator-state.py` (the coordination core) both owns task state and shells
out to `ps -p <pid> -o lstart=` in `process_identity`. Claim, reconcile, guarded
cancellation and recovery, foreground delivery, and execution observation all
consume that one function. Proposal #138 expects other runtimes to need other
kinds of observation later, but those cannot be designed safely while the only
implementation is embedded in a 1,800-line state module. Can the process probe
move to its own module without changing what any caller observes?

## Decision Drivers

- Behavior preservation: identical signature, `alive`/`absent`/`unknown`
  results, three-second bound, and environment handling.
- Evidence integrity: execution evidence admitted under a controller hash must
  not silently lose coverage of code that used to be inside a hashed module.
- Fail closed: an unknown observation must stay unknown; nothing may become
  stronger evidence of liveness, absence, or termination than it is today.
- No privilege, status-taxonomy or new persisted-schema change. (The existing
  execution-plan `controller` mapping gains one key; see Compatibility.)
- Existing patching (`orchestrator-state.process_identity`) and importers of the
  core by path (consumer adapters, fixtures that copy the whole skill) keep working.
- Small, reviewable change; no speculative abstraction (YAGNI).

## Considered Options

1. **Leave `process_identity` in the core** — no risk, but keeps the future
   runtime-observation question entangled with lifecycle, reservation and
   recovery code.
2. **Extract to sibling `runtime-observation.py`; keep a compatibility wrapper in
   the core (chosen)** — move the function body verbatim; the core loads the
   sibling by path, as it already does for `reservation-history.py`, and its
   `process_identity` delegates.
3. **Introduce a generic observation interface or registry with a process
   adapter** — anticipates Paseo and other runtimes, but would invent contracts
   (status vocabulary, adapter selection, schema) with no second implementation
   to validate them.
4. **Re-point callers directly at the new module and drop the wrapper** — a wider
   diff and it would silently bypass monkeypatches and callers that use the core
   attribute (`worker_metadata`, `reconcile_one`, recovery, the foreground
   dispatcher, the execution observer, `scripts/assignment-dispatch.py`).

## Decision Outcome

Chosen option: **2**, because it creates the seam with the smallest diff while
satisfying every driver above.

- `bin/runtime-observation.py` holds `process_identity(pid, *, environment=None)`
  verbatim: one `ps` call, `timeout=3`, `OSError`/`SubprocessError` →
  `("unknown", None)`, return code 1 with stderr or any code other than 0/1 →
  `unknown`, otherwise non-empty stripped stdout → `("alive", text)` and empty →
  `("absent", None)`.
- `orchestrator-state.py` loads the sibling via `importlib.util` relative to its
  own file and keeps `process_identity` with the same signature, delegating to it.
  All in-core call sites still resolve the module attribute.
- `worker_metadata`, the claim/reconcile/recovery paths, assignment reservation
  and release, and the stop guards are untouched.
- `execution-plan.py` adds `runtime-observation.py` to `MODULES`. The probe used
  to be inside the hashed `orchestrator-state.py`; without this the extraction
  would silently remove it from the controller hash that execution evidence is
  judged against.
- `tests/runtime-observation-test.py` covers real-process positives and absence,
  the exact bounded invocation, the current result mapping (including malformed or
  multi-line output), timeout and launch errors, environment forwarding, wrapper
  compatibility, and copied-skill loading. `tests/execution-plan-test.py` shows
  that changing only the probe invalidates applicable execution evidence and
  that retained legacy plans are preserved but refused (see Compatibility).

**A process observation is not descendant termination proof.** `alive`, `absent`
and `unknown` describe one PID at one instant. They do not show that child
processes, containers, or a worker's session ended; existing stop and recovery
guards still require their own evidence. This ADR changes none of that.

### Compatibility with retained execution plans

This change is not free of persisted-state effects. The plan ledger's
`controller` mapping previously had seven keys and now has eight.

- A plan admitted by this version records all eight keys; its content-addressed
  plan ID covers them.
- A retained plan admitted earlier has seven keys. Its bytes and plan ID are not
  rewritten, and the validator still accepts exactly that seven-key shape (and
  exactly the eight-key shape) so the ledger stays readable. No other shape is
  accepted.
- A seven-key plan never bound `runtime-observation.py`, so it cannot equal the
  current controller manifest. Dispatch and assessment of such a plan refuse with
  UNVERIFIED, and no new plan is admitted for that generation ("already frozen").
  Recovering needs a new review generation and a fresh plan and executions.
  This is the same outcome as any other controller upgrade today.
- Previously settled execution observations under an older plan therefore stop
  earning current obligation credit. Historical bytes are still retained.
- Rolling this change back is also not a no-op once eight-key plans exist: an
  older validator rejects them. Retain the newer controller, or quarantine and
  re-plan, rather than editing retained plans.

### Positive Consequences

- The probe has a named home and its own focused tests.
- Future observation work can be reviewed against a small, stable module.
- No caller or operator procedure changes, and no wrapper or probe result changes.

### Negative Consequences

- The core now has an import-time dependency: an installed copy lacking
  `runtime-observation.py` fails with an ordinary import error (the module spec
  or file cannot be loaded), not a structured Unknown result, before any command
  runs. Consumers that copy the whole `bin/` directory or sync the skill are
  covered; hand-picked partial copies are not.
- Previously settled execution evidence under retained plans loses current
  credit (see Compatibility).
- One more file in the canonical hash manifest and sync set.
- The core keeps a one-line wrapper so existing callers and patches keep working;
  removing it is a separate decision.

### Compliance Consequences

- Supports audit and monitoring clarity (AU-3, AU-12, SI-4) and change control
  (CM-3) by isolating the evidence source; no new control is claimed as satisfied.
- No ATO boundary, data classification, credential, network, or privilege change.
- The new file is covered by `CANONICAL-SHA256SUMS`; `make check` verifies it.

## Future uses (not implemented, not approved by this ADR)

Proposal #138 anticipates that a CLI-backed or Paseo-backed worker would need
runtime observations other than a PID (for example agent, session or turn state;
a shared Paseo server PID cannot stand in for a conversation). The new module is
a place such work *could* be considered. Any such use needs its own issue,
contract, status vocabulary, evidence-limit statement, review and qualification.
This ADR adds no adapter, registry, schema, taxonomy, Paseo integration, or
autonomous lifecycle action.

## Known limitations preserved, not fixed

Reported for separate triage; the extraction deliberately does not change them:

- The start time is compared as opaque `ps` text (locale- and format-dependent;
  second resolution). Callers that pass no environment inherit the caller's.
- Return code 0 with non-empty stdout is `alive` regardless of its content or
  line count; the text is not parsed or validated.
- Return code 1 with empty stdout and empty stderr is reported as `absent`; the
  probe does not distinguish why `ps` found no row.
- `ps` is resolved through `PATH` of the supplied (or inherited) environment.

## Rollback

Revert the change set: restore the function body in `orchestrator-state.py`,
delete `runtime-observation.py` and its test, restore `MODULES`, and drop the
Makefile line and the hash/provenance entries. Before any eight-key execution
plan is retained this is clean. Afterwards, see Compatibility: do not edit
retained plans; keep the newer controller or quarantine and re-plan.

## Links

- Issue: [#161](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/161)
- Proposal: [#138](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/138)
- Operator guide: `.agents/skills/workspace-orchestrator/docs/OPERATOR-GUIDE.md`
  ("Status and recovery")
- Provenance: `.agents/skills/workspace-orchestrator/PROVENANCE.md`
- Controller hash: `.agents/skills/workspace-orchestrator/docs/EXECUTION-PLAN.md`
