# Portable review workspace: package, kit and synchronization design

Status: implementation in progress. This document defines the deployment target;
it does not claim nested execution or kit installation is qualified.

## Outcome and canonical ownership

Teams should be able to install the same review workflow in a local workspace or
an acq sandbox, choose their repositories/Project and model, run independent
reviews and isolated tests, repair findings, and deliver green PRs for a human.

Maintainers owns the reusable orchestration and review implementation and tests.
`review_things` is a reference consumer with additional hostile-PR and local
endpoint safeguards. Its root policy, private engagement configuration and
existing evidence are not replaced by another repository's policy. Patterns
owns thin acq kit packaging; Quickstart owns outer sandbox provisioning and kit
translation. A second independently edited copy of orchestration is rejected.

Reusable review-harness extraction must preserve original source provenance,
tests, modes and referenced rules. Machine-specific CA/listener inventories,
private reviews, credentials and workspace state never enter the package.
Do not simply copy all of `review_things` into a guest or publish its root policy
as universal team instructions.

## Three separate boundaries

1. The host operator/acq pins the outer guest, kit source and credential/egress
   bindings. No host container socket or privileged host-control mount is needed.
2. A guest controller owns installed policy, task state, accepted evidence and
   the guest-local OCI runtime. It remains trusted and must not execute candidate
   hooks, startup files, scripts or tests in its own process environment.
3. Disposable inner containers execute candidate code with only explicit source
   and scratch mounts. They receive neither controller directories nor provider,
   GitHub or signing credentials and cannot control the OCI runtime themselves.

Nested containers share the outer guest kernel. They add namespace/capability/
seccomp/resource isolation, not another microVM boundary. Rootless Podman is
preferred where effective controls pass; guest-local Docker is a separate mode.
Outer guest compromise threatens its authorized services and mounted data.
Host-owned final evidence export remains useful for durability and separation.

The initial inner-runner contract is network off, preloaded immutable image,
no implicit pull, numeric non-root identity, read-only candidate snapshot,
isolated writable HOME/work/cache, dropped capabilities, no-new-privileges,
bounded CPU/memory/PIDs and explicit timeout/cancellation outcomes. Unsupported
mandatory controls refuse execution. Engine availability alone is not a pass.

## Reuse the existing OCI kit

Patterns already supplies `integrations/isolation/acq-kits/oci-engine` under the
neutral `hybrid/v1` mixin schema. It installs rootless Podman and prerequisites,
storage fallbacks and a Docker-compatible command wrapper. Its provisioning can
degrade without preventing outer guest startup. Reuse it; do not duplicate its
installer or assume its marker proves execution safety.

The current kit schema has no dependency declaration. Compose two explicit
`--kit` references: the pinned OCI kit and the pinned review-workspace kit.
Quickstart's built-in picker and consumed Patterns pin are distinct from the
Patterns advisory catalog. Add picker integration only after the reviewed kit is
reachable at the consumed pin. Local explicit kit references can qualify first.

The review runner must distinguish actual Podman from native Docker even when
`docker` is a wrapper. Rootless UID mapping, cgroup delegation, mount behavior,
effective network denial and cleanup must be tested for each backend. Existing
Docker execution-observer assumptions do not qualify Podman by aliasing it.
The earlier MSB file-device mismatch also means repair-controller filesystem
capabilities require their own probe.

## Deployment composition

The proposed review kit is a thin adapter over a pinned Maintainers payload:

- Install a declared portable package into a dedicated guest review workspace.
- Install complete canonical skills and selected identical command/profile
  copies after the operator reviews permission inheritance.
- Keep the controller outside candidate-controlled checkout paths.
- Accept team-local repository/Project/provider/authority configuration; no GSA
  repository set or specific VM manager is required.
- Verify integrity and capabilities at startup without overwriting local work.
- Export complete evidence before guest disposal, with hashes checked outside
  the guest. A model answer or provisioning marker is not installation evidence.

Installation downloads, provider egress, container-image acquisition and host
configuration require the operator's applicable authorization. Ordinary candidate
execution starts network-off. Human approval remains the default delivery mode;
the parked automatic publication/App work is not a package prerequisite.

## State-preserving consumer upgrades

`sh scripts/review-workspace-preflight.sh --source CANONICAL --consumer WORKSPACE
--expected-source FULL_SHA` is a read-only first check. It inventories the complete
skill, selected profiles/commands and local state, reports drift and active-state
signals, and verifies the pinned source. It does not import a controller, query
processes, make network calls, migrate records, or prove quiescence. Its sanitized
status is ALIGNED_STATIC, ACTION_REQUIRED or UNVERIFIED; no status means safe to
overwrite a running controller.

The wrapper selects `python3 -I -B` before interpreter startup. Direct Python use
requires those flags and otherwise refuses before importing package helpers.
Bounded monitor JSON and interrupted task-write markers are inspected; SQLite
contents remain explicitly unmeasured and require separate coherent backup and
validation. The preflight cannot replace actual controller-state compatibility
tests, nor classify a stable but active worker as stopped.

Upgrade in this order:

1. Reconcile live task ownership with the installed controller. Finish or stop
   workers and monitoring; do not remove stale locks or missing worktree records
   to manufacture a clean upgrade.
2. Preserve a coherent private backup of the entire state, current installation,
   selected profiles/commands, wrappers, configuration and provenance. Preserve
   dirty worktrees and referenced evidence separately; a state archive is not a
   backup of everything those records reference.
3. In a network-off disposable environment, validate a copy of legacy task JSON
   with the new code and exercise representative lifecycle cases. Original
   absolute paths and process IDs are data in this test, not proof of live worker
   identity. Do not inject new review/repair evidence into legacy tasks.
4. Verify the source commit, manifest and absence of local edits. Run the existing
   explicit skill sync for `workspace-orchestrator`; omission selects another
   skill. Install the shipped command separately, verify unchanged profile bytes,
   and update the consumer pin. Preserve local policy and wrapper differences.
5. Verify installed bytes/modes and unchanged state, restart OpenCode, reconcile
   with the new installed controller, and resume admission deliberately.

Code-only rollback is safe only before new-format state is written. Thereafter,
preserve newer evidence and restore compatible code/state together, or use a
reviewed reverse migration. Old schema-2 readers may accept extra fields while
ignoring their guards. Same schema number does not imply semantic compatibility.
Do not discard new work to restore an earlier snapshot.

## Implementation sequence and acceptance

| Increment | Required evidence |
|---|---|
| Upgrade preflight and design | Bounded read-only inspection; degraded/malformed/changing-state tests; independent review |
| Reference consumer upgrade | Quiescent backup, isolated legacy-state validation, complete sync/profile/command parity, explicit restart |
| Portable harness/package | Declared files and provenance, no local private data, conflict-safe materializer and neutral consumer tests |
| Explicit inner Podman/Docker runner | Real positive/negative execution, effective isolation/resource checks, no implicit pull, timeout/cleanup/evidence export |
| Thin acq kit | Actual install and repeat startup using normal kit translation on each claimed outer backend; unavailable OCI reported honestly |
| Team rollout | Tested installation/update instructions, pinned release/consumed tuple and two neutral repo configurations |

The preflight and design are the first increment, not a kit release. Nested OCI
capability and packaging must pass before any report calls the acq deployment
supported. Each implementation belongs upstream first; consumers then sync the
reviewed revision and retain evidence of the exact installed version.
