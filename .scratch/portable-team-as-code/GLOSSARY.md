---
title: "Portable team vocabulary"
description: "Terms settled with the user for portable team ownership and continuity."
status: draft
tier: 2
last_updated: "2026-11-06"
---

# Portable teams

Vocabulary for teams whose roles persist across changes of agent conversation.

## Language

**Seat**: A stable role and address within a team, independent of the conversation
currently filling it. _Avoid_: agent, worker slot.

**Occupant**: The replaceable agent conversation currently filling a seat.
_Avoid_: seat, process.

**Occupant generation**: A distinct tenure of an occupant in a seat, separating
its permission to act from that of preceding or succeeding occupants.
_Avoid_: process ID, model version.

**Task custody**: A seat's continuing responsibility for assigned work, including
across occupant replacement. _Avoid_: conversation ownership, personal todo.

**Runtime observation**: Evidence about an occupant's execution, distinct from
its assignment or permission to act. _Avoid_: ownership proof.

**Routine wake**: A seat-addressed request to reconsider a particular purpose,
with repeated requests for that purpose combined while reassessment is pending.
_Avoid_: interruption, completed work.

**Reassessment**: The current occupant's examination of current state in response
to a pending purpose. _Avoid_: timer tick, delivery attempt.

**Binding capability**: A declared guarantee or behavior available through a
particular binding. _Avoid_: assumed feature, silent fallback.

**Authored knowledge**: Deliberately preserved findings, decisions, rationale and
evidence that support continuity across conversations. _Avoid_: transcript, recollection.

**Team knowledge**: Shared decisions and reusable discoveries relevant across the
team. _Avoid_: all conversation history.

**Seat knowledge**: Role-specific experience belonging to a seat across occupant
changes. _Avoid_: occupant memory.

**Task knowledge**: Rationale, evidence, failed approaches and unresolved questions
associated with particular work. _Avoid_: task status.

**Occupant scratch**: Temporary working notes whose useful content may be
selectively preserved as authored knowledge. _Avoid_: required handover record.

**Consequential inherited claim**: A claim received from prior work whose falsity
could change the next action, its authorization or its outcome.
_Avoid_: every remembered fact.

**Orientation index**: A concise entry point connecting team guidance, seat
knowledge, assigned work and its evidence. _Avoid_: complete context dump.

**Knowledge publication**: A preserved knowledge revision available to its
intended readers. _Avoid_: delivery, incorporation.

**Review at revision**: An occupant's recorded examination of a particular
knowledge revision. _Avoid_: message sent, timeless acknowledgement.

**Interchange package**: A versioned portable representation of team/task state,
authored knowledge and their provenance. _Avoid_: runtime backup, credential bundle.

**Authority cutover**: The explicit transfer of responsibility for authoritative
writes from one binding to another. _Avoid_: data copy, dual-write synchronization.

**Runtime rebinding**: An explicit reassociation of team work with verified
existing or replacement occupants. _Avoid_: import, automatic execution transfer.

**Cutover record**: Retained evidence identifying a migration's source revision,
destination and activation progress. _Avoid_: completion claim, timeout inference.
