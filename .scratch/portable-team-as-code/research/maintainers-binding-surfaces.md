---
title: "Maintainers coordination binding surfaces"
description: "Source-backed research on task authority, replaceable occupants, execution observations, and portable persistence seams."
status: draft
tier: 2
last_updated: "2026-11-06"
---

# Maintainers coordination binding surfaces

> Superseding clarification, 2026-11-06: Will confirmed to the user that GitHub
> issues are authoritative and local issue metadata is a cache. This report's
> operational task-record findings must not be generalized to issue authority.
> Session/generation comparison and explicit recovery have also since merged.
> See the [upstream watch](upstream-binding-watch.md) for current pins and limits;
> the evidence below remains a historical baseline, not a current inventory.

AI-assisted research. Observations, documented plans, user direction, and
recommendations are distinguished below; none settles the user's design decisions.
Static inspection only, with authorized public primary-source reads.

## Answer in brief

Maintainers supplies useful **invariants**, but not a swappable task-persistence
interface. Task JSON combines lifecycle, owner/worker leases, and domain receipts;
several callers directly read its layout and process identity. Reuse the rules
for conditional transitions, evidence applicability, ambiguous-effect recovery,
and single authority. Do not equate a new Markdown serializer with portability.
Stable seats and replaceable occupants need an explicit seam above host observation.

The published GitHub paths observe PRs, issues, Projects, and outcomes. The planned
ownership mirror remains local-first; it cannot implement the user's different
target of native-issue authority merely by changing configuration. GitLab ownership
parity is planned. Will's additional unpublished work is **unknown**, not absent.

## Scope, source pins, and observation freshness

