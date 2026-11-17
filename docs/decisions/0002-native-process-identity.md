---
title: "Native Linux process identity and bounded task migration"
description: "Proposed task formats, compatibility fences, and opt-in inactive-task conversion"
status: "proposed"
date: "2026-11-16"
decision_makers: ["Maintainers (review pending)"]
---

# Native Linux process identity and bounded task migration

**Proposed; not implemented or activated.** AI-assisted design for
[#182](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/182).
Approval to prepare this design PR authorizes neither runtime changes nor
deployment, migration, recovery, or remote operations. This follows
[ADR 0001](0001-extract-process-observation.md) without changing that decision.
Existing [scoped authority](../SCOPED-AUTONOMY.md) remains controlling.

## Context and decision

The legacy observer compares rendered `ps` start text, not a native lifetime
handle. Procps documents `lstart` as formatted calendar time; Linux exposes
start ticks separately [P, L]. This motivates avoiding calendar rendering for
new Linux identities, but does not establish the cause of any reported failure.

Choose explicit task schemas **4 (ordinary)** and **5 (cooperative)** plus a
versioned identity object. Retain schemas **2/3** with exact legacy semantics.
Support new native task lineages and explicit, one-task-at-a-time conversion
of eligible inactive legacy tasks. Conversion establishes no live identity:
only the next normal claim creates a native worker.

Reject tagged `process_start` strings: arbitrary historical text could collide
with any reserved prefix. A worker-only discriminator cannot fence old readers
of unclaimed tasks (`worker: null`). Reject automatic successor tasks: they
break or complicate incarnation, dependencies, scope and accounting bindings.
Four finite task variants preserve the existing lifecycle distinction without
introducing a generic backend registry or redesigning lifecycle authority.

## Proposed persisted and observation contracts

| Task schema | Lifecycle | Worker identity | Creation/conversion |
|---|---|---|---|
| 2 | Ordinary | Legacy `process_start` | Existing behavior retained |
| 3 | Cooperative | Legacy `process_start` | Existing guarded 2 → 3 claim |
| 4 | Ordinary | Native `process_identity` | Qualified new task or explicit 2 → 4 |
| 5 | Cooperative | Native `process_identity` | Guarded 4 → 5 claim or explicit 3 → 5 |

All other ownership fields remain applicable; `null` workers obey existing
lifecycle rules. Exact version validation precedes finite predicates for
cooperative (3/5) and native (4/5) tasks. `allow_bound=False` and automatic global
reconciliation still refuse cooperative tasks. Schema 5 does not gain ordinary
review/repair extensions. Reading or reclaiming schema 2/3 never promotes it.

For schemas 4/5, replace only the worker's `process_start` field with:

```json
{
  "process_identity": {
    "schema_version": 1,
    "backend": "linux-procfs",
    "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
    "pid_namespace_inode": "4026531836",
    "start_ticks": "12345678"
  }
}
```

The inner object has exactly those five fields. Version is integer 1, not a
boolean; backend is exactly `linux-procfs`; boot ID is a canonical lowercase
UUID. Inode and ticks are canonical decimal strings bounded to unsigned 64-bit;
inode is positive, ticks nonnegative. The separately stored PID retains its
existing validation. Reject dual identity fields, cross-format workers, extra
fields, coercion, missing discriminators and unknown versions/backends.

Keep `process_identity(pid, *, environment=None)` and its core patching seam
unchanged: `ps -p <pid> -o lstart=`, captured text, `timeout=3`, supplied or
inherited environment. `OSError`/`SubprocessError`, exit 1 with nonempty stripped
stderr, or exits outside 0/1 yield `unknown`. Otherwise stripped nonempty stdout
is `alive` with that exact text, empty stdout is `absent`. Arbitrary and multiline
historical text remains legacy; retain existing per-consumer validation limits,
PATH behavior and exact comparisons, including their known limitations.

Propose `native_process_identity(pid)` and record-directed
`observe_worker_process(worker, *, environment=None)` entry points. They return
the existing `alive`/`absent`/`unknown` vocabulary; native `alive` carries the
validated object, other native results carry `None`. Validated task/worker
format selects the backend, not the ambient OS. Native failures never invoke
`ps`. Darwin remains legacy; native claims there or on unqualified hosts refuse.
Failed native qualification must precede worker/slot/lane claim commitment.

## Linux qualification and evidence limits

The initial native backend requires trusted kernel-backed fixed `/proc`, with
observer and target in the **same PID namespace** and procfs exposing that
namespace's PID-number view. No caller-selected root, environment-selected
identity source or cache. Qualify a specific kernel/interpreter/architecture
and mount context. A reviewed filesystem-type check and substitution checks
are required; path existence or root ownership is insufficient. The Linux
`fstatfs` ABI and rejection of overmounted identity sources remain open gates,
not claims that a portable `ctypes` layout already exists.

Use a one-shot trusted sibling helper with the trusted interpreter (`-I -B`)
and a three-second subprocess timeout covering the native probe, not merely
deadline checks between potentially blocked reads. Require finite reads,
size caps (for example 16 KiB for stat), bounded output and strict parent-side
result validation. Launch/timeout/exit/parse/permission failures are `unknown`.
Qualification must test timeout and cleanup behavior; no persistent supervisor.

Hold proc-root and target-directory descriptors; open fixed children relative
to them, rejecting unexpected symlinks and handling kernel namespace links
explicitly. Parse stat as bytes: validate PID and opening `(`, find the final
closing `)` of `comm`, then extract field 22 at suffix index 19 (field 3 begins
the suffix). Do not split the entire line, decode `comm` as required UTF-8, or
persist it. Check field counts, bounds and repeated identity-bearing values;
CPU counters and process state may legitimately change.

Recheck boot ID, observer/target namespace, procfs view, target association,
PID and ticks. A vanished opened component or inconsistent sample is `unknown`,
not a stitched observation. For recorded native workers, boot/namespace must
match the qualified current context **before concluding absence**. Absence
requires a missing target in that view, same-namespace `kill(pid, 0)` returning
`ESRCH`, and stable context. `EPERM`, hidden/inaccessible targets, disagreement
or context changes mean `unknown`. Zombies are not absent before reaping [L].

This is bounded observational evidence, not an eternal unique handle: ticks
are quantized and namespace identifiers can be reused. Time-namespace effects
also require qualification. Runtime checks cannot authenticate a hostile kernel
or privileged mount administrator. No observation proves descendant/container
termination, session health or authority to release a task. Existing hostname,
ownership, stop, recovery and authority guards remain independent.

## Independent document boundaries

The following versions are **proposals**, not currently supported formats.
Version every independently accepted changed identity contract; do not assume
the outer task protects detached documents. Keep historical bytes and digests.

| Boundary | Proposed treatment |
|---|---|
| Slot/lane owner | Complete native worker; exact-object equality, no legacy field |
| Recovery and task-contained snapshots | Explicit originating task schema for new snapshots; exact worker validation |
| Claim-intent v1/v2 | Preserve their existing approval/public-text distinctions and bytes |
| New claim-intent v3/v4 | Respectively v1/v2 contracts with native worker and schema-5 origin binding |
| Assignment request v1/v2 | Preserve manual/standing-grant meanings and bytes |
| New assignment request v3/v4 | Manual/standing-grant schema-5 counterparts; v4 deferred, not enabled |
| Publisher binding | Distinct native envelope version(s); exact numbers/shapes require integration review |
| Evidence/settlement containing references only | Existing versions may remain if versioned request resolution validates every exact link |
| Execution attempt | Separate required native attempt version and exact launcher shape; deferred |
| SQLite tables/store metadata | Keep layouts and existing storage-version requirements unless a demonstrated uncovered writer requires change |
| Scope and coordinator-lock metadata | Keep schema 2; do not globally change shared `SCHEMA = 2` |

New assignment validators must match request family, publisher binding version,
origin schema, original/reserved worker shapes, claim-intent version and exact
digests. Unknown combinations refuse. A future native execution attempt replaces
launcher `process_start` with `process_identity`: object for `alive`, `None` for
`unknown`/`absent`; preserve unversioned legacy attempts unchanged. Changed
independently consumed review/repair exports need their own versions, not
speculative bumps to exports with no identity. Until qualified, these native
paths refuse; proposing a format does not enable a feature or standing grant.

At the pinned source, journal validation rejects unsupported request versions;
old exact-shaped attempt validators reject an added version field. Demonstrate
refusal at supported operational reader/writer entry points before relying on
these fences. Token-only helpers and arbitrary historical binaries are not
universally fenced. Mixed-version scans must count all capacity/reservations,
not skip unfamiliar tasks. Deployment must exclude old writers from the store.

## Opt-in inactive-task conversion

Initial profile: base schema-2 tasks in Ready/Rework and base schema-3 cooperative
tasks in Ready; ordinary findings, validation and dependencies are retained.
Support unchanged `legacy_finding_dispositions`, settled `transition_recovery`,
and fully settled **manual** `assignment_dispatch` chains. Check all task-bound
linked requests, approvals, evidence and settlements, not only the latest marker.
Schema-3 Rework needs its existing lifecycle route first; migration cannot make
it claimable. Blocked tasks need authorized lifecycle resolution; Done/Cancelled
cannot reopen. Foreground, review, repair, execution, candidate/reservation and
standing-grant/intake extensions are deferred pending specific tested profiles.

Require exact source validation, null worker, no slot/lane including reverse
leases, unchanged valid scope reservation, no transition intent, pending
recovery/assignment/execution/repair/cleanup, unresolved remote attempt or UNKNOWN.
Every required artifact must be available and valid; unknown extensions refuse.
Require revision headroom for both conversion writes and the next lifecycle
operation, and explicit operator approval bound to source digest, target schema,
conversion request and implementation/policy revision. Controller support is
also mandatory. **Task 154's UNKNOWN is excluded; task 158 remains paused.**
A pause is not migration permission; this ADR finds neither task eligible.

Old worker retirement means authorized lifecycle release of worker authority
and capacity leases, not necessarily termination of a shared server process.
Migration must not kill it or use today's native PID observation to resolve an
old identity mismatch. Independent termination-evidence requirements still apply.

Create a task-local immutable bundle via a fixed validated identifier, never
an arbitrary caller path. Retain exact original `task.json` bytes and raw SHA-256,
the existing canonical task digest(s) required by bindings, source schema/revision
and incarnation inputs, target, operator approval, allowed transformation, and a
complete field-aware inventory of supported snapshots and external references.
No recursive “anything named worker” discovery or universal replacement digest.

Add a permanent versioned `identity_migration` reference. Only schema, that
reference/phase, revision and update timestamp change; worker stays null. Preserve
task ID, creation time, scope token/reservation, repository/branch/worktree, owner,
dependencies/tracker, incarnation, cooperative session/generation, rework and
other business counters, findings/disposition epochs, operation IDs and history.
The current full-record digest necessarily changes; historical digests do not.
Old approvals remain bound to old content, old revisions remain stale and consumed
operations remain consumed. No budget, store identity, deduplication/logical key,
expiry, qualification or UNKNOWN reset; no new identifier to evade accounting.

Origin mapping records fixed logical location/external identity, source task
schema, existing digest and relationship to immutable source. Full external task
snapshots use their own schema; carried embedded legacy snapshots use this exact
mapping; new snapshots use explicit origins. Missing/ambiguous/mismatched origins
are UNVERIFIED. Never infer historical schema from the converted current task.
For settled recovery, validate its original reconstruction under schema 3, keeping
worker bytes/correlation digest; separately check current scope, monotonic
generation and permitted revisions. Do not insert a legacy worker into schema 5.
Guards preserve the migration reference/source permanently. Legitimate later
history replacements leave pre-conversion values preserved in that source;
subsequent history still obeys its existing retention rules and explicit origins.

## Durable conversion protocol

Use the existing coordinator lock and authority, not another admission controller.
For source revision `r`, the proposed forward-only protocol is:

1. Pin source and references, validate eligibility/approval, no-clobber-create the
   bundle, establish file/directory durability, then recheck exact source and
   eligibility evidence. A prepared bundle alone grants no authority or freeze.
2. Atomically install schema 4/5 at `r + 1`, unchanged inactive state/null worker,
   permanent reference and phase `pending`. Establish file/directory durability.
   The target schema immediately fences old task readers; updated readers refuse
   unrelated mutations. An ignorable flag inside schema 2/3 is insufficient.
3. Revalidate exact pending record, immutable bundle, scope and reference state;
   atomically persist phase `complete` at `r + 2` and establish durability before
   acknowledging success. Only then may a normal claim establish native identity.

| Observed crash/retry state | Required handling |
|---|---|
| Source unchanged, prepared bundle only | Not installed; retry needs fresh exact-source validation |
| Exact pending target | Explicit resume of the same approved request may complete |
| Exact complete target | Idempotent success; no repeated increments |
| Missing bundle, unexpected revision, changed binding or ambiguous write | UNVERIFIED; retain evidence |
| Later claim/lifecycle state | Validate completed lineage; never restore old source |

No automatic 4 → 2 or 5 → 3 downgrade after intent installation. Before intent,
the source remains authoritative; afterward retain dual-format readers and
resume or stop for investigation. Conversion claims no capacity and performs
no remote action. Rollback cannot erase intervening state or revive approvals.

## Implementation phases and rollout gates

1. Review this format and narrow conversion profile; admit implementation
   separately. Freeze exact publisher/attempt/bundle contracts and supported ABIs.
2. Integrate finite validators and bounded observer in isolation. Route core
   claim/reconcile/cancel/recovery, monitor's independent `ps` bypass, assignment
   and every enabled live consumer through record-directed observation. Qualify
   ordinary/cooperative new tasks and manual journal/publisher boundaries together.
   Keep unsupported native foreground/review/repair/execution/standing/intake
   paths fenced; broader formats require separately reviewed implementation.
3. Implement immutable origins and converter/resume, mutation guards, reference
   integrity and task-bound journal eligibility. Run crash and old-reader tests.
4. Resolve [#173](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/173)
   controller schema support **and confinement** with its owner. The unimplemented
   integration proposal limits eligibility to schema 2; its deployment and
   confinement remain unqualified. Separately, the implemented static preflight
   supports schemas 1/2. These remain unresolved integration gates;
   schema 4 needs explicit support, schema 5 also needs resolution of existing
   schema-3 restrictions. Do not widen guards silently, add another controller,
   create a new authority store, or bypass confinement to make activation pass.
5. After independent review and actual Linux qualification, obtain exact-release
   deployment approval. Prefer one coordinated production cutover; update complete
   installations and restart long-lived consumers. Start with a newly admitted
   native task, then separately approve each eligible conversion in the same store.

Changed hashed core/observer modules invalidate controller-bound execution plans,
including for legacy tasks. Retain historical plans/results; use the existing
new-generation/new-plan route, never unfreeze a plan or reset generation limits.
Any new operational dependency needs manifest coverage. Separate reader/writer
deployments may invalidate plans twice. Source merge alone is not deployment.

After native tasks/documents exist, supported old readers should refuse, possibly
blocking whole list/admission scans or journal opening. That is not rollback.
A reviewed rollback build must retain native readers, fences and migration
recovery while disabling further native admissions/conversions. Never relabel
schemas, remove identity fields, rewrite journals/digests or restore old snapshots.

## Finite acceptance matrix for future implementation

No tests were added or executed by this design. Required cases, in an independently
justified sandbox, include actual Linux probes as well as fixtures:

| Cases | Required result |
|---|---|
| Stable PID; modeled calendar shift; changed start ticks | Stable native identity in first two; exact mismatch in third |
| Changed boot/namespace with PID present or missing; ancestor procfs; time namespaces | Unknown outside qualified context; no absence-based release |
| `comm` spaces/parentheses/newlines/non-UTF-8; truncated/oversized stat | Correct field 22 or bounded unknown, never whole-line splitting |
| Raced target; hidden process; EPERM; source disagreement | Unknown, no stitched identity |
| Qualified missing PID + ESRCH; zombie then reaped | Absent only for qualified absence, not zombie |
| Helper timeout/bad output; substituted mount; unsupported ABI/Darwin | Unknown, bounded failure, no `ps` fallback or claim commitment |
| Arbitrary legacy strings, environments, Linux/Darwin | Unchanged API, invocation, result mapping, validation and equality |
| 2/3/4/5; cross-shapes; unknown versions; 4 → 5 claim crash | Finite validation, cooperative fences and existing counter/lease guarantees |
| Mixed reservations; monitor/recovery/manual assignment | Complete equality/counting and shared observation; no bypass |
| Native journal/publisher families; mismatched approval/version/digest | Exact round-trip links or refusal; deferred families remain refused |
| Eligible 2 → 4; 3 → 5 with recovery/manual history | Native only next claim; two revisions; unchanged lineage/counters/history bytes |
| Active/reverse lease, pending/UNKNOWN, pause, missing artifact, unknown extension | Conversion refused without clearing the blocker |
| Missing/changed origin; legacy snapshot relabeled native | UNVERIFIED; no rewrite or current-schema inference |
| Failure at every durability boundary; exact and stale resume | Only documented source/pending/complete outcomes; forward-only/idempotent |
| Old approvals/operations/budgets after conversion | No replay, renewed authority, accounting reset or current-digest substitution |
| Pinned old core/journal/publisher readers and writers; controller guards | Reject new inputs before effects; unsupported controller remains blocked |
| Controller-byte change; rollback build | Old plans retained but inapplicable; native history still readable/fenced |

Open qualification: supported Linux ABIs/mount and namespace checks, timeout
cleanup guarantees, exact independent envelope allocations, controller confinement,
and a genuinely eligible conversion candidate. Parser doubles cannot close these
gates. Future implementation also requires repository `make check` and pinned
strict checks in the sandbox, copied-installation checks and fixed-head review.

## Sources and limits

- **[S] Pinned repository baseline:**
  [`466a78d3974081d80a7c4b44d0f86ad695371c51`](https://github.com/GSA-TTS/agentic-coding-maintainers/tree/466a78d3974081d80a7c4b44d0f86ad695371c51).
  Inspect `.agents/skills/workspace-orchestrator/bin/`: `runtime-observation.py`
  (legacy probe), `orchestrator-state.py` (schemas/recovery/lock),
  `monitor-journal.py`, `assignment-journal.py` (document validation),
  `execution-observe.py`, `execution-plan.py` (attempts/hashes); and `scripts/`
  `assignment-dispatch.py`, `publish-github-assignment.py`,
  `review-workspace-preflight.py` (independent boundaries).
- **[P] Procps project documentation:** [ps(1)](https://man7.org/linux/man-pages/man1/ps.1.html),
  `lstart` and format/environment descriptions; [upstream](https://gitlab.com/procps-ng/procps).
- **[L] Linux primary documentation:** [procfs](https://docs.kernel.org/filesystems/proc.html),
  [kernel random/boot_id](https://docs.kernel.org/admin-guide/sysctl/kernel.html#random),
  and Linux man-pages [proc_pid_stat(5)](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html),
  [pid_namespaces(7)](https://man7.org/linux/man-pages/man7/pid_namespaces.7.html),
  [kill(2)](https://man7.org/linux/man-pages/man2/kill.2.html).
  These explain primitives, not qualification of this proposed backend or any
  legal, compliance, security-control or globally unique identity guarantee.
