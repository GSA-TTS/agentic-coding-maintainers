# Coordinated Work Operator Guide

This is a practical first version for one primary OpenCode session coordinating
bounded child agents. It is not a daemon, a security boundary against the same
local user, or a distributed scheduler.

## Defaults

| Control | Default |
|---|---|
| Global active workers | 6 (monitors, reviewers, implementation, nested agents) |
| Implementation lanes | 2 |
| Poll cadence | 600 seconds, foreground only |
| Delegation depth | One level on installed OpenCode v1.19.0 |
| Rework limit | 3 substantive cycles, then checkpoint/escalate |
| Review gates | Independent QA; baseline security; independent security for trust-boundary changes |
| GitHub writes | Use the consumer's recorded standing authority and narrower current steering; this guide grants no permissions |

## Human-reviewed delivery

The canonical OpenCode start command is `examples/commands/orchestrate-start.md`
inside this skill. Install a byte-identical copy at the consumer workspace's
`.opencode/commands/orchestrate-start.md`. Quit and restart OpenCode after command
changes. The command directs native task dispatch; installing it does not prove
that workers ran or that runtime capabilities are qualified.

Within explicit delivery scope, continue admitted work and choose further bounded
tasks using existing standing authority. Do not wait unconditionally for task
selection or reauthorization of every covered write. Ask when scope, ownership or
the intended action lacks authority. Current narrower operator steering controls;
admission itself grants no remote capability.

For human-reviewed delivery, keep automated GitHub App/review publication parked
and retain native review evidence for human approval. Use multiple independently
reviewable default-branch-based PRs with explicit integration order. A dependent
implementation starts from refreshed main only after its prerequisite merges;
do not stack PR bases on branches subject to auto-deletion. Continue independent
batches while earlier PRs await human review.

Reserve two of the six worker slots for QA/security, with no more than two
implementation lanes. Monitors and specialists count too. Reduce implementation
admission as review accumulates. Dispatch actual native OpenCode tasks and record
task/session IDs and outcomes; specialist analysis supplements mandatory review.
Unavailable dispatch is UNVERIFIED coverage, not a simulated review. A finished,
reconciled worker can release its slot while its PR awaits human approval.

## Startup

1. Reconcile live configured repository/project state and local task state:
   ```bash
   export WORKSPACE_ORCHESTRATOR_ROOT="$PWD"
   "$SKILL_DIR/run.sh" state reconcile
   ```
2. Inspect worktrees and dirty state before assigning ownership:
   ```bash
   # Inspect only trusted maintainer source on the host. For an untrusted
   # checkout, use the state tool's hardened Git identity probes; bare Git
   # status/diff can run repository-configured filters or fsmonitor programs.
   git -C /path/to/trusted-maintainer-repository worktree list
   "$SKILL_DIR/run.sh" state list
   ```
3. Create one record per independent task. Scope is a stable structured string,
   not a title copied from an issue:
   ```bash
   "$SKILL_DIR/run.sh" state create example-task \
     --scope 'owner/repo:path:src/example:change' \
     --kind implementation --repo owner/repo \
    --branch task/example-task --worktree "$PWD/work/example-task" \
     --base-sha "$(git rev-parse HEAD)" \
      --owned-path src/example --owned-path tests/example \
      --acceptance 'The recorded behavior and regression tests pass' \
     --next-action 'claim and implement'
   ```
4. Claim before dispatch. The PID must identify the actual process that owns the
   work, not merely a parent shell that can outlive it:
   ```bash
   "$SKILL_DIR/run.sh" state claim example-task --owner primary --pid <worker-pid>
   "$SKILL_DIR/run.sh" state transition example-task Implementing
   ```

## Worktrees

Use one branch and one worktree per implementation task. Do not force-check out
the same branch in multiple worktrees. Review a fixed SHA in a separate detached
checkout or `git archive` tree. Record the path and base SHA before dispatch.

