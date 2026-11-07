---
title: "Define what a binding migration preserves"
description: "Decide the portable export and authority-cutover scope."
status: draft
tier: 2
labels: ["wayfinder:grilling"]
---

# Define what a binding migration preserves

Type: grilling
Status: resolved
Assignee: primary AI Wayfinder with user
Blocked by: 03, 06
Parent: [Portable team-as-code: scale down, scale up](../map.md)

## Question

Should the local Markdown representation also be the interchange format, and
what data and guarantees must a migration preserve?

Build on [Agree on the portable team and binding contracts](03-team-and-binding-contract.md).
Decide stable identities, source provenance, dependencies, evidence/history,
provider-specific fields, and the treatment of active occupants and pending
effects. Define an explicit single-authority cutover and how to report loss or
unsupported fields. Do not assume native PR/MR objects or active processes can
move with task records.

Include [Define ongoing team memory and continuity](06-team-memory.md): preserve
knowledge scopes, provenance, corrections, supersession, and evidence links.
Distinguish portable authored knowledge from disposable retrieval indexes.

## Discussion

The user requested this next decision after accepting the memory contract.
### Confirmed by the user — migration Q1–Q3

- Use a versioned Markdown/Git interchange package for portable team/task state
  and authored knowledge. Preserve logical identities, custody, dependencies,
  decisions, evidence references, sources, corrections/supersession and known
  operation outcomes; map provider-native identifiers separately. Identify
  unresolved references and unsupported fields explicitly. Rebuild retrieval
  indexes rather than treating them as authoritative exports.
- First migration is a supervised, paused single-authority cutover: quiesce
  affected mutations, reconcile pending effects, capture a consistent source
  revision, validate an inactive destination, then explicitly activate it and
  retire the old write path. Unknown effect outcomes block dependent activation.
- Changing task storage and changing occupant runtime are independent. Runtime
  references may be preserved as provenance, but import does not resume agents,
  recreate timers, transfer credentials or grant execution permission. Retain or
  replace occupants only through an explicit runtime-binding step.

### Confirmed by the user — migration Q4–Q6

- The migration report distinguishes directly preserved content, explicitly mapped
  translations, historical-only evidence, and unsupported/missing content. Loss
  of required ownership, task, knowledge or recovery semantics blocks activation.
  Optional provider-specific details may remain in an attached archive with
  explicit acceptance. Native PRs, reviews and conversation histories are not
  silently represented as equivalent destination objects.
- Preserve pending reassessment purposes, not old timer ticks. After runtime
  rebinding, deliver them to current occupants using coalescing. Knowledge review
  records retain their original occupant generation and knowledge revision.
  A replacement inherits that evidence but performs its own orientation and
  consequential-claim verification.
- Retain a durable cutover record identifying the source revision, destination,
  migration ID and activation progress. Recovery inspects actual outcomes before
  continuing; a timeout is not evidence of success. Before activation, the source
  may be explicitly reopened only after verifying the destination stayed inactive.
  Once the destination has accepted writes, return requires another reconciled
  cutover. Uncertain authority pauses mutations until resolved.

## Answer

Resolved through the user's explicit acceptance of migration Q1–Q6. The
versioned Markdown/Git interchange preserves logical identity, task custody,
dependencies, authored knowledge, provenance and known operation outcomes, with
explicit mappings and preservation limits. The first migration is a paused,
supervised single-authority cutover with retained recovery evidence. Runtime
rebinding remains separate and never follows implicitly from import. Pending
reassessment purposes and revision/generation-bound review history retain their
meaning without replaying timer ticks or granting inherited approval.

Required semantic loss blocks activation; ambiguity blocks dependent actions.
This decision defines the contract, not a completed migration implementation or
live experiment. It unblocks
[Design the scale-down and scale-up demonstration](05-demonstration-design.md),
which decides how much migration the first demonstration must show.
