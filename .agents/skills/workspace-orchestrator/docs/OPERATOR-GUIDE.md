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

Use the consumer's canonical action matrix and grant contract, if adopted; this
skill supplies no maintainer-specific policy, repository IDs or pilot grant.
Policy adoption is not activation. Existing per-action approval requirements
continue until grant support is qualified and a human separately activates it.
Covered routine actions then need no repeated prompts. Recheck current grant,
task fences, exact fields/ref, expiry/revocation, durable budgets and downstream
effects before dispatch. Preserve historical UNKNOWN and paused work; a new
grant cannot reinterpret old evidence. A cooperative same-account host pilot is
not protection against hostile host code; a protected broker is a later distinct
boundary, and candidate execution always requires independent isolation.

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

## Foreground selection order

Use each foreground reconciliation pass to select work at decision boundaries;
preserve in-flight owners rather than interrupting every running task. This is
operator guidance, not a scheduler or runtime enforcement, and grants no new
authority. Existing ownership, capacity, review and remote-action gates apply.

1. **Check terminal state first** in the owning repository. Remove merged or
   closed PRs from the actionable queue; `UNKNOWN` mergeability on a terminal PR
   is not a blocker. An unverifiable terminal state is not proof of completion.
2. **Evaluate approved, green PRs for a human merge decision before review work.** Approval and
   green CI alone are insufficient: verify the current head, applicable human /
   independent CODEOWNER approval, required checks, resolved threads, non-draft
   status, dependency and acceptance gates, and repository merge rules under the
   consumer's authority. Retain the explicit human merge decision required by
   the review section below; approval and priority do not grant queue admission
   or issue-closure authority. Immediately before an authorized submission, recheck
   the inspected/approved head and use the expected-SHA guard and permitted merge
   method or queue. Make at most one merge submission attempt per PR per pass;
   a retry in a later pass requires changed evidence or explicit operator
   direction. Observe the result; queue entry never means merged. Bound queue
   observation to at most 10 minutes per pass, then release the observer slot
   with the observed queue state and next action retained. Later reconciliation
   checks terminal state again; do not leave a background observer running.
3. **Re-review changed heads or substantive new evidence for prior findings**
   from a finite snapshot captured at the start of the pass. New arrivals do not
   extend or restart that batch. Skip unchanged waiting heads without new
   evidence; distinguish owner repair from actionable reviewer work. After this
   bounded batch, admit at least one eligible waiting new review before the next
   pass when capacity permits. If capacity prevents that admission, retain the
   obligation across passes and satisfy it before starting another re-review
   batch when capacity becomes available.
4. **Review new, non-draft, unreviewed PRs.** Operator-designated urgency or a
   verified security advisory may outrank routine reviews; record the evidence,
   owner and scope. Otherwise tie-break by dependency unblocking, then waiting
   age and review effort. Priority never bypasses review or erases the waiting
   new-review obligation.
5. **Admit appropriate ready implementation** only when higher classes have no
   actionable work or cannot consume available capacity. Blocked items must not
   idle independent lanes or starve reviews; preserve reserved review capacity.

For each admission, retain the existing task scope and selection reason. For
each skipped higher-priority item, record the skip reason, blocker, responsible
owner and next action using existing `next_action` / `validation` fields. Retain
any unfulfilled new-review obligation there too; no new schema is needed.

| Scenario | Foreground decision |
|---|---|
| Merged PR reports `UNKNOWN` mergeability | Reconcile the terminal result; do not block actionable work on mergeability. |
| Approved, green PR and review work both wait | Verify gates and present the required human merge decision first; submit only after authorization, guarded by its approved head. |
| Changed heads keep arriving while a new review waits | Finish the finite snapshot without restarting; admit a waiting new review before another pass, or carry the obligation until capacity allows before another re-review batch. |
| Higher-priority PR needs owner repair or human approval | Record the skip reason, owner and next action; continue eligible reviews and independent implementation that fits available capacity. |
| Submitted PR remains queued | Observe for at most 10 minutes this pass, then release the observer with queue state and next action; recheck terminal state later, with no resubmission absent changed evidence or operator direction. |

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