Worktrees are directory isolation, not security isolation. The state tool checks
declared path/branch/worktree conflicts; semantic overlap remains an orchestrator
judgment. Reviewed code still runs only through the consumer workspace's
approved sandbox harness. Serialize shared manifests, generated files,
lockfiles, and Git ref/config changes.

## Monitoring

Create and claim a `kind=monitor` task first; the monitor consumes one of the six
global slots. The monitor must own its PID, so use an `exec` wrapper that claims
with the PID the monitor process will inherit. Supply a validated config from
`examples/` or your consumer workspace:

```bash
sh -c '"$1/run.sh" state claim monitor --owner monitor --pid $$ >/dev/null && exec "$1/run.sh" monitor --task-id monitor --config "$2"' sh "$SKILL_DIR" "$CONFIG"
```

Foreground loop while this terminal/session is intentionally kept alive:

```bash
sh -c '"$1/run.sh" state claim monitor --owner monitor --pid $$ >/dev/null && exec "$1/run.sh" monitor --task-id monitor --config "$2" --loop --interval 600' sh "$SKILL_DIR" "$CONFIG"
```

The monitor stays quiet when nothing changed. It prints material PR/configured-project
changes, and exits `3` with `UNVERIFIED` when it could not query complete state.
Checkpoints store the last successful observation and a separate failure record;
they do not prove that monitoring continued after process exit.

OpenCode v1.19.0 has no scheduler. Child/background work dies with the CLI
process. Do not claim this loop survives logout, TUI exit, sleep, or restart.

## Status and recovery

```bash
"$SKILL_DIR/run.sh" state show example-task
"$SKILL_DIR/run.sh" state list
"$SKILL_DIR/run.sh" state reconcile
```

`reconcile` compares active records with process identity, worktree existence,
transition intent, and bidirectional reservation evidence. A verified dead
worker or missing worktree becomes `Blocked`. Corrupt records, failed process
inspection, malformed locks, ownership mismatch, or unreadable state produce
exit `3` / `Unknown`; nothing is stolen or repaired automatically.

Never infer health from an OpenCode database `running` or `completed` field
alone. On v1, a subprocess aborted by CLI exit can be recorded `completed` with
`User aborted the command` buried in output.

## Review and rework

1. Implementation owner returns exact SHA, files, validation, and residual risk.
   After committing, bind the actual assigned worktree head and invalidate stale
   review evidence:
   ```bash
    # Obtain this full SHA from reviewed/verified evidence, then let the state
    # tool verify it against the assigned worktree with hardened Git probes.
    HEAD_SHA=<full-40-hex-reviewed-head>
    "$SKILL_DIR/run.sh" state update-head example-task "$HEAD_SHA"
   ```
 2. Orchestrator transitions to `Reviewing` and assigns QA at that SHA.
    Record review and evidence without hand-editing task JSON:
    ```bash
    "$SKILL_DIR/run.sh" state record example-task reviewer qa-reviewer --reviewed-sha "$HEAD_SHA"
   "$SKILL_DIR/run.sh" state record example-task validation \
     'tests/orchestrator-state-test.sh PASS at <sha>'
   ```
3. Add an independent security review when credentials, identity, permissions,
   isolation, networking, execution, dependencies, or CI changed.
4. Objective findings return to the implementation owner for correction. Retain
   evidenced fixed/refuted/persists dispositions. Re-review every materially
   changed SHA; an implementer's self-review cannot supply independent coverage.
5. After three failed substantive cycles, set `Blocked`, preserve evidence, and
   escalate while unrelated work continues.
6. `Ready for human review` is not `Done`. Require completed applicable validation
   and review at the current head, with no unresolved Blocker or Should-fix.
   Failed, skipped, absent or pending required checks are not green. Candidate
   tests/builds run only in the approved sandbox with observed transcripts.
   The orchestrator may commit, push or publish only within recorded authority;
   parked publication remains inactive. If a submitted review is authorized,
   bind it to the inspected commit after rechecking the remote head and verify
   the submitted review's commit afterward.
   Do not claim independent sign-off from an unverifiable or failed reviewer.
   Evaluate merge readiness after a clean approval. The independent applicable
   CODEOWNER who approved the current head may submit an eligible PR for merge
   only under the consumer's applicable authority, guarded by that reviewed head
   SHA. Human approval remains required in human-reviewed delivery mode. PR
   closure requires its own applicable authorization. A
   queue entry is not a completed merge; check the owning repository for the
   terminal result.

