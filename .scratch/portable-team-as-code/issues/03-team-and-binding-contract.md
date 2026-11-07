---
title: "Agree on the portable team and binding contracts"
description: "Decide the ownership model and minimum binding guarantees with the user."
status: draft
tier: 2
labels: ["wayfinder:grilling"]
---

# Agree on the portable team and binding contracts

Type: grilling
Status: resolved
Assignee: primary AI Wayfinder with user
Blocked by: 01, 02
Parent: [Portable team-as-code: scale down, scale up](../map.md)

## Question

Which team concepts and operations should be portable, and what minimum
guarantees must each binding provide?

Use [Locate reusable coordination and missing binding interfaces](01-maintainers-binding-surfaces.md)
and [Compare minimal local operation with the Paseo experience](02-minimal-and-paseo-bindings.md).
Decide stable task/seat identity, occupant replacement, claim semantics,
caller identity assumptions, authority placement, effect delivery, and runtime
observation. Distinguish assignment custody from personal todos and scheduling
from agent judgment. Choose the reuse strategy for Maintainers.

Resolve through live discussion; do not treat a research recommendation as the
user's decision. Capture settled vocabulary in an effort-local glossary.

## Discussion

2026-11-06: Both research prerequisites resolved. Primary is opening the human
contract discussion. Existing direction (Markdown default authority, stable seats,
replaceable occupants, portable skills, first-class memory) stays settled.
Initial proposal: task custody belongs to a seat, execution permission to an
occupant generation; replacement fences old-generation team mutations. Runtime
stop evidence remains separate. Skills request semantic operations from bindings;
unsupported required guarantees are explicit rather than silently approximated.
At the opening of discussion these were proposals, not an Answer.

### Confirmed by the user, 2026-11-06

- Task custody belongs to the stable seat; permission to act belongs to the
  current occupant generation. Replacement preserves task custody and knowledge
  while rejecting stale-generation team mutations. Runtime termination remains
  separately observed; changing the mapping does not prove an old process stopped.
- Define the portable contract first, informed by Maintainers' coordination rules.
  Assess concrete extraction/adaptation after that; the minimal team need not
  install the full Maintainers orchestration suite. Paseo satisfies the same contract.
- Will confirmed GitHub issues are authoritative and local issue metadata is a
  performance cache. Will reports decoupling in flight. Track published changes
  through the [upstream binding watch](07-upstream-binding-watch.md), distinguishing
  issue truth, operational records, observed source and maintainer confirmation.
- Q3 accepted: a successor may orient, retrieve knowledge, inspect evidence and
  plan while the old occupant's execution is uncertain. Conflicting writes remain
  blocked until that execution is confirmed stopped or independently prevented
  from affecting the shared work. Generation checks on team operations do not
  themselves prevent an old process from writing files directly.
- Q4 accepted: every binding must satisfy a small mandatory core: stable
  identities, conditional state changes, stale-generation rejection, and explicit
  outcomes including unknown. Steering, durable notifications, scheduling and
  panels are declared optional capabilities. Skills may select supported behavior
  but must not silently weaken a required guarantee.
- Q5 accepted: mutations carry an operation ID, expected revision and occupant
  generation. An identical retry recovers its recorded result; reuse of the ID
  with changed contents is rejected. Uncertain external effects are inspected
  before retry; this is not a promise of exactly-once external execution.
- Q6 accepted: routine wakes address seats and retain one pending reassessment
  per purpose, combining duplicate ticks. When the current occupant is available,
  it reassesses current state once rather than replaying every missed tick.
  Delivery attempts and completed reassessments are counted separately. Explicit
  human interruption is a separate action. This requires behavior beyond a raw
  Paseo heartbeat, which refuses busy recipients.
- Q7 accepted: the minimal configuration assumes cooperating agents and users.
  Generation checks prevent accidental stale actions through team operations;
  they are not authentication against a same-account process that can read the
  same state or credentials. Stronger isolation is a declared runtime capability.

Settled terms are recorded in the [effort glossary](../GLOSSARY.md).

## Answer

2026-11-06: resolved through the user's explicit acceptance of Q1–Q7. The confirmed
decisions above are the contract direction, not a claim of implemented bindings.

The portable contract separates stable seat/task custody, current occupant
generation, and runtime observation. Binding operations condition mutations and
recover repeated requests; uncertain execution or external effects remain
explicit. Successor orientation can proceed while conflicting writes are blocked.
Routine seat wakes coalesce into a pending reassessment; richer capabilities are
declared without silently weakening the mandatory core. The minimal trust model
is cooperative. Contract-first reuse of Maintainers is approved, with current
upstream progress tracked before concrete extraction decisions.

This settles the semantic direction needed by
[Define ongoing team memory and continuity](06-team-memory.md), then
[Define what a binding migration preserves](04-migration-contract.md) and
[Design the scale-down and scale-up demonstration](05-demonstration-design.md).
Precise declaration syntax, command shapes and panel layout remain design work
under the map; this resolution authorizes no production implementation.
