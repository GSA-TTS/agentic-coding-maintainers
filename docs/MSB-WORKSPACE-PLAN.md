# MSB-first full maintainer workspace plan

Status: **planned, not qualified**. This is the bounded release-groundwork plan,
not an installer or a claim of completed runtime tests. The initial source
release target is v0.1.0. OpenCode is the first reference harness; Pi follows.
Prime retirement is separate work and is not performed or certified here.

## Measured checkpoint — 2026-11-06

Operator-reported guest measurements: OpenCode 2.0.30, Pi 0.84.3, Podman 5.7.0
and base Python 3.14.4. Guest-local uv 0.9.26 and Python 3.12.12 were installed;
all six quality tools were version-verified. The 15 session and 6 authority
fixtures passed. The pre-fix cleanup suite had 12 failures and 1 error across
25 tests: overlayfs reported directory `st_dev=28` and file/path-descriptor
`st_dev=29`, while rename into a child directory succeeded with the inode
unchanged. This checkpoint does not claim post-fix cleanup validation.

A manual, bounded guest-root cgroup prototype obtained verifier PASS with
CPU `100000/100000`, memory `134217728` bytes, PIDs `32`, and exact cleanup.
This is prototype evidence only, not shipped startup integration, reboot
qualification or OpenCode/Pi harness parity. The acceptance sequence below
remains open; these measurements do not qualify full MSB support.

## Deployment and authority boundary

MSB is the first outer VM target. Put the **full maintainer workspace and its
orchestrator inside the VM**, not only a review worker. Install the CLI/quality
tools, harness binaries, canonical skills, selected profiles and guest-local
rootless OCI engine there. The outer host provisions, pins and controls the VM
and approved credential/egress bindings; it does not expose a host Docker socket
or quietly run guest tests on the host. A Git worktree is not isolation.

Within the VM, use one authoritative controller/state root. Canonical code and
policy are read-only to workers; controller-owned config, admission state and
accepted evidence are writable only through the trusted authority path. Keep
candidate source/worktrees and scratch output separate as untrusted data.
Candidate-controlled startup hooks, config and executables cannot redefine
controller policy, become accepted evidence by location alone, or start a second
authority over the same work. The selected harness must preserve these controls,
not merely ask the model to follow them.

Candidate builds/tests run in disposable inner containers, not in the controller
environment. Reuse Patterns' `oci-engine` kit rather than duplicating its
installer. Pin both the engine kit and future workspace kit/payload at reviewed
full SHAs; a moving branch, version label or successful provisioning marker is
not execution evidence. Preserve source provenance. Signed artifacts and their
verification are deferred until such artifacts actually exist.

Nested rootless OCI shares the VM kernel; it is not a second VM boundary. Real
execution must prove numeric non-root identity, effective user/mount/network
isolation, dropped capabilities, no-new-privileges, read-only candidate input,
private writable scratch/HOME/cache, resource limits, and absence of controller
state, runtime sockets and credentials. Start network-off with preloaded immutable
images, no implicit pull. Unsupported mandatory controls refuse execution. A
`docker` alias pointing to Podman does not qualify Docker or either engine's
behavior. See [the existing portable design](PORTABLE-REVIEW-WORKSPACE.md).

## Acceptance sequence

1. **Reproducible VM installation.** Record the exact MSB/guest-image/architecture,
   kit and Maintainers full-SHA tuple, installed tool and harness versions, file
   hashes/modes, and selected configuration. Prove the tools execute inside the
   VM, with no unintended host fallback. Repeat startup must not overwrite local
   config, work or state. Fail explicitly on unavailable dependencies.
2. **One persistent authority.** Specify persistent storage for controller state,
   config, clones, dirty worktrees and referenced evidence. Test normal shutdown,
   restart and abrupt interruption; preserve incomplete writes, locks and dirty
   work. On restart reconcile recorded workers/PIDs and live ownership before
   admission; stale PIDs or a stored monitor checkpoint do not prove a live worker
   or continued monitoring. Never silently take over uncertain locks. Prove no
   second authority root is created. Export a coherent private backup and verify
   restoration; document what VM disposal destroys if not exported.
3. **Actual inner-engine qualification.** Use the normal kit translation and run
   both positive and hostile negative cases on rootless OCI, measuring effective
   controls rather than checking a marker or `--version`. Include attempted
   controller/credential access, mount writes, network access, timeout,
   cancellation, descendant cleanup and resource exhaustion. Record execution
   and cleanup outcomes separately, including missing evidence as UNVERIFIED.
4. **OpenCode end-to-end reference.** Bind one admitted task to a source head,
   bounded candidate edits, actual isolated checks, independent fixed-head review
   and accepted evidence. Demonstrate permission denials on real tool paths and
   prevent candidate data/config from changing trusted controls. Reconcile after
   a VM/controller restart and export evidence with hashes checked outside the
   VM. Existing model-free fixtures are not this qualification.
5. **Pi reference next.** Install a pinned Pi inside the same VM layout and prove
   equivalent admission, permissions, isolated execution, restart and evidence
   handling through its actual adapter/tool paths. Do not infer this from OpenCode
   results or a shared profile vocabulary.
6. **Consumer upgrade and rollback.** Exercise coherent backup, state/evidence
   compatibility validation, quiescent update, restart and explicit resumption.
   Preserve newer-format evidence on rollback; code-only rollback after state
   migration is not presumed safe. Publish only nonsensitive tuple-bound evidence
   and narrow support claims after independent review.

## Support matrix (at groundwork)

| Deployment/harness | Status | Evidence needed before claiming support |
|---|---|---|
| MSB full workspace + OpenCode | Planned / runtime unknown | All installation, persistence, inner-engine and OpenCode cases above |
| MSB full workspace + Pi | Planned second / runtime unknown | Same VM/engine cases plus actual Pi permission and adapter execution |
| Other outer VM backends | Unknown, not qualified here | Separate exact backend/image/architecture tuple and full acceptance run |
| Native host full-workspace execution | Not qualified here | Separate isolation and lifecycle qualification; no fallback from failed MSB |

Existing [OpenCode compatibility evidence](OPENCODE-COMPATIBILITY.md) and
profile/tool qualification drivers remain useful within their recorded scope;
they do not establish full MSB support. A source tag, static test pass or agent
summary cannot promote any row. No stable 1.0 API, universal native support,
production kit, signed release artifact or automatic publication is claimed.
