---
title: "Define ongoing team memory and continuity"
description: "Decide how portable teams retain, retrieve, and maintain useful knowledge."
status: draft
tier: 2
labels: ["wayfinder:grilling"]
---

# Define ongoing team memory and continuity

Type: grilling
Status: resolved
Assignee: primary AI Wayfinder with user
Blocked by: 02, 03
Parent: [Portable team-as-code: scale down, scale up](../map.md)

## Question

What memory contract and operating skills let a team learn across tasks and
occupant replacements, starting with structured Markdown and Git history?

Use [Compare minimal local operation with the Paseo experience](02-minimal-and-paseo-bindings.md)
and [Agree on the portable team and binding contracts](03-team-and-binding-contract.md).
Decide team, seat, task, and occupant scopes; contribution and shared-update
rules; provenance, confidence and freshness; correction and supersession;
retrieval and successor orientation; and when agents should consult or preserve
knowledge. Distinguish memory from authoritative assignments and raw transcripts.

Specify how discoveries become shared knowledge without endless transcript
accumulation. Decide how successors verify consequential inherited claims and
how richer retrieval remains substitutable. Feed portable knowledge and
provider-specific retention constraints into the migration decision.

Resolve with the human. Success includes explicit continuity criteria for both
the minimal configuration and Paseo, not merely a directory naming convention.

## Comments

2026-11-06: The user explicitly approved dedicated coverage of ongoing team
memory and continuity in the demonstration. Recorded by an AI assistant.

## Discussion

The user requested continuation after resolving the team-and-binding contract.
This is the next unblocked human decision. Structured Markdown/Git memory,
explicit team/seat/task/occupant scopes, and successor verification are already
agreed direction; their operating rules remain to be settled.

### Confirmed by the user — memory Q1–Q3

- Team knowledge holds reusable discoveries and shared decisions; seat knowledge
  holds role-specific experience; task knowledge holds rationale, evidence and
  failed approaches; occupant scratch is temporary until selectively preserved.
  Authored knowledge is the required continuity surface. Transcript exports are
  optional supporting evidence, not required to reconstruct every conversation.
- Occupants can publish sourced findings and explicit corrections within their
  authority. New findings are provisional; an accountable seat maintains shared
  knowledge. Knowledge promotion cannot silently change human decisions,
  permissions or the team contract. Supersession preserves the prior rationale.
- A consequential inherited claim is one whose falsity could change the next
  action, its authorization, or its outcome. Successors verify such claims against
  current evidence before relying on them; inability to verify blocks dependent
  action, not all orientation. Other inherited context retains its source and
  uncertainty without mandatory blanket revalidation.

### Confirmed by the user — memory Q4–Q6

- Use a small orientation index linking team guidance, seat knowledge, assigned
  tasks and their evidence. Consult it on startup/replacement, task admission,
  and before relying on consequential claims. Retrieval returns source references,
  applicability and verification dates rather than only a synthesized answer.
  Richer search/indexes are optional; authoritative Markdown remains readable.
- Publish knowledge before notifying affected seats through coalesced
  reassessment requests. Distinguish published, notification pending and reviewed
  at revision. Sending a message does not prove incorporation. Consequential
  corrections are checked before dependent work; routine discoveries can wait
  for the next relevant task or reassessment.
- Preserve decisions, useful failed approaches, evidence references and correction
  history. Preserve useful scratch at meaningful checkpoints, rather than relying
  on a graceful outgoing handoff. Mark and link superseded entries. Expired
  freshness prompts verification, not deletion. Scratch and selected transcript
  exports have configurable retention; the first demonstration does not
  automatically delete durable knowledge.

### Confirmed by the user — memory Q7

Require the same continuity sequence in both minimal and Paseo configurations:

1. During ordinary work, a builder records a decision, a failed approach and a
   sourced finding.
2. Its conversation becomes unavailable before a final handoff.
3. A replacement follows the orientation index and recovers the rationale without
   the old transcript.
4. It verifies a consequential inherited claim, finds it stale, and publishes a
   correction linked to earlier evidence.
5. Another affected seat reviews that correction at its recorded revision before
   continuing dependent work.
6. One useful discovery becomes shared team knowledge; irrelevant scratch stays
   outside durable memory.

Missing evidence is reported as missing. The successor must not reconstruct
unrecorded reasoning as fact. The walkthrough defines acceptance; future live
execution must establish that the behavior works.

## Answer

Resolved through the user's explicit acceptance of memory Q1–Q7. Authored
knowledge provides continuity across conversations, with team, seat and task
scopes plus selectively preserved occupant scratch. Sourced provisional findings,
accountable maintenance and linked corrections preserve learning without silently
changing human decisions. Orientation exposes evidence and applicability;
consequential claims require current verification before dependent action.
Publication, notification and review at revision are distinct. Checkpointing
supports abrupt conversation loss; selective retention preserves rationale and
supersession rather than accumulating all transcripts.

The accepted sequence above is the continuity acceptance criterion for
[Design the scale-down and scale-up demonstration](05-demonstration-design.md).
[Define what a binding migration preserves](04-migration-contract.md) is now
unblocked and must preserve this knowledge contract. No live demonstration or
production implementation has been performed by resolving this decision.
