# Portable work: aligned implementation roadmap

Status: **planning candidate; no runtime activation**. Evidence refreshed
2026-11-19 UTC (2026-11-18 America/New_York). This supplements the accepted
[portable-team proposal](../.scratch/portable-team-as-code/proposal.md) and
[decision map](../.scratch/portable-team-as-code/map.md); those remain research
provenance. Their local tickets are not GitHub implementation drafts.

## Evidence and responsibility map

Maintainers source **M** is
[`638763a521d2c86f8d453b603d3bdcb983eba116`](https://github.com/GSA-TTS/agentic-coding-maintainers/tree/638763a521d2c86f8d453b603d3bdcb983eba116).
The owning issues and relevant comments were re-read, including the completed
[seven-project survey](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/191#issuecomment-6999309486)
and refinements on #193–196. “Implemented” below means inspected source, not a
new execution receipt. Qualification and activation require separate evidence.

| Requirement / classification | Authoritative owner | Current source/issue evidence | Implemented behavior | Qualification evidence | Remaining gap | Proposed action | Dependencies |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Portable contracts — reuse + implement missing | [Portability epic #198](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/198) | [PR #138](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/138), merged `e06394d0f1588f392715164c40ef2ed03ffcfb30`; proposal/map at M | Cooperative lifecycle primitives, no generic work runner | Research review only | Repository-free work/run/artifact contract and local binding | Adopt accepted authority, memory and cutover semantics; implement smallest shared modules | Contract slice below; W0 before extraction |
| Task-store seam — amend + verify | [#167](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/167), [W0–W7](TASK-STORE-WORK-ITEMS.md) | Inventory, delta and tracker merged in [#169](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/169), [#179](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/179), [#180](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/180) | Direct core/independent readers remain; no `task-store.py` seam | Historical inventory fixtures; not current consumer qualification | W0 decisions and full implementation-base re-pin | Preserve Markdown owner; do not recreate W0–W7 as issues | #182 integration for affected consumers; D1–D10 |
| Native process observation — reuse + blocked | [#182](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/182), [ADR 0002](decisions/0002-native-process-identity.md) | [#188](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/188) merged as M; `runtime-observation.py`, `orchestrator-state.py` at M | Additive record-directed observer; creation/claims still legacy; core schemas 2/3 | Primitive/namespace evidence is bounded; backend remains unqualified | Core/manual candidates need combined isolated validation and exact-head review; other profiles/races/cleanup remain | Preserve owners; re-pin consumers after integration | Native task selection, migration and deployment have separate gates |
| Shared capacity — reuse + amend | [#190](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/190), #191–197 | Core constants at M are 6 workers / 2 implementation lanes; survey complete | Fixed reservation admission; adaptive controller not implemented | No calibrated 8/3 operating envelope | Generic operation identity and guest-consumed host evidence | Add profile-neutral contract below to existing children | #191 before #192/#193; #182 overlap review |
| Task facts and external effects — reuse | [#29](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/29), [#66](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/66), [#67](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/67), [#68](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/68) | Intake, assignment journal, scoped-autonomy and executor at M | Bounded observations, local receipts, synthetic issue/assignment vertical | Synthetic endpoint scope is not general metadata qualification | General task binding and typed effects remain partial | Keep native issue facts native; selected local binding owns local work facts | Fresh authority/preconditions for each effect |
| Coding and dependency semantics — reuse | [#61](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/61), [#62](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/62), [#72](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/72), [#73](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/73) | Foreground delivery/review/repair modules at M | Coding-specific evidence and replay primitives | Does not establish two generic workflows or polyrepo delivery | Shared runner and consumed deployment tuple | Reference these owners; add only repository-free runner/demo scope | Semantic interface; exact input/evidence revisions |
| Lifecycle, memory and interfaces — amend | [#74](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/74), accepted memory/migration/panel design | Dispatcher pause/replay, research contracts at M | Partial lifecycle; no general UI adapter | No current Paseo API/permission parity receipt | Headless projection, optional UI, continuity/cutover | Extend #74 projections; optional adapter gets concrete API spike | Shared commands; #125 topology; separate UI qualification |
| Full ACQ workspace — amend + verify | [#125](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/125), [MSB plan](MSB-WORKSPACE-PLAN.md) | Release machinery at M; v0.7.0 published; #189 proposes v0.8.0 | Release config and qualification drivers | Full workspace remains planned/unqualified | Pinned payload, normal kit install, persistence, inner execution, harness runs | One canonical payload; thin supported-format packaging | Actual Quickstart/Patterns source and deployment tuple |
| GitLab parity — reuse + blocked | [#119](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/119) | Existing small-adapter design | No qualified GitLab binding | None claimed | Concrete consumer/version/edition and GitHub qualification | Keep current sequencing; no generic forge framework | #116–118 qualification; explicit pilot authority |
| Rollout — reuse + blocked | [#75](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/75), #197 | [Scoped authority](SCOPED-AUTONOMY.md) at M | Synthetic activation path only | Neither source merge nor model vote activates authority | Measured profile/runtime/endpoint qualification | Separate installed, implemented, qualified, activated, verified-outcome states | Exact-head human merge and independent activation decisions |

At discovery #190 had **zero formal GitHub sub-issues**; #191–197 are its
body-linked checklist and all were open. Do not report that checklist as a
formal dependency graph. Configured Project 120 covers Quickstart, Patterns
and Playbook, not Maintainers; Maintainers status above comes directly from its
issues/PRs. Only Maintainers PR #189 was open, at
`e9769cf2aec660d4702068be0e43637e02d90fc5`, with no checks/reviews returned.
It is unrelated release work, not an integration prerequisite or merge decision.

## Bounded contract decision

### ACQ source and consumed-pin evidence

Quickstart main is
[`6c4526cc79694cf26cccddf07ebd46caf8487aa1`](https://github.com/GSA-TTS/agentic-coding-quickstart/tree/6c4526cc79694cf26cccddf07ebd46caf8487aa1);
Patterns main is
[`af0271a14cb52ce6109a11420fcf43ce3f7b03f2`](https://github.com/GSA-TTS/agentic-coding-patterns/tree/af0271a14cb52ce6109a11420fcf43ce3f7b03f2).
Quickstart actually consumes Patterns
[`941a286f912b99475429c3c00db49a99af5b241e`](https://github.com/GSA-TTS/agentic-coding-patterns/tree/941a286f912b99475429c3c00db49a99af5b241e),
not current Patterns main. Its Paseo pin is 0.15.0 versus 0.15.4 on Patterns main.

| Requirement / classification | Authoritative owner | Current source/issue evidence | Implemented behavior | Qualification evidence | Remaining gap | Proposed action | Dependencies |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Payload packaging — reuse | #125; Patterns kit schema/catalog | Quickstart `acq.backends/kit-translate.sh` and Patterns `schemas/kit-hybrid-v1.schema.json` at pins above | `hybrid/v1` mixins; SBX synthesis emits v2; no manifest dependency field | Source inspection in ALIGN | Exact payload materialization/modes/relative paths and restart | Thin hybrid packaging over canonical payload; ordered composition outside unsupported fields | Existing base/harness/provider/OCI kits |
| Python migration — reuse + verify | [Quickstart #709](https://github.com/GSA-TTS/agentic-coding-quickstart/issues/709), assigned existing maintainers | [Draft PR #697](https://github.com/GSA-TTS/agentic-coding-quickstart/pull/697), `eee68c964965054919824bf0e0cc866ea71bf819`, open/conflicting at discovery | Candidate `py-acq/src/acq_py/kit_sbx.py` preserves hybrid→v2; unmerged | Candidate reports are not final integrated qualification | Final compatible consumer tuple | Link #125 payload cases to #709; no rewrite duplication | Existing migration integration/release gates |
| Kit v3 — reuse + blocked | [Quickstart #628](https://github.com/GSA-TTS/agentic-coding-quickstart/issues/628), launch owner [#577](https://github.com/GSA-TTS/agentic-coding-quickstart/issues/577) | [#586 research](https://github.com/GSA-TTS/agentic-coding-quickstart/issues/586#issuecomment-6378559372); spec/conformance `cc033f80d58bb9516db1c26b71a3ce8184100fd0` | No qualified ACQ v3 consumer established | Prior descriptor/library tests only | Runtime required/optional capability and lifecycle evidence | Reuse research; add this payload as consumer; waivers/skips remain gaps | Compatible spec/tool/backend tuple; independent of first hybrid payload |
| Base and inner OCI — reuse + blocked | #125; [Patterns #418](https://github.com/GSA-TTS/agentic-coding-patterns/issues/418), [#588](https://github.com/GSA-TTS/agentic-coding-patterns/issues/588); [MSB #2029](https://github.com/superradcompany/microsandbox/issues/2029) | Patterns devenv and `oci-engine` READMEs at current pin | Documented base 2.1.0/devenv 2.4.0 and opt-in metadata helper; startup/workload integration and actual image contents not independently verified here | Historical guest smoke, leaf-limit and metadata persistence evidence only | Runtime-owned delegated ancestry/freezer and effective inner workload controls | Preserve normal installer; qualify supported delegation/equivalent before execution | No sibling-cgroup workaround; actual tuple and cleanup |
| Optional UI — verify | #74/#125, existing Patterns Paseo/OpenChamber kits | [Paseo plugins](https://github.com/getpaseo/paseo/blob/4e78d15bdc514cc59bca31d2b70a3d2bf9f6b92f/public-docs/plugins/index.md); [OpenChamber target selection](https://github.com/openchamber/openchamber/blob/f698cd04dea8c286b029afafd8ae16c4afe31cdc/packages/docs/content/docs/opencode-server.mdx) | Trusted plugins/direct or ACP launches; server fallback exists in some configurations | No current Maintainers adapter qualification | Version-matched projection and controlled command routing | Projection-only first; controller-owned execution survives removal of presentation client | Current upstream API does not qualify packaged Paseo; no host fallback |

Quickstart #628 is the architecture owner and formally lists #586 as its direct
child; #586 owns performance research. Neither relationship transfers ownership.
No new Quickstart or Patterns epic is needed. Removing a Paseo provider plugin
may terminate its sessions: the continuity requirement is to preserve controller
state/evidence and reconcile execution, not promise that plugin-owned processes
continue. A removable presentation adapter must not own those processes.

### Shared contract recommendation

**Recommended:** one shared module/CLI contract in Maintainers, with a coding
profile and a repository-free evidence profile. Retain the existing coordinator
as the authority for claims, generations, operations and capacity. A generic
key/value adapter, second lifecycle database, new service, or external distributed
scheduler would duplicate existing owners. Extraction into another distribution
waits for demonstrated consumers. Nexus is an engineering-review dependency for
this effort, not a mandatory delivered runtime dependency.

The portable work envelope contains outcome, authority/reference/revision,
inputs, constraints and acceptance. A versioned workflow defines steps and
input/output/capability checks. Runs and attempts bind definition revision,
exact inputs/configuration, generation, budget and result. Artifacts identify
type, provenance and content/native revision. Evidence binds applicability and
reviewed revision. Typed effects bind operation ID, target preconditions,
authority and observed outcome. Stable team seats are optional; a one-worker
evidence task does not manufacture a three-seat team.

Repository, branch, PR, Git commit and coding-tool fields belong to the coding
profile. The local profile may use Git for storage without requiring forge
credentials. Task facts belong to the selected binding: native GitHub facts
remain native, caches remain derived. Runtime observations describe their
limits and freshness; a server PID is never proof of a live conversation.

Use semantic inspect/query, typed apply, observation and bounded reassessment
operations. Mutations bind scope, operation ID, expected revision and applicable
occupant generation. Same ID/content returns the retained result; changed
content is refused. A historical result grants no current permission. Preserve
coordinator-before-journal ordering, intent/receipt reconciliation and existing
strict-reader differences until their equal-guard migration is tested. Neither
Git publication nor a local transaction promises exactly-once remote effects.

Deterministic validation controls authority, resource admission, replay and
evidence acceptance. Agent steps investigate, synthesize and repair. Human
decision points retain their current policy. Dependencies name accepted
artifact, merged revision, published artifact, consumed pin or tested tuple;
provider completion alone is not verified completion. Input changes invalidate
only evidence whose recorded applicability no longer holds.

## Capacity interface amendments (existing #190 owners)

Keep every existing acceptance criterion, dependency and survey/refinement
comment. These are additive requirements, not a replacement issue plan.

| Owner | Addition / acceptance |
| --- | --- |
| #190 | Both workflow profiles use one capacity admission path; lifecycle/UI/kit ownership stays elsewhere. Current 6/2 operation and serial heavy validation remain; 8/3 is only a qualification target. |
| #191 | Map work/run/operation/attempt to existing task/session/generation; resource-domain identity distinguishes roles, workers, provider calls and deterministic operations. Repository-free document work can request capacity. Labels/kits cannot enlarge authority. |
| #192 | Guest controller consumes bounded host observations with domain, boot/clock origin, freshness and unavailable-visibility semantics. No privileged host shortcut or extra guest entitlement; stale required data prevents expansion. |
| #193 | Coding implementation/review lanes are the initial policy profile. Equivalent CLI/UI/harness requests receive equal admission; hard cap, review reserve, narrower grants and old-reader refusal remain controlling. |
| #194 | Bind reservations to logical work/run/attempt/operation without repository identity. Preserve physical parent accounting; UI loss, replacement, import and cancellation requests do not clear uncertain charges. |
| #195 | Qualify actual nested-agent/tool/provider/retry/pending-job maxima before dispatch, including Nexus panels. Retain the three-requested/seven-created negative case and independently observed cleanup. |
| #196 | Project limiting domain/class/quota/freshness/provenance to clients. Changing UI/harness labels cannot reset pressure history or authority; equivalent traces produce equivalent decisions. |
| #197 | Test coding and repository-free profiles against the ACQ contract: restart, disconnect, replacement, uncertainty and actual fanout. Link workflow/kit outcomes to their separate owners. |

Reuse Kueue's reserved/admitted distinction, Ray's atomic operation bundles,
Dask's requested/observed separation and hysteresis, and systemd's effective
ancestor limits. The survey's pinned sources/licenses remain the evidence;
no code or runtime dependency is imported. No demand-free expansion, partition
borrowing above the hard cap, preemption or UNKNOWN release is adopted.

## Delivery order and missing-work boundaries

1. **[PORT-CONTRACT #199](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/199):** agree the versioned objects, authority map, coding-profile
   mapping and two minimal input/output examples. This is the first bounded
   implementation candidate: schemas/validators and inert examples only, no
   task-store writes or worker launch. Reject forge-required non-coding inputs,
   mutable-title identities, unversioned definitions and evidence with mismatched
   input/artifact revisions. Reuse #66/#191; reserve exact new paths at admission.
2. **W0 then W1–W7 as applicable:** refresh all affected consumers after #182
   integration. Preserve the existing tracker and its conditional order. Decide
   D1–D10 with current source before migrating callers; generic contracts can
   be designed independently. Do not mark W0 done merely because inventory PRs
   merged. Strict/equal-guard readers precede their consumers.
3. **[PORT-LOCAL-BINDING #200](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/200):** a genuinely additional scope beyond #167/W0–W7:
   selected Markdown/Git work facts with conditional committed-tree publication,
   canonical operations, inactive import validation and one authority at cutover.
   Preserve runtime rebinding as a separate act and unknown predecessor effects.
   No production migration or second authority over existing tasks.
4. **[PORT-WORKFLOWS #201](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/201):** one runner with coding-link repair and evidence-brief
   definitions. Reuse #72 dependency/evidence rules and #61 review/repair;
   integrate accepted authored-memory/replacement/replay semantics. First finish
   with local artifacts; remote publication is a separate typed effect.
5. **#125 / PORT-DELIVERY:** immutable payload plus thin kit packaging, one outer
   MSB controller/workspace and narrower rootless candidate execution. Record
   source/payload/kit/image/backend/architecture/harness/policy identities. Use
   fixed capacity first; #196 is not on this critical path.
6. **#74 / PORT-INTERFACE:** headless read-only work/run/evidence/attention
   projection first; then a separately selected Paseo API/permission spike and
   adapter. UI commands use canonical revision-aware authority, not a second
   database. UI removal preserves headless work and evidence.
7. **#197 and #75:** measured capacity and authority rollout, each after its own
   qualification. Pi/second harness, Kit v3 and cross-forge parity remain separate
   tested tuples, not inherited from the first success.

Deduplication found no portable implementation epic in the complete Maintainers
all-state issue feed before this alignment;
#138 is merged research, #62 is the coding application, and #190 owns capacity.
The reviewed planning payloads were published as sibling epic #198 and only
contract/local-binding/workflow children #199–201. **Capacity remains #190;
#198 now names the distinct portability outcome.** Link #125 and #74 for
delivery/interface rather than duplicating them.
Continuity is acceptance across these slices, not a second migration project.

## Reference acceptance and compatibility

**Coding:** repair one documentation link in a synthetic repository, exact
source input, bounded patch, isolated check, independent fixed-revision review,
and exported patch/evidence. **Evidence:** version a small public/synthetic
document set, extract cited claims, synthesize a brief, independently check
support/omissions/contradictions, repair and export report plus verification.
Include a changed source or stale observation. No forge/provider ID is required
to express the evidence work. Select approved model access separately.

Both definitions must run headlessly through the same shared implementation.
Bound each demonstration to one work item, one replacement, one scenario pass,
30 minutes and a numeric model-spend/call budget fixed before launch; exhaustion
stops new work and preserves unresolved attempts. No UI is a prerequisite.

| Qualification boundary | Required positive and negative evidence |
| --- | --- |
| Revision and replay | Changed source invalidates dependent checks; duplicate/reordered operation does not double charge; changed content under the same ID refuses. |
| Occupant and effects | Successor generation rejects stale results; crash before/after intent/receipt and lost external response preserve UNKNOWN and block unsafe retry. Cancellation request, termination, descendant cleanup and committed effects remain separate. |
| Memory and cutover | Sources, applicability, corrections and revision-specific reviews survive replacement. Inactive destination validation, explicit loss check, single-authority cutover, interrupted import and rollback after destination writes retain evidence. Retrieved content never grants authority; publication/export evaluates audience and sensitivity including history. |
| Capacity and clients | Concurrent CLI/UI requests share reservations; visibility loss prevents expansion; relabeling cannot reset history; pending starts and tool/provider fanout remain charged within qualified bounds. |
| Deployment | Repeated startup preserves work/config; coherent backup restores dirty work and unresolved operations. Candidate code cannot access controller state/policy/accepted evidence, credentials or host sockets. Network-off/preloaded images first, actual effective limits and cleanup observed. |
| Optional adapters | UI disconnect/removal preserves headless outcomes; current Paseo APIs, unintended OpenChamber host fallback, second-harness permissions and v3 required/optional capabilities each need actual tests. |

The replacement demonstration loses the predecessor conversation before
handoff. The successor recovers a recorded decision, failed approach and sourced
finding from retained knowledge, verifies/corrects a consequential stale claim
before dependent work, and obtains independent review at the correction's
revision. Conversation transcripts are optional supporting evidence, not the
recovery source or an acceptance prerequisite.

Legacy schemas 2/3, digests, reservations, controller manifests and UNKNOWN
history are preserved. Proposed native schemas 4/5 are not portable work schemas
and are not activated here. Never repurpose those version numbers or migrate
pilots #154/#158. A manifest-hashed change invalidates applicable retained plans;
preserve bytes and admit a new review generation rather than rewriting history.
Old-reader refusal and rollback after new writes require substantive tests.

## Review and publication gates

Every material decision needs the actual artifact, immutable source/candidate
identity and full digest, inspected by independent reviewers. Nexus voting uses
named alternatives where relevant, supermajority with strict missing-voter
handling, actual participants/models and bounded execution. `quickMode` is not
capacity proof. Unverified fanout or source coverage blocks that tool path, not
independent planning work; no simulated vote counts.

Planning changes require documentation/link checks, independent source review
and repository `make check`/strict checks in justified isolation. Publish only
sanitized evidence. [Current authority](SCOPED-AUTONOMY.md) distinguishes normal
task-branch commits/pushes, per-action publication and human merge/activation.
Unsupported standing endpoints cannot be enabled by this roadmap. If required
publication or Nexus gates remain unavailable, retain complete UTF-8 amendment
and draft-PR files privately with target/base/digest and drift/retry instructions.
Do not place unposted issue drafts or Nexus records in tracked source.
