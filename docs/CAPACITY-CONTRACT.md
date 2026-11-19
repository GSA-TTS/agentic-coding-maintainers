---
title: "Capacity contract v1: bounded admission and retained ownership"
status: proposed
date: "2026-11-19"
source_sha: 638763a521d2c86f8d453b603d3bdcb983eba116
---

# Capacity contract v1

## 1. Decision boundary

Design recommendation for [#191](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/191)
under epic #190; **not implemented, qualified, or activated**. This documentation
can proceed independently of the portable planning PR. Runtime integration must
wait for #182 core/manual integration, a fresh source pin and ownership review.
It changes no active configuration, authority, resource setting or task format.
“Must” below specifies the proposed contract, not an assertion about current code.

Keep **6 workers / 2 implementation lanes**, two QA/security places **within**
the worker total, and **one heavy validation operation at a time**. The reserve
is a required admission refinement, not a claim that the pinned core enforces it.
**8/3 is only the first qualification candidate**, neither measured-safe nor an
automatic increase. Narrower grants and current policy always win over config,
resource availability, model recommendations and queued demand. Existing
[scoped authority](SCOPED-AUTONOMY.md), isolation, one-writer worktrees, semantic
conflict checks and exact-head human merge decisions remain controlling.

Reuse the existing serialized coordinator and task lifecycle. Capacity supplies
admission guards, reservations and explanations, not a second scheduler, daemon,
task store, cancellation service or completion authority. No preemption: pressure,
expiry and limit reductions restrict new work, not running owners or UNKNOWN.

## 2. Fresh static source findings

Inspection pin: `638763a521d2c86f8d453b603d3bdcb983eba116`. Paths/line ranges in
this section were read in the assigned checkout; no code was executed. These are
bounded findings, not a complete re-audit of the [consumer inventory](TASK-STORE-INVENTORY.md).
`core` means [orchestrator-state.py at this pin][core].

| Observed source | Consequence for implementation review |
| --- | --- |
| core:23–30, 359–362 | Exit 3/4 and constants 6/2 exist; lease readers share the allocation maxima. Merely making those constants configurable would make retained higher leases unreadable. |
| core:790–804, 996–1050 | `reserve_first` scans only its count range; claim uses `CoordinatorLock` and the full admission scan. Definite claim-write failure cleans up; ambiguous write retains the slot. Preserve that distinction. |
| core:1335–1396 | Implementing transition allocates a lane before durable intent; selected reservations are checked, but this path does not call the complete admission scan. Add count/resource guards here, not only at claim. |
| core:1608–1643 | Admission walks all tasks and reverse scope/slot/lane reservations, refusing unfinished intents and mismatches. Never replace it with an in-range slot count. |
| core:1646–1695, 1736–1844 | Legacy `finish_intent` can allocate a missing lane; cooperative recovery scans both directions and writes pending/settled receipts around release. New allocation requires current guards; retaining/releasing existing capacity must remain possible. |
| core:297–329, 1851–1857 | Schema 2 permits extra keys where schema 3 has a closed extension set; reconcile preflights bound state. An ignored sidecar or additive schema-2 field is not an older-writer fence. |
| `scripts/check-native-ownership.py`:172–176 | Independent reader has inclusive lease maxima 5/1; updating core alone cannot widen compatibility. |
| `scripts/review-workspace-preflight.py`:297–299, 383–384 | Another reader has exclusive 6/2 bounds and rejects unknown root inventory. A new capacity directory affects it even without changed task fields. |
| `scripts/assignment-dispatch.py`:167–210 | Descriptor-selected tasks use core validation, then exact lease metadata, schema-3 and generation/revision checks. Capacity changes must preserve these bindings. |

[core]: https://github.com/GSA-TTS/agentic-coding-maintainers/blob/638763a521d2c86f8d453b603d3bdcb983eba116/.agents/skills/workspace-orchestrator/bin/orchestrator-state.py

Re-pin these paths plus runtime observation, claim producers/observers, review
reservations, journals, installed manifests and recovery consumers after #182.
Do not reuse task schema numbers 2/3 or proposed native identity numbers 4/5 for
capacity. Process identity migration remains #182's responsibility; capacity
freshness must not rewrite retained process identities or use timestamp tolerance.

## 3. Three ceilings and review arithmetic

* **Readable ceiling R:** a versioned representational bound for retained lease
  IDs, independent of current allocation. It must cover every previously admitted
  index; lowering a hard/effective ceiling cannot lower R or renumber leases.
  Unsupported, malformed or out-of-format records block admission, never vanish.
* **Hard ceiling H:** reviewed configured worker/lane maxima, bounded by qualified
  runtime support and narrower authority. Raising config alone grants nothing.
* **Effective ceiling E:** current admission target, no greater than H and active
  authority; fresh observations and reservations may reduce it. Occupancy may
  legitimately exceed E or a newly lowered H until existing work drains.

For workers, let N be all charged workers and Q the charged, authorized QA/security
workers, including pending/uncertain launches. With review reserve S=2, a new
non-review worker requires both `N + 1 <= E` and `N - Q + 1 <= max(0, E - S)`.
A review worker requires `N + 1 <= E`; no class minimum or rounding can override
the total. Reserve identity follows authorized purpose, not a caller's label;
general work cannot borrow it. If E<2 only review admission can fit. Lane limits
are an additional intersection, not worker credits. Bundles use their whole delta.

Count monitors and every nested agent, including queued panel seats reserved for
dispatch. Primary/collector CPU, memory, descriptors and provider use are always
budgeted; if they perform worker roles those roles also consume worker capacity.
Do not silently exempt primary model work when evaluating conservative panel fit.
An owned heavy check consumes an operation reservation, **not** a fictitious extra
worker; actual additional agents still need worker reservations. Existing review
evidence reservations do not by themselves prove count/resource admission.

## 4. Typed requests, observations and entitlement

Use separate namespaces and tagged records; matching numbers do not imply identity.

| Type | Required meaning |
| --- | --- |
| `work_id` | Stable outcome identity; source authority distinct from optional coordinator task mapping. |
| `run_id` | One execution context for work/workflow revisions; a new run never resets an unsettled operation. |
| `operation_id` | Stable logical launch/effect identity and canonical request digest across retries. Conflicting content under one ID refuses. |
| `attempt_id` | One bounded dispatch/retry/fallback under an operation, with parent linkage and settlement evidence. |
| `domain_id` | Opaque resource authority identity: physical host, VM, cgroup/container, backing volume, or provider budget; not a hostname used as proof. |
| `class` | `remote_static`, `implementation`, `heavy_validation`, `vm_start_provision`; purpose/QA role is a separate authorization attribute. |

A **request** declares IDs, domain/class, policy/config revisions, resource vector,
qualified maximum fanout, duration/retry limits and input provenance. It is neither
observed use nor entitlement. An **observation** reports measured facts/limits and
their uncertainty, never admission. An **entitlement** is a trusted, scoped,
expiring/revocable budget derived from active authority, not from the request or
from a provider advertising a model's context size. A **reservation** is a durable
coordinator charge tied to an exact request digest and fencing generation.

Use exact nonnegative integers: CPU millicores (1000 = one CPU), memory/swap/storage
bytes, PID/thread/FD/inode counts, provider concurrent/pending request counts,
input/output tokens per explicit window and currency micros per explicit window.
Rate observations use integer numerator, duration and unit; reject booleans,
floats, coercion, overflow, negative values, unknown units and unbounded vectors.
Zero is not “unsupported”; unsupported/inapplicable has an explicit reason and
reviewed applicability rule. CPU weights are not quota entitlement.

Portable #199 may validate inert request shape and internal references only.
It must reject entitlement/admitted/release injection, perform no topology lookup
or effective-limit calculation, and claim neither durable replay nor freshness.
Agreement on this seam is still proposed; adaptive #196 is **not a prerequisite**
for the first portable consumer. Consumer extraction/activation has separate gates.

## 5. One physical backing hierarchy

One host ledger covers all participating orchestration roots, host processes and
VM envelopes. Multiple roots must share that authority and serialization or refuse
unsupported topology; separate coordinator directories cannot multiply host budget.
Validate parent identities, unique backing resources and acyclic ancestry before
admission. Missing/contradictory backing is UNVERIFIED; a proven forbidden topology
is policy refusal. Existing owners and their charges remain intact in either case.

Host physical entitlement backs VM allocations; guest/cgroup limits constrain use
**within** that envelope, never add host capacity. Effective CPU intersects online
CPUs, cpusets and all ancestor quotas; memory/PID limits likewise honor ancestors.
Do not add each child's advertised maximum to host capacity or charge the same
guest allocation again on top of its host VM envelope. VM virtualization overhead
is an explicit host charge. Observed guest use is not a second host charge.

At each accounting domain, conservatively charge `max(reserved envelope, attributed
observed use)` for each disjoint managed allocation, plus unattributed external
demand and controller/safety headroom. Reconcile the same allocation's observation
with its reservation, do not add both. Uncertain attribution cannot subtract use
optimistically. Fit must hold at every ancestor and each independent resource;
nominal CPU fit cannot waive memory pressure, swap-rate or provider constraints.

Docker/external processes consume the host residual even when not coordinator
owned. All APFS volumes sharing a container use one backing-space budget; guest
free disk is not additional physical free disk. Account sparse-image growth,
snapshots, Git/scanner caches and temporary validation demand. Stopped VMs release
compute only on confirmed stop, retaining images/snapshots/storage charges; starts
reserve their full incremental envelopes before effects. Collect allocatable
capacity and inode limits where meaningful, not sums of filesystem free reports.

## 6. Observation and refusal interface

An observation envelope names producer/source version, domain/backing IDs, boot
identity, collection start/end monotonic time, duration, sequence, policy/config
digest, applicability, units and per-metric status. Track CPU/quota/throttling/PSI,
memory pressure and interval swap/pageout rates, storage/I/O/transient growth,
PID/thread/FD headroom and separately declared provider budgets. Free RAM or one
snapshot is not health. macOS and Linux adapters must state unsupported metrics.

Only compare monotonic times within the same boot/clock domain; bind cross-domain
samples to bounded collector receipt/age evidence, not subtracted guest/host ticks.
Wall time is display/audit data, not freshness authority. Sleep, reboot, collector
restart, counter reset or clock discontinuity invalidates healthy-history credit.
Partial, stale, empty, contradictory or unbound required samples cannot expand
admission; observation failure never proves a worker stopped or a lease expired.

Return **3 / UNVERIFIED** for unmeasurable prerequisites, unsupported config/state,
missing ancestry, stale/reset samples or ambiguous launch/settlement. Return
**4 / refusal** for established exhaustion, pressure, conflict or policy denial.
An independent known denial can be reported alongside uncertainty, never as proof
that the remaining guards passed. In resource-aware mode any new charge, including
a replacement launch at unchanged total, needs fresh required evidence; read-only
explanation and compatible settlement remain available. Legacy count-only behavior
is a separately identified mode, not an automatic fallback after observation loss.

Explanations identify limiting domain/budget, request delta, charged totals,
configuration revision, freshness status and next responsible action. Keep raw
host/VM telemetry private, bounded and redacted from public evidence. Collectors
have bounded runtime/output, no installs, launch privileges or setting changes.

## 7. Atomic reservation and launch contract

Under the existing coordinator lock: validate authority, exact task/run generation,
all forward/reverse reservations and topology; compute the complete worker/lane/
operation/provider bundle; evaluate ceilings, reserve and fresh resource guards;
durably record **reserved** intent and charges before allowing any launch effect.
**Admitted** means the same generation has satisfied launch-boundary checks and
may dispatch; it is not proof of a running process. Recheck changed observations,
policy, ownership and budget at transitions, expensive launches and retries.

Commit request digest, operation ID, resource charges and task mutation/revision
as one recoverable transaction. Cross-file persistence needs a reviewed durable
intent/receipt protocol, not a claim of atomicity from several renames. Journal
rows may reference that authority but cannot own a second lifecycle. Same-ID/digest
replay returns history, not renewed launch permission; conflicting digest refuses.

Crashes before reservation have no launch authority; crashes after reserve keep
charges. Launch-before-ack, timeout, missing descendants or ambiguous writes are
UNKNOWN and charged. Definitely unissued reservations may be released only with
guarded proof; issued work needs observed settlement/descendant-stop evidence.
Cancellation request, coordinator death, TTL and lower limits do not establish
settlement. Recovery that allocates anything new reruns admission; recognizing
or releasing an existing higher-index lease does not require it to fit today's H.

## 8. Runtime qualification and feedback

#195 must enforce the qualified maximum nested agents, concurrent tool calls,
hidden threads, retries/fallback attempts and pending submissions **before**
dispatch. Provider concurrency, rolling token/rate limits, spend and backoff are
separate budgets shared across invocations; SDK serialization is not that ledger.
Reserve worst-case bounded exposure, reconcile actual use, retain unknown issued
attempts. Opaque/unbounded fanout stays disabled; price reporting is not a hard cap.

Retain the observed Nexus negative case: three requested seats expanded to seven.
The supplied installed-source audit of 15.4.0 supersedes 14.0.1-specific findings:
workspace targeting, keyed serialization and async cancellation improved, but
quick mode can still escalate, fallback/SDK attempts remain distinct, and timeout
does not prove underlying-call cancellation or spend settlement. No qualified
per-call role ceiling or global provider budget was established by that static
audit. Neither a simulated vote nor a larger configured ceiling closes this gap.

#196 later supplies class-specific hysteresis beneath H: sustained low-pressure
windows and eligible queued demand before bounded growth, high-water refusal,
cooldown and no expansion credit after reset. Slow remote-model latency is not
local CPU pressure. **Test hypotheses only:** 30-second maximum sample age,
120-second healthy window, +1 worker per 60-second cooldown, CPU low/high water
60%/80% of effective quota. Calibrate or reject them in trace replay; they are not
production defaults or measurements. Memory/swap/storage/provider thresholds need
their own qualified profiles. No deliberate contention probes or worker retirement.

## 9. Configuration, migration and rollback proposal

Propose a dedicated closed `capacity-config/v1` document, not monitor config:
`format`, `version`, `config_revision`, `policy_digest`, `mode`, `hard_limits`,
`review_reserve`, `class_budgets`, `domains`, `provider_budgets`, `observation_policy`
and `qualification_refs`. Bound size/depth/collections, reject duplicate keys and
unknown versions/fields; references use exact digests, not mutable labels. Trusted
installation supplies authority separately. Storage path/schema and readable-state
fence encoding require #193 review; this file creates no active format or loader.

| Situation | Required migration / rollback behavior |
| --- | --- |
| Legacy 6/2, no activated format | Preserve pinned legacy fixtures and behavior; no silent migration on read. |
| New reader, old state | Lossless explicit mapping; retain identities, counters, digests and UNKNOWN. No fabricated generations or cleared reservations. |
| Activate new capacity semantics | Quiesce admission and let existing owners drain naturally; back up authoritative state; establish compatible readers/recovery and an unavoidable older-writer fence before first new-format effect. Unresolved UNKNOWN blocks unsafe migration. |
| Old writer against activated state | Refuse before any effect, including selected-task mutation, create, recovery and release; prove using pinned old clients. An ignored sidecar/additive field is insufficient. |
| Lower H/E with higher leases | Retain full readable range and every charge; deny overspending new work, permit compatible settlement, never compact indices. |
| Roll back before activation | Restore prior installed/config pin only after confirming no new semantics/effects were persisted. |
| Roll back after activation or uncertain launch | Stop expansion, keep compatible readers/recovery, reconcile and drain naturally. Never strip fields or restore an old snapshot over newer effects; unsupported downgrade remains blocked. |

## 10. Mechanisms reused as ideas, not code

Seven-project survey evidence is recorded in [#191's comparison][survey]. Releases
below are survey-observed maintenance signals (all then non-archived), not support
guarantees or fresh live checks. Each link pins inspected source; no dependencies,
assets or source were imported. Check file-specific licenses before any future copy.

| Project / inspected source / license / observed release | Borrow or reject |
| --- | --- |
| [Kueue admission](https://github.com/kubernetes-sigs/kueue/blob/1fa7c3eabf6ebfa9c32f0514ec617f204bf85818/site/content/en/docs/concepts/admission.md), Apache-2.0; v0.20.6, 2026-11-12 | Borrow reserved/admitted separation and invalid-hierarchy refusal; no Kubernetes runtime, preemption or uncertain quota release. |
| [Dask AdaptiveCore](https://github.com/dask/distributed/blob/dc182bda54af488d029f2c40db0893d5f48e69d5/distributed/deploy/adaptive_core.py), BSD-3-Clause; 2026.8.0, 2026-08-24 | Borrow requested/observed separation and dampening; no nanny termination or per-worker duplication of host entitlement. |
| [systemd resource control](https://github.com/systemd/systemd/blob/38318cafb54c61cb663fab17914ec6114d84254f/man/systemd.resource-control.xml), primarily LGPL-2.1-or-later, file exceptions; v262.2, 2026-11-05 | Borrow effective ancestor limits; enforcement alone is not reservation accounting, and live limit reduction must not kill owners. |
| [Ray placement groups](https://github.com/ray-project/ray/blob/be8a35b5bede2e2ec336e4639d35550312a9ebb6/doc/source/core/scheduling/placement-group.md), Apache-2.0; 2.60.0, 2026-11-04 | Borrow all-or-nothing bundles; logical resources do not enforce CPU or automatically bind descendants. |
| [Netflix Gradient2Limit](https://github.com/Netflix/concurrency-limits/blob/78a74b9878d38c4c048b0304ce12a162ab7b7222/concurrency-limits-core/src/main/java/com/netflix/concurrency/limits/limit/Gradient2Limit.java), Apache-2.0; v0.5.4, 2025-12-08 | Borrow clamping/no demand-free growth; reject partition borrowing/rounding that admits above the global cap. |
| [Envoy gradient controller](https://github.com/envoyproxy/envoy/blob/0f62b3853a711e67e0a0a864999c2a870238f885/source/extensions/filters/http/adaptive_concurrency/controller/gradient_controller.cc), Apache-2.0; v1.40.2, 2026-10-27 | Borrow explicit sample windows; reject empty-window retained expansion and deliberate minimum-concurrency probes. |
| [Nomad resource fitting](https://github.com/hashicorp/nomad/blob/359056d76692c74250b15aa4a10abc6fbb6fc268/scheduler/feasible/rank.go), BUSL-1.1 with additional terms; v2.1.1, 2026-10-29 | Distinguish reservation/burst envelopes and shared disk; no oversubscription/eviction or runtime adoption. |

[survey]: https://github.com/GSA-TTS/agentic-coding-maintainers/issues/191#issuecomment-6999309486

## 11. Owner dependencies, negative cases and first slices

Settled **as recommendations**: one coordinator, three distinct ceilings, two
within-total review places, serial heavy validation, typed request-only portable
seam, non-preemptive bundles and ideas-only reuse. Still requiring owner decisions:
#193's storage/fence and readable bounds; #192's supported observation tuple;
#194's shared-root authority and attribution; #195's enforceable fanout/exposure;
#196's calibrated thresholds; #197's explicit measured rollout. #66 retains action
authority and #74 lifecycle/recovery; #72 consumes admission, not a competing loop.

| Owner / dependency | Required negative fixtures or qualification evidence |
| --- | --- |
| #193 after #191 and reconciled #182 | Rounded class minima exceed total; QA request at global cap; concurrent last-slot/lane claims; failed writes; orphan/missing locks; allocation during recovery; pinned old-writer refusal before effects. |
| #192 after contract agreement | Empty/partial/stale samples, boot/sleep/counter reset, cross-clock comparison, unsupported PSI/inodes, missing ancestors and provider entitlement injection. Offline parsers plus bounded actual platform observations. |
| #194 after #192/#193 | Double spending across roots, duplicate APFS backing, cycles, guest capacity added to host, reserved/observed double charge, pending VM start, launch/ack crash and UNKNOWN retention. |
| #195 after #194 | Three-to-seven panel escalation, escaped child/thread/tool fanout, retries/fallbacks, pending versus running limits, provider rate/spend uncertainty, unconfirmed cancellation. |
| #196 after #194, integrating #195 | Bursts, slow remote work, external demand, delay, oscillation, no-demand growth and reset history; deterministic replay against fixed 6/2 and serial-heavy baseline. |
| #197 after #192–#196 | Restart/lower limits with higher leases, partial migration/rollback, late results and drain; isolated load plus bounded live canary comparing useful throughput, tail latency, refusal stability and cleanup. Passing fixtures do not activate 8/3. |

First implementable slice: **#193 count-only compatibility/reserve** after #182
integration/re-pin, without resource feedback or expanded activation. Alternatively
**#192 bounded read-only observation parsers** may start on an independently owned
scope once this interface is reviewed; they cannot launch or admit work. Neither
requires adaptive #196 or the portable planning implementation stack. Subsequent
changes need normal isolated checks, independent fixed-head QA/security, applicable
policy/profile/provenance synchronization and an exact-head human merge decision.

Validation: static inspection only; no commands, tests, model panels, commits or
remote writes. AI-assisted design; qualification and activation remain open.
