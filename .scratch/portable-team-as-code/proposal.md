---
title: "Portable teams: evolving Maintainers into reusable bindings"
description: "Evidence-backed proposal mapping agreed portable-team contracts to existing Maintainers modules and a bounded demonstration."
status: draft
tier: 2
last_updated: "2026-11-06"
---

# Portable teams: evolving Maintainers into reusable bindings

AI-assisted design proposal for the user and Will. **Recommendation:** expose
Maintainers' coordination rules through a small portable interface, retain its
forge/runtime expertise behind bindings, and add stable seats plus authored
knowledge. Demonstrate the same team skills using a minimal CLI profile and Paseo.

This is a design for review, not implemented behavior. The semantic direction
and demonstration bounds were accepted in the [decision map](map.md).
Module placement, interface names and configuration examples below are proposed.

## 1. Start from what Maintainers already does

**GitHub issues are authoritative; locally cached issue metadata is an
optimization.** Will confirmed this through the user. Local coordination claims,
execution attempts and operation receipts are different facts. The earlier
research inferred too much from `task.json`; that correction is incorporated here.

Published source also contains useful work beyond the initial research baseline:

| Source | Evidence and significance |
| --- | --- |
| Main `b2d052fa74e8f1e7ba316677786c6ca882ece77a` | Current snapshot for this proposal; reviewed 2026-11-06. |
| [Cooperative session-bound lifecycle](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/128) | Merged: opt-in generation/session/revision comparisons. Adopt its cooperative fencing semantics rather than reinventing them. |
| [Explicit interrupted-task recovery](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/133) | Merged: retained pending/settled recovery evidence and guarded recovery to Blocked. |
| [Acknowledged cooperative handoff](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/135) | Merged: release is distinct from stopping the old worker; successor claim is a new generation. |
| [Current ownership documentation](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/b2d052fa74e8f1e7ba316677786c6ca882ece77a/docs/NATIVE-OWNERSHIP.md) | Pilot remains core-CLI-only, requires PID observations, and rejects unsupported domain/monitor consumers. It is not yet a general runtime binding. |

The [upstream watch](research/upstream-binding-watch.md) tracks the broader
session, forge and recovery work. Will reports decoupling in flight; identify
and adopt that concrete interface before committing to a parallel extraction.
Neither an absent public PR nor this source snapshot disproves unpublished work.

## 2. The proposed change map for Will

Paths below are in `.agents/skills/workspace-orchestrator/` unless prefixed
otherwise. **Adopt** means preserve behavior/provenance; it does not promise
byte-for-byte reuse before dependencies are separated.