### Legacy finding dispositions

Legacy `state record TASK finding TEXT` entries are retained in their original
order. Duplicate finding text is refused. The baseline provided
`record TASK resolution TEXT`, which removed the matching finding string without
retaining a disposition. This change intentionally refuses that destructive
command; migrate callers to `resolve-finding` with the bindings below. Findings
already deleted by the old command cannot be reconstructed from the task record.
Preserve any separately retained review evidence; do not claim this migration
retroactively restores that missing history.
For an implementation task in `Reviewing`, record a fixed/refuted disposition:

```bash
"$SKILL_DIR/run.sh" state show example-task
# Take REVISION, HEAD_SHA and the zero-based FINDING_INDEX from that record.
# FINDING_SHA256 is SHA-256 of the exact finding's UTF-8 text, without a newline.
"$SKILL_DIR/run.sh" state resolve-finding example-task \
  --finding-index "$FINDING_INDEX" --finding-sha256 "$FINDING_SHA256" \
  --head-sha "$HEAD_SHA" --expected-revision "$REVISION" \
  --disposition fixed --reviewer qa-reviewer \
  --evidence 'Reviewed fix at <sha>; retained review/transcript at <location>'
```

Use `refuted` only with evidence that the finding does not apply. A persisting
finding stays unresolved. The command requires a nonempty implementation owner,
a distinct reviewer label, and nonempty evidence. It checks the actual assigned
checkout/head and cleanliness in production; a stale revision, mismatched finding
index/text digest, duplicate disposition in the current epoch, or missing identity
is refused without changing the record. Refresh `show` before each disposition.

`legacy_finding_dispositions.history` is append-only through the tool, including
the owner, reviewer, evidence, disposition, finding digest/index, head, epoch and
write revision. All findings need a current disposition before legacy readiness
or readiness recovery can succeed; the existing reviewer, validation, current-SHA
and clean-checkout requirements still apply. `update-head` increments the epoch
on each recorded head change, including A→B→A, preserving old history without
reactivating it. Claiming under a different owner also invalidates dispositions.
Unrecorded external changes are not an observed epoch: always update the recorded
head as work changes. New findings still revoke readiness. Present but malformed
disposition data yields exit `3` / `UNVERIFIED`; it never falls back to legacy
success. Missing extension data is compatible but resolves no findings. Invalid
arguments exit `2`; stale/conflicting or disallowed claims exit `4`.

These are operator-supplied local claims, **not authenticated independent-review
attestations**. A different label cannot prove a different person/session performed
the review, and evidence text is not verified as a transcript. The orchestrator
must retain actual independent review and sandbox validation evidence. The store
is not tamper-proof against its owning user. Tasks with `review_protocol` remain
ineligible for this command and retain their existing fail-closed readiness guard;
legacy claims cannot bypass runtime corroboration or authorize GitHub approval.

## Shutdown and cleanup

1. Stop monitor with `Ctrl-C`.
2. Run `"$SKILL_DIR/run.sh" state reconcile` and inspect active tasks.
3. Transition intentionally paused tasks to `Blocked` with a next action.
4. Confirm commits/patches are preserved and no worker is live before removing
   worktrees. Follow the consumer workspace's approved cleanup and evidence-
   retention policy.

## Runtime upgrades

Pilot a new harness/runtime under a distinct command and separate config, data,
cache, log, and worktree roots. Keep orchestration limits external unless the
runtime documents and verifies equivalent admission. Promotion requires
instruction loading, permission precedence, restart recovery, API compatibility,
and worktree-isolation evidence while the current runtime remains available for
rollback. Put organization-specific version and issue status in consumer docs or
a dated example, not this reusable guide.