### Core-only cooperative binding pilot

Schema 2 remains the default. An inactive `Ready` task can opt into schema 3
with `state claim ... --session-id <opaque-ASCII-token> --expected-generation 0
--expected-revision <observed-revision>`. Tokens are 1–128 ASCII characters
matching `[A-Za-z0-9][A-Za-z0-9._-]*`; use private UUID-style labels without
personal data. Retained `cooperative_binding` generation starts at 1, and the
worker/global-slot/implementation-lane records agree exactly on session and
generation. This is cooperative correlation and stale-write fencing, not native
caller authentication or remote authority.
Opt-in checks complete prospective state and exact scope metadata before
capacity reservation. Retained domain or unknown extensions are unsupported in
schema 3; only base fields, cooperative binding, core legacy-finding
dispositions, and the private transition-recovery receipt are accepted.

For bound active tasks, every `record`, `update-head`, `transition`, and
`resolve-finding` invocation supplies `--expected-session-id`,
`--expected-worker-id`, `--expected-generation`, and `--expected-revision`.
Use explicit observations; the CLI never fills these comparisons from state.
Missing flags yield UNVERIFIED (3), and complete mismatches are refused (4).
All comparisons and reservation checks occur under the lifecycle lock.

To release and re-claim, the owner makes a guarded transition to `Blocked`.
The retained generation survives worker release. An inactive operator transition
to `Ready` requires `--operator-action --operator-reason <rationale>` and explicit
generation/revision. A subsequent explicit session claim increments generation;
schema-3 claim from `Rework` is unsupported. Operator declarations cannot bypass
an active owner: only cancellation of a same-host worker whose PID is verified
absent is permitted. Execution-stop and repair gates still apply.

Core `show`/`list` support pilot observations but emit private raw state and confer
no authority. Public core readers/writers default to rejecting schema 3, as do
older schema-2 core readers and the existing native preflight. Reconcile refuses
the entire authority before recovery writes if any bound task exists. Interrupted
bound intents are preserved and block ordinary mutations. To recover one supported
interrupted task explicitly:

```bash
"$SKILL_DIR/run.sh" state reconcile --recover selected-task --operator-action \
  --expected-revision <current-revision> --expected-generation <current-generation> \
  --operator-reason 'Preserved interrupted work; checkpoint for operator review'
```

The only settlement is `Blocked`. This operator declaration is not authentication.
Use exact flags; positional selection cannot accompany `--recover`. Recovery
requires a legal durable intent, exact retained scope, complete worker/capacity
metadata, consistent reverse associations, and actual same-host worker absence
when the source is active. Unknown runtime or another unsettled task refuses.
Existing execution/repair guards apply. Missing capacity is justified only by an
original releasing intent or a durable pending receipt. Both pending/final record
shapes and byte budgets are preflighted before effects. A private pending receipt
is persisted before cleanup; retry supplies the current revision and original
rationale and rechecks immutable-correlation snapshots and remaining owners.
Pending recovery blocks ordinary mutation/admission. Settlement preserves scope,
generation, findings, head, review/validation evidence and existing rework count;
it does not replay the original target or increment rework again.

Full capacity cleanup is slot-first then lane, for original release and pending
recovery. The pending receipt binds actual initial capacity-presence observations.
Retry refuses capacity reappearance and lane-absent/slot-present cleanup when
both were initially present. A lane already absent from the original
`Implementing → Reviewing` lane-only release remains legitimate, including on
pending retry; an intent label alone cannot grant that exception.

After any pending or settled receipt is persisted, a receipt-aware core is
required. The previous schema-3 core at canonical base `aeaa68ce` rejects
`transition_recovery` as an unsupported extension. An older core cannot operate
this authority even after settlement. Never strip the receipt for compatibility;
retain the supporting core or quarantine state pending reviewed migration.

