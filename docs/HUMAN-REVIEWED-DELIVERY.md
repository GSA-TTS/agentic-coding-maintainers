# Human-reviewed delivery

## Current operating direction

Deliver multiple small, green PRs for human approval. Automated GitHub App
activation and automated review publication are parked. They are not prerequisites
for this workflow. Existing service/qualification documents describe bounded
interfaces or future capabilities; they do not establish an active service.

Use the installed `/orchestrate-start` command with a bounded delivery scope.
Its canonical source is
`.agents/skills/workspace-orchestrator/examples/commands/orchestrate-start.md`;
`.opencode/commands/orchestrate-start.md` is the byte-identical installed copy.
Follow the skill's [operator guide](../.agents/skills/workspace-orchestrator/docs/OPERATOR-GUIDE.md)
for state, ownership and recovery. Quit and restart OpenCode after command
changes; an existing session retains its loaded configuration.

## Authority and continuity

Reconcile task ownership, worktrees and live GitHub before resuming. Record the
operator's delivery scope and applicable standing authority, including repository,
branch and allowed effects. Continue admitted work and select further bounded
tasks inside that scope without asking the human to choose every task again.
Routine actions already covered by standing authority need no repeated prompt.

Authority is action-specific: permission to push does not imply permission to
open a PR, publish a review or merge. Follow `AGENTS.md` and any narrower current
instructions. Ask when an intended effect lacks authority or scope/ownership is
ambiguous; do not turn that question into a stop for unrelated authorized work.
Parked automated review publication stays inactive even where a broader standing
grant would otherwise permit submitted reviews. The human performs approval;
native agent reviews remain evidence, not a substitute for a required independent
CODEOWNER. Never self-approve or bypass repository rules.

## Batches and dependency order

For each task record acceptance criteria, owner, owned/restricted paths, worktree,
branch, exact base SHA, prerequisite tasks/PRs, review obligations and next action.
Check semantic overlap, including changes to the same behavior in different files.

- Start independent tasks from verified current `main` (or the owning
  repository's default branch). Each PR targets that branch, not another task's
  branch. Auto-deletion of a merged branch must not strand a dependent PR base.
- Express integration order explicitly. For example: A and B are independent
  main-based PRs; C depends on A and starts only after A's observed merge and a
  refresh of main. B can proceed while A awaits approval. Cross-repo prerequisites
  may also require a verified release/pin before the dependent task is ready.
- Do not pre-build C by stacking it on A. If a dependency appears mid-task,
  preserve work, record the blocker and reconcile with its owner. After the
  prerequisite lands, integrate onto current main through the authorized normal
  Git workflow and rerun applicable validation/review for the changed head.
- Serialize shared interfaces, manifests, lockfiles, generated artifacts and Git
  ref/config operations. Recheck independence after each merge; main-based PRs
  can still conflict semantically.

## Native execution and review capacity

Claim through the installed state tool before dispatching each native OpenCode
worker. Keep at most **6 active workers**, **2 implementation lanes**, and reserve
**2 slots for QA/security**. Monitors, specialists and nested workers count toward
the six. A reservation may be used by its reviewer; it is not extra capacity.
Reduce new implementation starts when review queues grow. Release finished
workers through the state lifecycle after reconciling their outcome; a PR waiting
for a human does not require an idle worker.

Use actual independent task dispatch for parallel implementation and review.
Record task/session IDs, assigned scope, exact base/head, result and coverage.
Every implementation receives independent QA and baseline security review.
Trust-boundary changes additionally require an independent security reviewer.
Use available specialists for concrete gaps such as documentation accuracy,
dependency behavior or domain correctness, with the same slot and evidence rules.
Do not invent an installed role or count one agent's role-labelled prose as fanout.
Unavailable or prohibited dispatch leaves that coverage `UNVERIFIED`.

Reviewers inspect actual fixed-SHA source in a separate read-only checkout, not
only an implementer's summary. Objective findings return to the owner, with
severity, source location, impact and concrete correction. Retain the finding and
its evidenced fixed/refuted/persists disposition. Fix objective defects and
re-review every material new head; previous clean results cannot transfer
silently. Escalate after three unsuccessful substantive rework cycles while
independent lanes continue.

## Evidence and human handoff

Run candidate tests, builds and installs only through an approved isolated
environment. Worktrees do not provide that boundary. Record the actual command,
environment, head and observed result. Run required repository checks (including
`make check` here) before requesting review. If execution is blocked, preserve
that limitation rather than marking the check passed.

For every delivered PR provide:

- PR URL, owning repo, default-branch base and exact reviewed head;
- scope/acceptance result and integration order, including unmet prerequisites;
- actual QA/security/specialist assignments, findings and current-head coverage;
- validation transcripts and current required-check results;
- remaining human approval or repository gates, their owner and next action;
- PR-level AI disclosure under the applicable publication authority.

`Ready for human review` requires completed applicable validation and review at
the recorded head, with no unresolved Blocker or Should-fix finding. A draft or
blocked PR can be shared when authorized, but must not be described as green or
ready. Failed, absent, skipped, pending or inaccessible required checks are not
passing. Static checks, protocol fixtures and a running process do not prove
runtime fanout or whole-candidate readiness.

Recheck live head, checks and review state before any authorized remote action.
After human approval, evaluate dependency, CODEOWNER, thread, draft and merge
rules promptly. Merge only under applicable authority at the approved head;
approval alone does not grant a new merge capability. Observe the actual remote
result. Approval, queue entry, merge and downstream delivery remain distinct.
Continue independent batches while the human reviews prior PRs, retaining honest
blocked/UNVERIFIED states and foreground-only monitoring claims.