- Local source baseline: `f21052d6097cd40164d7f7c42a0e6f7bf361701b` (B below).
- Public main observed: `ffe271e2a5f669eef8efbcf8f293355ffe99eee2` (M below).
  [Comparison](https://github.com/GSA-TTS/agentic-coding-maintainers/compare/f21052d6097cd40164d7f7c42a0e6f7bf361701b...ffe271e2a5f669eef8efbcf8f293355ffe99eee2)
  contains #123 shared-authority wrapper and #124 review-output guidance;
  core coordinator, monitor, and domain implementations are unchanged.
- Read session on 2026-11-06, bounded by recorded checkpoint `2026-11-06T05:51:24Z`:
  branches were main and Dependabot; `gh pr list --state all --limit 100` returned
  the published PR history within that bound. This is not evidence about forks,
  private repositories, local branches, or unpublished work.
- Native ownership #116, mirror #117, guarded branch effect #118, GitLab #119,
  and effects/outbox #68 were OPEN when queried. Issue bodies are mutable plans;
  the observations below record their scope rather than treating them as code.
- Original skill provenance records William Zujkowski's authorized import from
  `review_things`, base `c9248ac748ee3835df5b837ae8009fce4c3a389b`; imported files
  were uncommitted and bound by `SOURCE-SHA256SUMS` [E18]. Preserve both provenance
  and the later Maintainers pin in any reuse.

## Evidence table: pinned implementation and documentation

All source links are commit-pinned. B/M mean the revisions above; line ranges
refer to those exact files. Paths under the skill use its actual canonical copy.

| ID | Pinned path and lines | What it establishes |
| --- | --- | --- |
| E1 | [B: orchestrator-state.py 300–369](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py#L300-L369) | Task schema, fixed kinds, PID worker, leases, candidate extension validation. |
| E2 | [B: orchestrator-state.py 210–214, 241–270](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py#L210-L270) | Hardcoded task.json path, bounded serialization, replacement/fsync and ambiguous durability. |
| E3 | [B: orchestrator-state.py 437–540](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py#L437-L540) | Coordinator lock, revision write, token-fenced reservations, PID+lstart metadata. |
| E4 | [B: orchestrator-state.py 543–635](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py#L543-L635) | Creation validates worktree/branch/head, excludes path overlap and reserves scope. |
| E5 | [B: orchestrator-state.py 709–828](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py#L709-L828) | Claim reserves capacity; transition intent precedes release; readiness/rework gates. |
| E6 | [B: orchestrator-state.py 999–1184](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py#L999-L1184) | Bidirectional reservation checks, interrupted-intent recovery, host/process reconciliation. |
| E7 | [M: bin/orchestrator-state.sh 9–45](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/ffe271e2a5f669eef8efbcf8f293355ffe99eee2/bin/orchestrator-state.sh#L9-L45) | Linked worktree must explicitly select its physical shared-Git primary authority. |
| E8 | [B: docs/NATIVE-OWNERSHIP.md 45–145](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/docs/NATIVE-OWNERSHIP.md#L45-L145) | Static three-record comparison; native authentication and action fencing unimplemented. |
| E9 | [B: orchestrator-monitor.py 235–347](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py#L235-L347) | Direct JSON/slot/PID reads; gh PR and Project observation transports. |
| E10 | [B: DURABLE-PR-MONITOR.md 11–65](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/docs/DURABLE-PR-MONITOR.md#L11-L65) | As-of coverage and material generations, foreground-only runtime, JSON authority. |
| E11 | [B: candidate-binding.py 207–278](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/candidate-binding.py#L207-L278) | Task receipt commits first; journal acknowledgment is repairable and advisory. |
| E12 | [B: CANDIDATE-BINDING.md 31–65](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/docs/CANDIDATE-BINDING.md#L31-L65) | Incarnation derivation; one immutable PR provenance association, not admission. |
| E13 | [B: foreground-delivery.py 421–588](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/foreground-delivery.py#L421-L588) | Receipt replay before revision check, domain dispatch, lock-held persistence and PID checks. |
| E14 | [B: EXECUTION-OBSERVER.md 39–92](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/docs/EXECUTION-OBSERVER.md#L39-L92) | Durable pre-dispatch intent; child identity differs from guest stop proof. |
| E15 | [B: REVIEW-PROTOCOL.md 66–117](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/docs/REVIEW-PROTOCOL.md#L66-L117) | Native-session/fake assignments, retained generations, claims versus execution evidence. |
| E16 | [B: review-reservation.py 30–58, 88–139](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/review-reservation.py#L30-L139) | Destination reservation and receipts; launch_authorized remains false. |
| E17 | [B: MAINTAINER-SERVICE.md 20–25, 52–89](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/docs/MAINTAINER-SERVICE.md#L20-L89) | Proposed effects, separate capabilities, no second lifecycle; migration requirements. |
| E18 | [B: PROVENANCE.md 3–16](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/PROVENANCE.md#L3-L16) | Import lineage and author; does not inventory later unpublished work. |
| E19 | [B: scripts/evaluate-workflow.py 44–98](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/scripts/evaluate-workflow.py#L44-L98) | Evaluator directly enumerates JSON records using installed validator. |
| E20 | [B: scripts/review-workspace-preflight.py 278–339](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/scripts/review-workspace-preflight.py#L278-L339) | Portable-upgrade inspection is also coupled to kinds, PID and task.json layout. |
| E21 | [Git: git-update-ref.adoc 21–28, 139–162](https://github.com/git/git/blob/0ffa3e35c7c82ab8d0de226149fb03b3f7674d05/Documentation/git-update-ref.adoc#L21-L162) | Expected-old-object conditional ref update; multiple refs are not a reader-atomic snapshot. |

## Actual read, write, claim, reconcile, and extension paths

1. **Entry/read:** repository wrapper → skill `run.sh state` → Python state CLI.
   `read_task` validates JSON; `list` enumerates `*/task.json`. The CLI initializes
   state directories even for show/list. M's wrapper prevents accidental separate
   linked-worktree stores, but direct skill consumers bypass this wrapper [E2–E3,E7].
2. **Create/claim:** create locks the coordinator, validates existing reservations,
   excludes scope/resource collisions, and reserves scope before Ready persistence.
   Claim accepts Ready/Rework, observes the supplied PID, reserves a global slot,
   sets owner/worker and writes Claimed. A random worker ID is not session
   authentication. Creation and claim are distinct operations [E3–E5,E8].
3. **Transition/write:** an implementation lane is separately reserved; durable
   transition intent precedes capacity/scope release and final state. Unknown is
   a degraded result, not a worker-selected state. `write_task` increments revision,
   but base claim/transition commands do not expose a universal expected-revision
   or operation-receipt contract. Newer domain operations supply those checks [E3,E5,E13].
4. **Reconcile:** inspect both task→reservation and reservation→task consistency;
   finish retained intents only after rechecking gates. Different host or reused
   PID is unknown. An absent worker or missing worktree can become Blocked only
   after execution and repair settlement checks; no timeout grants takeover [E6,E14].
5. **Extend:** domain modules import coordinator functions, mutate validated record
   copies, and persist through the lock/atomic-write implementation. Foreground
   delivery composes these operations and receipts; candidate binding durably
   commits task provenance before optional SQLite acknowledgment [E11,E13].

**Coupled callers to include in any replacement assessment:** monitor's direct
task/slot/PID reader; foreground delivery's strict file read and liveness check;
candidate binding's task-file fsync; execution-observe's task-file enumeration;
review-evidence, review-collect, review-accept, execution-plan, repair-apply and
repair-proposal's coordinator imports; native preflight, evaluator and workspace
upgrade reader [E8–E9,E11,E13,E19–E20]. Changing `read_task/write_task` alone misses
enumeration, lock-held callbacks, private artifact paths, and duplicate validators.

## State concepts: reuse versus missing interfaces

| Concept | Existing evidence | Missing portable distinction / recommendation |
| --- | --- | --- |
| Task | Task ID, revision, scope, criteria, dependencies, head, lifecycle [E1,E4]. | Explicit authority identity and portable task identity; selected native issue must be authority rather than a tracker-number mirror. |
| Team / seat | Owner string and ephemeral global-slot index [E1,E3]. | Stable team/seat identity independent of slot or person; accountable ownership policy remains a human choice. |
| Occupant | Worker embeds owner, UUID, PID, lstart, hostname [E3]. | Runtime-qualified conversation identity and occupant generation, allowing replacement without pretending the team changed. |
| Attempt | Review assignment/session, admission and destination reservation [E15–E16]. | A consistent attempt identity and dispatch/stop contract across local CLI and Paseo; a reservation alone never proves launch. |
| Observation | Poll generations/coverage, runtime collection, execution termination [E10,E14–E15]. | Capability-qualified host observation with provenance and applicability; distinguish unavailable, absent, busy, stopped and completed. |
| Effect receipt | Domain request digest, immutable result and intent recovery [E11,E13]. | Common conditional mutation/replay semantics; generic remote outbox and ownership effects are still planned [E17]. |
| Knowledge | Findings, counterevidence, generations and bounded handoffs [E15]. | Team/seat/task/occupant knowledge scopes, retrieval, source freshness, correction, sharing and selective preservation; not supplied by task prose arrays. |

Process identity is valid evidence for a process-bound runtime, not a universal
occupant identifier. A shared server PID cannot distinguish its conversations.
The supplied OpenCode/Paseo architecture context makes this mismatch relevant;
this report did not independently requalify either installed runtime. Existing
session-aware review records do not repair base claim admission [E3,E9,E15].

## Published forge surfaces versus plans and unknown work

- **Implemented GitHub observations:** foreground PR/Project monitor [E9–E10];
  [bounded Issues scans](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/docs/GITHUB-ISSUES-OBSERVATION.md#L3-L8),
  [historical review requests](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/docs/REVIEW-REQUEST-OBSERVATION.md#L3-L10),
  and [merge observation](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/docs/MERGE-OBSERVATION.md#L3-L29).
  Cross-repo epic/portfolio tools also read GitHub GraphQL; these are read paths,
  not an authoritative task binding or forge-independent persistence interface.
- **Implemented ownership support:** retained-state preflight [E8], shared-root
  wrapper [E7], local reservations and conditional domain receipts [E3,E13].
- **Planned:** [#116](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/116)
  native session ownership; [#117](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/117)
  local-first assignment/comment mirror; [#118](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/118)
  expected-head branch updates; [#68](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/68)
  restricted effects/outbox. A comment or assignment is not a distributed lock.
- **GitLab:** [#119](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/119)
  explicitly plans parity after GitHub qualification and a concrete versioned
  consumer. It names instance/project-ID/IID distinctions, assignment replacement,
  normalized notes/quick actions and conditional-operation gaps. No implemented
  GitLab task adapter was located in the inspected published source.
- **Will's other work:** request its repository/path and immutable revision before
  assessing reuse. Do not infer nonexistent work from this repository's inventory.

## Targeted deep-interface recommendations, not decisions

**One authority module, small semantic interface.** Explore `read/query` returning
an authority-qualified revision plus explicit coverage, and `apply` accepting a
typed intent, operation ID/digest, expected revision and occupant/attempt context.
`apply` should own invariant checking, publication and receipt replay. Put
host execution observation at a separate seam so callers never translate PIDs
into team ownership. Avoid a generic key/value store that exports all current
locking, phase ordering and recovery complexity to every skill [E3,E6,E13–E14].

**Markdown/Git can replace JSON authority, conditionally.** The candidate local
adapter could publish validated Markdown task state plus operation receipts in
one commit, then compare-and-swap one designated authority ref [E21]. Read the
same committed tree for an operation's snapshot. A second competing publication
must fail its expected-old-ref check; inspect/reconcile rather than silently
merge two claims. Ordinary editing/committing alone does not enforce lifecycle.
Git ref success is not proof an external effect occurred or a worker stopped.
Crash durability, object retention and deployment-version behavior need qualification.

Keep JSON only as a derived export/cache if Markdown becomes authoritative;
retaining two writable lifecycle stores defeats the replacement. Existing private
PID/token/runtime receipts should not be copied wholesale into shared Markdown.
Private observation storage can coexist if it cannot independently assign tasks
or advance lifecycle. No database is inherently required by this proposal.

**Native-issue authority needs its own demonstrated adapter.** Reuse observation
and receipt rules, not #117's local-first ownership semantics. Establish which
native fields carry state, how concurrent human edits and missing conditional
updates are handled, and what capabilities are unavailable. Local attempt records
may remain operational evidence; they must not become an undisclosed task mirror.
One adapter is a hypothetical seam; prove the second rather than inventing a forge framework.

**Migration and execution rebinding are separate.** Export/import can preserve
task identity, decisions, failed approaches, sources and correction history.
Authority cutover needs a designated old/new authority and generation, settled
effects, preserved evidence and explicit activation; importing data cannot prove
an old occupant stopped. A new occupant must reverify consequential inherited
claims. Knowledge should be referenced with scope, source revision, applicability
and supersession; receipt replay is historical evidence, not current truth [E12,E15,E17].
Human edit rules, handoff authorization, exact migration protocol, and memory
sharing/retention remain open decisions in the primary map.

## Validation and limits

- Read/grep/git metadata inspection and authorized `gh` GET/query calls only;
  no candidate code, tests, build, service, commit, push or remote edit executed.
- Git documentation website fetch failed with a transport error; source read via
  `gh api` at the pinned Git revision supplied E21 instead. No claim of runtime proof.
- Citation validation checks pinned paths and line bounds; no relative local
  Markdown links are used. Verification results are reported with the handoff.
- This single research artifact is the only authored file. The primary map and
  tickets remain primary-owned; recommendations here are not adopted architecture.
