# Frozen plan/current assessment trial — 2026-10-29

AI-assisted continuation after merged PR79 at
`9b3dd2f7dd175d111666a2b1e66026586963892b`.

## Implemented

Before dispatch, an operator-reviewed execution plan binds task/repository,
owner, review generation/epoch, packet/policy, full required definition/case
inventory and installed controller-module hashes. Planned definitions must use
packet-backed committed source bytes. The observer enforces exact plan selection
at admission and before each dispatch. Undispatched operation IDs remain reserved
across generations, so replacement plans cannot collide after intent creation.

The read-only assessment combines retained review claims with separately scoped
execution statuses: PASS, FAIL, UNVERIFIED and NOT_REQUIRED. It verifies source
currentness, retained artifacts, settlement and original applicability. Normal
worker-slot release does not invalidate otherwise current settled evidence;
source drift, cancellation, changed plan/controller or recorded integrity loss
prevents credit. An entirely empty execution selection is not a passing result.

## Independent analysis and review

Parallel native architecture/security agents shaped the change. Security analysis
identified post-hoc case selection as insufficient, leading to frozen predispatch
requirements instead of a caller-selected assessment filter. A Nexus read-only
routing experiment, with generic task text only, recommended a graph workflow.
It executed no implementation or vote and had no decision weight.

Parallel fixed-revision QA/security reviewed
`07eec4c5e0bdcd204dd196984bdcab1fe7acc2aa`. Security found no material issue in
scope. QA found undispatched operation IDs could be reused in a later plan,
causing a failure after dispatch intent was stored. The owner added cross-plan
reservation checks and tests for refused reuse and valid fresh-ID replacement.

## Real Ubuntu VM / Docker trial

The operator authorized a bounded continuation using cached Alpine, fresh
network-off Docker guests, non-root execution, read-only root/source, dropped
capabilities, no-new-privileges and bounded CPU/memory/PIDs. The candidate
controller ran inside the Ubuntu Multipass VM against isolated task state,
never on the host or installed production authority.

The trial used public commands for packet capture, review begin, plan admission,
execution observation, exact-container stop reconciliation and assessment.
Two separately planned cases produced:

```text
good: status PASS, correctness PASS, source drift UNVERIFIED, candidate_ready false
bad:  status FAIL, correctness FAIL, source drift UNVERIFIED, candidate_ready false
```

Repeated execution observation retained one launcher; read-only assessment replay
left task state unchanged. All other execution obligations were explicitly
NOT_REQUIRED, not misreported as reviewed. The review claims section remained
independently incomplete. Containers were stopped/reconciled/removed. No provider
calls, new image pulls, remote effects or MSB execution claims were involved.

## Verification and remaining scope

Twelve focused plan tests pass, including current positive evidence after worker
release, negative and missing evidence, idempotent admission, post-hoc refusal,
owner/task/repository/epoch/controller substitution, empty requirements, recorded
loss, dirty-source-versus-packet mismatch, exact dispatch selection, deleted plan,
new generation, source drift, read-only CLI and cross-plan operation reservation.
Full Docker repository checks passed before the final reservation correction;
final full verification is required before publication. Ruff/Pyright pass; Bandit
passed on the initial plan implementation. Generic OpenCode runtime probes remain
explicitly skipped in repository tests; this trial does not claim model review.

Overall candidate readiness, trusted oracle approval, automatic owner patch
transport, durable PR monitoring, GitHub effects and polyrepo delivery remain
separate obligations. No approval/merge policy, daemon or controller promotion
is activated by this assessment command.
