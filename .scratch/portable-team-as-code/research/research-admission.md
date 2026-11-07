---
title: "Research-only admission and source baseline"
description: "Scoped operator authorization, research ownership, and observed runtime-admission mismatch."
status: draft
tier: 2
last_updated: "2026-11-06"
---

# Research-only admission and source baseline

AI-authored operating record for [Portable team-as-code](../map.md).

Publication copy: private runtime identifiers are omitted. The original local
record is retained outside Git. Models, source revisions and research outcomes
remain below so the methodological evidence is preserved.

## Authorization and scope

On 2026-11-06 the user explicitly authorized a temporary research-only admission
ledger keyed to Paseo agent/session IDs, reservations before launch, the existing
six-worker ceiling, separate workspaces, and Paseo completion observation.
The user clarified that this is an outside wayfinding effort hosted in
Maintainers; evaluating its skills does not require reproducing their design.
This is a scoped exception for two researchers, not a repository-policy edit,
PID-verified claim, implementation authorization, or service activation.

The previously approved scoped-edit plan continues: primary owns this record,
the map and tickets; researchers own separate evidence assets. Verify Markdown
metadata, links, dependencies, source pins, and factual citations on integration.
No research branch push is authorized by this record.

## Reservations before launch

| Seat | Reserved capacity | Workspace | Branch | Owned artifact |
| --- | --- | --- | --- | --- |
| Coordination bindings researcher | research slot 1 of 6 | Separate Maintainers worktree | `research/portable-team-coordination` | `.scratch/portable-team-as-code/research/maintainers-binding-surfaces.md` |
| Runtime bindings researcher | research slot 2 of 6 | Separate Maintainers worktree | `research/portable-team-runtimes` | `.scratch/portable-team-as-code/research/minimal-and-paseo-bindings.md` |

Both workspaces are explicit children of the Maintainers project, based on
`f21052d6097cd40164d7f7c42a0e6f7bf361701b`. Neither owns the primary map.
No nested delegation is authorized. Two research workers, zero implementation
lanes; preserve two additional slots for review if later authorized.
Launch acknowledgements on 2026-11-06:

| Seat | Paseo agent | Model | Observation |
| --- | --- | --- | --- |
| Coordination bindings researcher | Private identifier omitted | OpenCode `usai/gpt-6-astra`, high reasoning | Launch acknowledged, running |
| Runtime bindings researcher | Private identifier omitted | OpenCode `usai/claude-opus-5`, high reasoning | Launch acknowledged, running |

Launch acknowledgements do not expose native session IDs. Retain those on
completion when available, without treating missing session identity as verified.
Finish notifications are enabled; no polling or recurring monitor is active.

### Coordination researcher recovery

At `2026-11-06T06:00:00.338Z`, Paseo reported the coordination researcher errored:
`Timed out waiting for response data`. Event-triggered inspection confirmed
status `error`, no active turn, and the retained native session identity.
Recent activity showed source reads/searches;
no Markdown research artifact was found in its assigned effort directory.
The cause of the response timeout is unverified. Retain its reservation and
resume the same conversation once, asking for an immediate bounded evidence
checkpoint rather than restarting discovery. No new worker or ownership transfer
is involved; research completion remains unverified pending the report.

At `2026-11-06T06:05:04.850Z`, the recovered agent snapshot reported `idle` with
no active turn; a finish notification and complete 202-line report were received.
The primary read the report, spot-checked central source claims, and copied the
artifact into the primary research directory, retaining the worker's original.
Research slot 1 is released. Runtime research retains slot 2; no other research
worker has been admitted. The research ticket is resolved, with recommendations
left for the human contract decision. The copy command emitted a portability
warning about its no-clobber option; byte equality is checked independently.

Runtime researcher subsequently returned its 910-line report and a finish
notification, with native session identity retained privately.
Primary preserved the original in the worker
workspace and integrated a corrected copy, with explicit inference corrections.
Research slot 2 is released; no research workers remain active by received finish
notifications. The researcher reported a nested reviewer despite the dispatch's
explicit no-nested-delegation constraint. This was not separately admitted, and
its transcript/identity were not independently inspected by primary; its claimed
review is not treated as verified independent approval. Future dispatch must
explicitly reconcile skill-driven review requests with the no-nesting limit.
This process deviation does not establish the source claims; primary's review and
the report's stated source/behavior limitations are retained separately.

## Observed admission mismatch

Local inspection on 2026-11-06:

- `bin/orchestrator-state.sh reconcile`: exit 0,
  `{"changed": [], "state": "CURRENT"}`.
- `bin/orchestrator-state.sh list`: exit 0, `[]`.
- `opencode --version`: `opencode v2.0.30`.
- `opencode api get /api/info`: reports version, service PID, URL and
  persistent-PTY capability, not per-conversation process ownership.
- Paseo agent status exposes native session ID and active-turn metadata;
  the inspected snapshot does not expose a session-exclusive worker PID.

At the pinned Maintainers baseline, `orchestrator-state.py` uses
`ps -p PID -o lstart=` for worker identity (lines 515–540), reserves capacity
only after that observation (709–740), and accepts task kinds implementation,
review, or monitor (1195–1217). The operator guide requires the actual work-owning
process, not a parent shell. A shared server PID cannot establish an individual
conversation's completion. Workspace separation cannot repair that mismatch.
The bounded probes found no honest PID/session binding; they do not prove no
such facility could exist elsewhere.

This is evidence for separating stable ownership, replaceable conversation
identity, and execution observation in the design. It is not a completed binding
contract or a human design decision.

## Source freshness

Live GitHub branch discovery returned `main` at
`ffe271e2a5f669eef8efbcf8f293355ffe99eee2` and one Dependabot branch. Compared
with the research baseline, main includes shared-authority wrapper admission
and review-output documentation changes. The core state implementation was
not listed as changed. Researchers must distinguish these revisions.

- [Shared-authority wrapper](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/ffe271e2a5f669eef8efbcf8f293355ffe99eee2/bin/orchestrator-state.sh)
- [Native ownership: implemented preflight and proposed contract](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/ffe271e2a5f669eef8efbcf8f293355ffe99eee2/docs/NATIVE-OWNERSHIP.md)
- [Session-aware native ownership](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/116): open at observation.
- [GitHub ownership mirror](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/117): open; local-first mirror, not native task authority.
- [GitLab parity](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/119): open; planned capability work.

## Retrieval limitations

The public OpenCode V2 API documentation request failed with a transport error.
The GitHub tree request for `GSA-TTS/agentic-coding-kits` returned 404; this does
not establish repository absence. The Paseo kit tree was found under Patterns
at `integrations/isolation/acq-kits/paseo`. Its version remains to be verified.

No human-decision ticket has been answered by this admission exception.

## Verification transcript

2026-11-06, AI coordinator: ran a read-only Python standard-library check over
all effort Markdown files for required frontmatter keys, local link existence,
ticket state fields, blocker existence, and dependency cycles. Result: PASS,
eight documents and six acyclic decision tickets. This checks document structure,
not source truth, model findings, or implementation behavior. No candidate code,
unit tests, integration tests, security scans, or builds ran for these local
research records; no review or production-readiness claim is made.