| Existing implementation | Treatment | Concrete proposed change | Evidence / qualification |
| --- | --- | --- | --- |
| `bin/orchestrator-state.py`: transitions, scope conflicts, reservations | **Adopt + decouple** | Keep single-owner, conditional-transition and ambiguity rules; make storage publication and execution observation dependencies of the coordination module. | [Baseline evidence E3–E6](research/maintainers-binding-surfaces.md); current core still owns these rules. |
| `validate_cooperative_binding`, `command_claim`, `require_cooperative_mutation` | **Adopt + amend** | Carry existing generation/revision comparisons forward. Add stable team/seat custody and runtime-qualified occupant reference; separate occupant tenure from a per-task claim attempt. Do not treat arbitrary session labels as authenticated identity. | [Current schema validation](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/b2d052fa74e8f1e7ba316677786c6ca882ece77a/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py#L394-L424), [claim/mutation](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/b2d052fa74e8f1e7ba316677786c6ca882ece77a/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py#L863-L967). |
| `read_task`, `write_task`, `task_path`, task enumeration | **Decouple; replace storage per binding** | Remove direct layout knowledge from callers. Markdown/Git becomes the minimal binding's authority; existing private coordination storage may remain behind a Maintainers binding. Preserve GitHub as issue authority and its cache as derived data. | [Current direct JSON I/O](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/b2d052fa74e8f1e7ba316677786c6ca882ece77a/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py#L615-L626). Changing two functions alone misses consumers below. |
| `process_identity`, `worker_metadata`; PID tests inside claim/recovery | **Decouple, retain as a runtime implementation** | Process identity remains valid for a process-bound worker. Paseo uses agent/session/turn observations; the shared server PID cannot stand in for a conversation. Both return explicit observation limits. | [Current recovery stop gate](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/b2d052fa74e8f1e7ba316677786c6ca882ece77a/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py#L1450-L1466); [runtime research](research/minimal-and-paseo-bindings.md). |
| `command_recover`, transition intents, `transition_recovery` | **Adopt + amend** | Preserve observe-before-retry, retained evidence and refusal to infer termination. Express runtime proof through the observation seam; keep incompatible legacy readers refusing new records. | Merged recovery and handoff work above. A portable migration is not a schema downgrade. |
| `bin/foreground-delivery.py`, domain receipts | **Adopt + decouple** | Preserve operation-ID/digest replay, expected revision, evidence gates and domain results. Replace direct file reads, PID checks and lock-held persistence callbacks with semantic binding operations. | [Replay and current-revision behavior](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/foreground-delivery.py#L421-L550); file unchanged in current comparison. |
| `bin/orchestrator-monitor.py`, observation journal | **Adopt + decouple** | Keep bounded forge reads, coverage and as-of observations. Remove assumptions that every observer owns a PID-shaped task record. Retain optional SQLite as an observation optimization, not a minimal-team dependency. | [Direct task/slot/PID reader](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/orchestrator-monitor.py#L235-L257); newer source adds explicit schema-3 refusal. |
| `bin/candidate-binding.py` | **Adopt provenance semantics; decouple durability** | Keep immutable task-to-PR observation association and receipt-before-journal-ack ordering. Replace its direct task-file durability barrier with binding publication. This is not the task-storage adapter. | [Receipt ordering](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/f21052d6097cd40164d7f7c42a0e6f7bf361701b/.agents/skills/workspace-orchestrator/bin/candidate-binding.py#L207-L278). |
| `execution-observe.py`, review/repair modules | **Keep specialized; amend callers** | Preserve evidence-bound review, repair and stop semantics for Maintainers workflows. Let them consume portable identities and observations without making every small team install the full review stack. | [Execution/review evidence E14–E16](research/maintainers-binding-surfaces.md). |
| Root `scripts/evaluate-workflow.py`, `scripts/review-workspace-preflight.py`, native ownership preflight | **Amend explicitly** | Replace schema/layout assumptions where portability is supported; otherwise report unsupported. Do not silently admit a new binding through an old validator. | [Consumer evidence E8/E19/E20](research/maintainers-binding-surfaces.md). |
| Maintainers skill/profile guidance and provenance | **Adopt judgment patterns; separate role from launch settings** | Portable skills teach assignment, evidence, recovery and knowledge maintenance; installed model/provider/profile choices belong to bindings. Preserve original import lineage and canonical revisions when extracting content. | [Provenance evidence E18](research/maintainers-binding-surfaces.md). |
| Native GitHub issue reads/cache and planned effects | **Retain + expose through task binding** | Preserve issue truth, immutable native references and cache freshness. Map portable task reads/mutations to native semantics; operation receipts remain operational evidence rather than a second editable issue database. | Will's confirmation; [journal](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/67), [effects](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/68), [ownership publication](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/117). Exact cache interface needs mapping with Will. |
| Stable seats, ongoing knowledge, seat wake intent, team panel | **Add narrowly** | Supply the missing portable concepts around existing coordination rules; add a read-mostly Paseo projection, not another scheduler or task lifecycle. | Accepted contract/memory/demo decisions in the map. |

This is an extraction/adaptation path, not a proposal to replace Maintainers
wholesale or recast its GitHub data as locally authoritative. The first demo
substitutes task storage and runtime bindings; production migration requires
the accepted cutover protocol and compatible readers.

## 3. Ownership of facts

| Fact | Owner in minimal profile | Owner in Maintainers/GitHub profile |
| --- | --- | --- |
| Task description, state, dependencies | Selected Markdown/Git task binding | GitHub issue binding; local metadata is a cache |
| Seat custody, occupant generation, operation results | Coordination binding | Coordination binding, linked to native task identity |
| Execution/stop/turn observations | Runtime binding | Runtime binding, including existing process/container collectors where applicable |
| Authored knowledge and corrections | Markdown/Git knowledge binding | Same default; richer retrieval may be substituted |
| Pending reassessment purpose | Coordination wake record | Same semantics; scheduler merely triggers evaluation |
| Transcript history | Model harness | Model harness, possibly surfaced through Paseo |

One authority per fact does not mean every fact must live in one database.
Cross-store operations need retained intent, applicability checks and reconciled
outcomes; a native issue update and local receipt are not one atomic transaction.
Where a forge cannot support a required conditional mutation, the binding must
provide a qualified cooperative mechanism or refuse that operation. A cache
timestamp or issue comment is not sufficient proof of exclusion.

## 4. Small semantic interfaces — proposed shape

The skill caller should know intentions and outcomes, not filesystem locks,
schema versions, process probes or HTTP retry details. Illustrative operations:

| Module interface | Inputs / results | Complexity kept inside |
| --- | --- | --- |
| `inspect` / `query` | Qualified task/seat reference → state, revision, provenance, coverage and capabilities | Native mappings, cache freshness, bounded reads, missing evidence |
| `apply` | Typed intent + operation ID + expected revision + occupant generation → recorded result or explicit refusal/unknown | Scope conflict checks, publication, operation replay, recovery |
| `observeExecution` | Qualified occupant/attempt → observed status, evidence, observation time and limits | PID, container, CLI-server or Paseo-specific inspection |
| `requestWake` / `reassessPending` | Seat + purpose → one retained pending reassessment and its outcome | Duplicate ticks, busy recipients, restart, delivery versus completed judgment |
| `orient` / knowledge publication and review | Scope + revision → addressed evidence; conditional knowledge update/review record | Sources, supersession, affected-seat notices, optional search indexes |
| Export / validate / activate cutover | Versioned package and expected source/destination state → preservation and cutover records | Native mappings, unsupported fields, interrupted activation, authority fencing |

These are semantic operations, not six new services. Start with a CLI facade
over shared modules; the panel calls the same operations. Existing domains may
keep specialized operations behind that interface. Avoid a generic key/value
adapter that leaves every caller implementing transitions and recovery again.

An illustrative mutation envelope:

```yaml
operation: claim-task
operation_id: demo-claim-001
task: {binding: local-tasks, id: repair-link}
expected_revision: task-r3
caller: {team: docs-team, seat: builder, occupant_generation: 2}
```

Request replay returns the original result, not permission for a stale occupant
to take a new action. Changed content under the same ID is rejected. A caller
must obtain current state before subsequent work; historical success is not
current authorization. External effects with lost responses require observation
before retry. Cooperative generation checks are not same-account authentication.

## 5. Minimal profile and Paseo profile

Proposed declaration, showing responsibilities rather than final syntax:

```yaml
team: docs-team
seats: [coordinator, builder, reviewer]
skills: ./skills
bindings:
  tasks: {kind: markdown-git, root: ./tasks}
  knowledge: {kind: markdown-git, root: ./knowledge}
  runtime: {kind: cli, harness: opencode}
  wakes: {kind: foreground-tick}
```

Paseo changes runtime/launch settings and wake trigger configuration, adds panel
registration, and retains the same skills and task/knowledge semantics. Model
selection is configuration, not seat identity. Role instructions remain portable
files; Paseo launch profiles supply provider/model/mode settings.

The minimal runtime floor is Git, Python standard library and one harness with
its own declared dependencies. OpenCode has a server and persistence internally;
CLI access does not remove those dependencies. No separate team database, cron,
tmux or flock package is required by the accepted target.

**Proposed local publication:** construct a validated committed tree and
conditionally update one authority ref using its expected prior value. Readers
use that tree as their snapshot. The authority revision includes state and
operation outcomes, so a concurrent loser reconciles rather than overwriting.
No model turn runs while holding a publication lock. Ordinary uncommitted edits
are drafts, not admitted transitions. Durability/crash behavior still requires
qualification; Git atomic publication does not establish external-effect success.

**Paseo wake binding:** schedule a bounded invocation of the team wake operation,
not one permanent heartbeat per disposable occupant. Keep the pending purpose
outside the agent conversation. The binding resolves the current occupant when
delivery is appropriate. Native heartbeats refuse busy agents; 0.15.0 messaging
coalescing is not a substitute for durable seat-level reassessment intent.

**Panel:** show task authority revision, seat/occupant generation, execution
observation, blocked writes, pending purposes and knowledge review revisions.
Initial actions: Open occupant, Inspect evidence, Request reassessment. The
[accepted panel sketch](research/demonstration-sketch.md) exposes uncertainty
without conflating task assignment, runtime liveness and knowledge freshness.

## 6. Memory and migration remain first-class

**Proposed trust/disclosure gates:** retrieved text and commands remain untrusted
data. Promotion, verification and migration never confer instruction authority
or permission to execute. Publication/export checks authorized audience and
sensitivity, including retained Git history, superseded material and archives.
Unknown sensitivity blocks sharing pending authorized review. These are contract
requirements, not scanner implementation or claims of performed checks.

The [memory contract](issues/06-team-memory.md) preserves team/seat/task knowledge
and selectively promotes occupant scratch. A small index guides orientation.
Records carry sources, applicability and verification dates; corrections link
prior evidence. Publication, notification and review at revision are distinct.
Consequential inherited claims are reverified before dependent work. Ordinary
checkpoints support abrupt loss; full transcripts are optional evidence.

The [migration contract](issues/04-migration-contract.md) uses a versioned
Markdown/Git package. Pause, reconcile effects, capture a source revision,
validate an inactive destination, then explicitly cut over. Required semantic
loss blocks activation. Runtime rebinding is separate. Preserve pending purposes
and historical review markers, not missed ticks or inherited approval. After
destination writes, rollback is another reconciled cutover.

Borrow OpenRig's stable-seat and authored-knowledge patterns, not its full daemon,
SQLite task authority or arbitrary bundle execution. RigSpec import is unnecessary
for the first demo; do not advertise compatibility without a separately scoped
mapping and qualification. Its declarations can include behavior that is inert.

## 7. Accepted demonstration and evidence

### Fit with the full MSB workspace plan

The [current MSB full-workspace plan](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/d2ec85d7d8e86b3e5906740139d1277b114ff4bc/docs/MSB-WORKSPACE-PLAN.md)
places the full coordinator/workspace inside the outer VM. Under that deployment,
the portable coordinator and optional Paseo binding also live inside the VM;
the host provisions the VM and approved credential/egress bindings. Controller
policy, admission state and accepted evidence stay protected from candidate
files/tools. Candidate builds/tests run in narrower disposable inner execution,
not the controller environment. Qualify OpenCode first, then Pi through its actual
adapter/permission paths; one harness's results do not establish parity.

The small cooperative demonstration below is separately scoped. It does not
implement or qualify full MSB deployment, controller protection or Pi support.
Those retain the plan's own evidence and activation gates; this research PR
authorizes neither deployment nor implementation.

Three seats repair one documentation link in a synthetic repository. A decision,
failed approach and stale check result make continuity observable. Run identical
skills/model settings through the minimal and Paseo profiles. Lose Builder A
before handoff; B orients, verifies the claim, corrects it and shares knowledge;
reviewer reads the correction at its revision. Exercise replay, busy-seat duplicate
wakes, stale-generation refusal, unknown execution and restart recovery.

One local-to-local interchange exercise shows paused export, inactive import,
an interrupted pre-activation stage, preservation inspection and explicit
cutover/runtime rebinding. It does not prove GitHub/GitLab translation.

Baseline: Paseo 0.15.0, exact harness/package/model versions recorded, one OS
qualified. Per profile: one task, one
builder replacement, one pass through failure scenarios, maximum 30 minutes.
Set a numeric hard model-spend cap before launch. Stop at either bound.

Evidence must include source/config hashes, state revisions, operation/replay
results, actual check output, knowledge sources/corrections/review markers,
execution observations and cutover records. Required missing evidence yields
blocked/incomplete. This proposal and its written walkthrough are not live passes.

## 8. Review focus and next gate

The [synthesis ticket](issues/08-proposal-synthesis.md) tracks the remaining
review/launch gates. Will's most useful review is a concrete annotation of the
change map: which seams already exist in his in-flight work, what names they use,
and which coupled consumers it handles. Prefer adopting those seams over creating
parallel ones. In particular, map authoritative issue metadata, local caching,
coordination receipts and runtime observations field by field.

Then review the proposed conditional-operation interface and compatibility path.
The accepted cooperative pilot is valuable but does not permit ignoring schema-3
reader refusals, replacing process identity with a server PID, or declaring the
whole Maintainers suite portable. Implementation ownership and sequencing should
follow that interface review; this document does not start implementation lanes.

## Evidence index

- [Decision map](map.md): human-approved direction and ticket resolutions.
- [Maintainers source research](research/maintainers-binding-surfaces.md): pinned baseline and explicit superseding clarification.
- [Runtime and memory research](research/minimal-and-paseo-bindings.md): OpenRig, the Paseo 0.15.0 target and CLI evidence with qualification limits.
- [Upstream watch](research/upstream-binding-watch.md): current PR/issue/commit observations.
- [Demonstration sketch](research/demonstration-sketch.md): accepted walkthrough and panel.
- [Glossary](GLOSSARY.md): settled vocabulary.
