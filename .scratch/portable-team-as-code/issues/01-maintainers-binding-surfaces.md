---
title: "Locate reusable coordination and missing binding interfaces"
description: "Investigate Maintainers task authority, runtime coupling, and adapter work."
status: draft
tier: 2
labels: ["wayfinder:research"]
---

# Locate reusable coordination and missing binding interfaces

Type: research
Status: resolved
Assignee: coordination-bindings-researcher (AI)
Blocked by: none
Parent: [Portable team-as-code: scale down, scale up](../map.md)

## Question

Which existing Maintainers interfaces and invariants can support authoritative
task bindings, and what interfaces are missing to separate stable team ownership,
replaceable occupants, and host-specific execution observation?

Trace actual read/write/claim/reconcile paths, not just terminology. Establish
whether reported GitHub/GitLab adapters exist in published source, another
identified location, or only planned work. Record unavailable evidence without
assuming the colleague's unpublished work does not exist.

Identify which state belongs to tasks, seats, runtime attempts, observations,
and effect receipts. Examine whether a local Markdown/Git binding could replace
persistence without duplicating lifecycle authority. Provide a source-linked
reuse/gap assessment, not a new implementation.

## Comments

2026-11-06: Created by an AI assistant from the user-approved research scope.
Earlier inspection found local task JSON authority and planned ownership mirrors;
verify and cite those findings in the research asset.

2026-11-06: Successor Wayfinder reserved this investigation for a separate
Paseo workspace under the Maintainers project. See the
[research admission record](../research/research-admission.md). Researcher owns
`research/maintainers-binding-surfaces.md` in its assigned workspace; the primary
Wayfinder alone integrates findings and resolves this ticket.

## Answer

Superseding clarification, 2026-11-06: Will confirmed GitHub issue authority with
local metadata caching; the baseline operational-record findings below do not
establish that issue metadata is locally authoritative. Session-bound core
mutation and recovery work has since merged. See the
[upstream watch](../research/upstream-binding-watch.md) for source pins and the
remaining distinction between cached metadata, coordination records and a
general portable interface. Research resolution is historical, not a claim that
upstream stopped changing.

2026-11-06, AI Wayfinder: resolved as a source investigation, not approval of an
architecture. The [source-backed report](../research/maintainers-binding-surfaces.md)
is preserved from the researcher's separate workspace.

Maintainers supplies reusable transition, reservation, evidence-applicability,
receipt-replay, and ambiguous-effect recovery rules. It does not supply an
interchangeable task-persistence interface: monitor, foreground delivery,
candidate binding, execution enumeration, and preflight/evaluation consumers
couple to task JSON, file layout, or PID identity beyond `read_task/write_task`.
Stable team/seat identity and replaceable occupant generation require explicit
separation from host execution observations.

Published GitHub observation paths exist. The local-first ownership mirror and
GitLab parity are planned work; they do not establish native-issue task authority.
Will's unseen work remains unknown pending an identified source and revision.

The report recommends investigating a small authority read/query plus conditional
apply interface, with separate execution observation. Markdown/Git conditional
publication is a candidate, not a qualified implementation. Native-issue authority
needs its own demonstrated guarantees. These choices remain with
[Agree on the portable team and binding contracts](03-team-and-binding-contract.md).

Verification: primary read the complete report and spot-checked direct monitor
JSON/PID checks, candidate receipt persistence, and foreground revision/replay/
PID checks against baseline source. Researcher reports 24 pinned source citations
validated for paths and line bounds. No runtime behavior was tested. Primary
integration checks verify an exact copy plus local metadata/links/dependencies.