Recovery does not cover every crash. Missing terminal scope, empty reservation
remnants, or a lane acquired before durable intent are unsupported. No reservation
is recreated. Changed identity, duplicate/reverse conflicts, live/reused/foreign
or unknown processes refuse before cleanup. Stale coordinator-lock recovery is
separate; automatic reconciliation and bound domain activation remain unchanged.
Receipt digests are local consistency checks, not tamper-proof attestations.

Keep this pilot on core lifecycle commands. Standalone monitor polling rejects
schema 3 before configuration loading and monitor-directory/poll-lock/store
creation; durable polling also guards before opening its store. Execution
observation rejects bound tasks before definition/runtime work and rechecks
under the coordinator lock before creating its runtime config. Other state-aware
controllers use the rejecting public core reader. These are refusal guards;
foreground/domain/monitor execution for bound tasks remains unsupported. Full
production binding and a native/GitHub bridge remain pending.

Migration is per-task opt-in, with no bulk conversion. To stop the pilot, stop
new bound claims, have the current owner make a guarded release to `Blocked`,
and preserve dirty worktrees and unsettled evidence. If the owner exited, use
only the guarded cancellation path after independently verifying termination.
Use explicit recovery for supported interrupted intents; preserve unsupported
interruptions for operator investigation.

For rollback, preserve the original authority and use operator-approved tooling
to export a complete, access-restricted private backup including reservations
and referenced artifacts. Quarantine the affected authority from legacy
automation. Do not downgrade schema 3, strip bindings, lower generations, delete
leases, or remove selected records to unblock reconcile. Older readers remain
unsupported. Retain the guarded CLI or wait for reviewed migration tooling;
fresh legacy work requires separate admission without overlapping active work.
Private `show`/`list` output is not a complete backup or public evidence. The
canonical maintainer repository's `docs/NATIVE-OWNERSHIP.md` documents the
contract, stop procedure, and offline fixture.

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

The monitor retries its read-only `gh pr list` and `gh project item-list`
queries on explicit HTTP 502/503/504 diagnostics only: at most three attempts,
with one- and two-second delays inside the existing query budget (90 seconds
for legacy polls; up to 30 seconds per source within the durable poll's
120-second deadline). Durable reads retain their per-attempt combined 5 MB
stdout/stderr bound. Failed-attempt output is discarded. Exhaustion remains
`UNVERIFIED`; a partial portfolio never replaces the successful legacy
checkpoint. Durable polls retain their per-source
`UNVERIFIED`/`NOT_ATTEMPTED` semantics. Authentication/rate-limit errors,
subprocess timeouts, malformed JSON and incomplete coverage are not retried.
Other commands never inherit this retry policy.

For historical task reconciliation, prefer small discovery pages followed by
detail queries for the recorded PR numbers. A large `--state all` query that
includes review decisions can time out in GitHub GraphQL. Reducing `--limit`
without checking pagination is not complete coverage. Keep head/review/CI
comparisons separate from discovery, and do not reuse a partial result as a
current verdict. Ad hoc status scripts do not automatically use the monitor's
retry helper.

### Gateway-timeout RCA (2026-11-04)

An ad hoc historical query (`gh pr list --state all --limit 200`, including
`reviewDecision`) returned HTTP 504 from GitHub GraphQL. The local task
reconcile/list commands had succeeded; the request was not the foreground
monitor's open-PR query. Subsequent small open-PR, per-PR detail, and REST
20-item discovery requests succeeded. Rate-limit counters were nearly unused.
These observations support a transient upstream/query failure, not credential
expiry or demonstrated rate exhaustion. They do not establish GitHub's internal
timeout cause or prove that request size alone caused it. The bounded monitor
retry is related resilience work, not a claim that it repairs GitHub or reruns
the failed historical reconciliation automatically.

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

