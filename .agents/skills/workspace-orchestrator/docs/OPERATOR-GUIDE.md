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
| GitHub writes | Task-branch push and fixed-head reviews permitted; an independent applicable CODEOWNER may merge the current approved head after all gates; PR closure requires per-action authorization |

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
4. Findings return to the implementation owner. Re-review the changed SHA.
5. After three failed substantive cycles, set `Blocked`, preserve evidence, and
   escalate while unrelated work continues.
6. `Ready for human review` is not `Done`. The orchestrator may commit, push a
   task-owned branch, and submit a review bound to the inspected commit after
   rechecking the remote head; verify the submitted review's commit afterward.
   Do not claim independent sign-off from an unverifiable or failed reviewer.
   Evaluate merge readiness after a clean approval. The independent applicable
   CODEOWNER who approved the current head may submit an eligible PR for merge
   without a separate operator prompt, guarded by that reviewed head SHA. PR
   closure without merge still requires per-action operator authorization. A
   queue entry is not a completed merge; check the owning repository for the
   terminal result.

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