Use [Actionable review output](REVIEW-OUTPUT.md) for human-facing review bodies:
unresolved, severity-ordered findings with verified file:line, trigger, impact,
and a concise fix; retain only material evidence/limits plus brief required AI
attribution and exact-head binding. Never invent unavailable line citations or
present UNVERIFIED required coverage as clean. Omit passing-check inventories,
resolved recaps, and administrative chatter from that outward body only.
Internal orchestrator handoffs still retain complete fixed-head/base bindings,
acceptance and obligation coverage, evidence, limitations, dispositions, status,
and next action. Presentation does not change permissions or acceptance gates.
Install byte-identical profile copies and the packaged guidance, then quit and
restart OpenCode; profiles must carry the essential rules without requiring a
runtime read of the linked document.

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
    Evaluate merge readiness promptly and present the human decision. In
    human-reviewed delivery, bind explicit human approver identity,
    repository/PR identity, exact head SHA, base, method and policy revision.
    A changed head invalidates that authorization; agent booleans, model votes
    and green CI alone cannot authorize merge. Recheck applicable CODEOWNER and
    native rules, CI, threads, draft status, dependencies and acceptance before
    submitting the normal SHA-guarded merge under consumer authority. Auto-merge
    enablement and queue admission also require explicit human decisions.
    PR closure needs its own authorization. Issue closure needs separate
    authorization naming every affected issue, including closing keywords in
    PR descriptions, commits reaching the base and final squash text. Report
    those effects in the human request. A queue entry is not a completed merge;
    check the owning repository for the terminal result. This guide changes no
    native repository review count and grants no activation authority.

### Legacy finding dispositions

Legacy `state record TASK finding TEXT` entries are retained in their original
order. Duplicate finding text is refused. The baseline provided
`record TASK resolution TEXT`, which removed the matching finding string without
retaining a disposition. This change intentionally refuses that destructive
command; migrate callers to `resolve-finding` with the bindings below. Findings
already deleted by the old command cannot be reconstructed from the task record.
Preserve any separately retained review evidence; do not claim this migration
retroactively restores that missing history.
For an implementation or review task in `Reviewing`, record a fixed/refuted disposition:

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

Use `refuted` only with evidence that the finding does not apply. Use the same
exact-bound command with `--disposition persists` and fresh evidence to reopen a
fixed/refuted finding, including at the same head after readiness. It is accepted
in `Reviewing` or `Ready for human review`; an initial `persists` records explicit
unresolved evidence too. Reopening a ready task clears reviewers, validation and
reviewed SHA and moves it to `Rework` (or `Blocked` at the three-cycle limit).
Reclaim the task and return to `Reviewing` before recording a later fixed/refuted
resolution and fresh readiness evidence.

The command requires a nonempty task owner, a distinct reviewer label, and
nonempty evidence. The retained `implementation_owner` field names that task
owner for both kinds; for review tasks it is not a claim about the code author.
Production implementation checks verify assigned branch, head and cleanliness;
review tasks use `verify_review_identity` to verify checkout root, head and
cleanliness, allowing detached HEAD. A stale revision, mismatched finding
index/text digest or missing identity is refused without changing the record.
Within each epoch, another fixed/refuted event requires an intervening `persists`,
and another `persists` requires an intervening fixed/refuted event. Duplicate
outcomes are refused, even with a newer revision. Refresh `show` before each event.

`legacy_finding_dispositions.history` is append-only through the tool, including
the owner, reviewer, evidence, disposition, finding digest/index, head, epoch and
write revision. All findings need a latest current-epoch fixed/refuted disposition before legacy readiness
or readiness recovery can succeed; the existing reviewer, validation, current-SHA
and clean-checkout requirements still apply. `update-head` increments the epoch
on each recorded head change, including A→B→A, preserving old history without
reactivating it. Claiming under a different owner also invalidates dispositions.
Unrecorded external changes are not an observed epoch: always update the recorded
head as work changes. New and reopened findings revoke readiness. The entire
retained history is validated, including event order, alternating outcomes and
epoch/head/owner bindings; counting uses the latest event for each finding in the
current epoch. Present but malformed
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
