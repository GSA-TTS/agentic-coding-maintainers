# Scoped autonomy contract

## Status and authority

This is the policy slice tracked by
[issue 66](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/66).
It specifies future scoped standing authority; it installs no controller, grants
no credentials and activates no grant. Integration and activation remain separate
work under [issue 70](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/70)
and [issue 75](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/75).
The operator approved this design and its pilot defaults on 2026-11-10; an actual
grant still requires a separate human activation through the trusted controller
channel. This policy PR itself requires human approval of its exact merge head.

Every merge requires an explicit human decision, superseding this repository's
former solo-agent-review-only merge exception. GitHub's temporary zero-review
setting is not merge authority. Existing commit, normal task-branch push and
fixed-head review permissions in [AGENTS.md](../AGENTS.md) continue within their
admitted scope and narrower steering. Until separately qualified grant support
is activated, other writes retain their existing per-action approval rules,
including the [publisher's controlling-terminal approval](CLAIM-PUBLISHER-PROTOCOL.md).
A document, issue, task admission, model vote or agent-written boolean cannot
activate authority or substitute for a human decision.

## Canonical action matrix

This is the single maintainer action matrix. Delivery guidance and commands refer
to it through consumer authority. `SCOPED` means prompt-free only under a current,
activated grant covering the exact task, fields and effects; it is not permission
from this document. `HUMAN` requires a separate explicit human decision. `REFUSE`
is unavailable through the routine workflow, even if requested by candidate text.

| Action ID | Class | Exact scope or decision |
| --- | --- | --- |
| read-admit | SCOPED | Read/research and admit bounded tasks under the objective; admission grants no remote write. |
| issue-create | SCOPED | Create deduplicated tracking issues from admitted intake tasks, including bootstrap `tracker: none`; retain returned immutable identity. |
| issue-edit | SCOPED | Edit explicitly agent-owned issue text with retained/fresh content comparison; detected human drift stops the write. |
| labels-add | SCOPED | Add existing allowlisted labels only, including their workflow and cost effects. |
| assignees-add | SCOPED | Add explicitly allowlisted assignee IDs, preserving existing assignees and checking assignability. |
| status-update | SCOPED | Update a known agent-owned status comment by immutable ID with drift checks; no general comment-edit permission. |
| branch-push | SCOPED | Create the admitted task branch; edit, commit and normally push only its owned paths and ref. Existing standing authority still applies. |
| isolated-check | SCOPED | Run approved isolated checks with their allowed network, execution and cost boundaries. |
| pr-publish | SCOPED | Create/update the task-owned PR under current description guidance; preserve human text and credits and check closure side effects. |
| review-publish | SCOPED | Publish actual fixed-head findings with current evidence; an agent review is not human approval. Parked capability needs separate activation. |
| merge | HUMAN | Human approves exact repository/PR, head, base, method and policy revision; agent submits a guarded normal merge after all gates. |
| auto-merge | HUMAN | Enabling auto-merge needs its own explicit decision; no inherited merge authority. Deferred from the first delivery. |
| queue | HUMAN | Queue admission needs its own explicit decision; no inherited merge authority. Deferred from the first delivery. |
| policy-install | HUMAN | Change active policy, trusted controller, credentials, rules or permissions, including installation after a source PR merges. |
| human-overwrite | HUMAN | Overwrite human edits only under a decision covering the specific change; otherwise stop on conflict. |
| issue-lifecycle | HUMAN | Close/reopen each named issue, including indirect closing keywords and cross-repository effects. |
| assignees-remove | HUMAN | Remove an assignee only under a specific decision; additive authority never implies removal. |
| delete | HUMAN | Delete comments or branches only under a specific decision, including configured post-merge deletion effects. |
| pr-close | HUMAN | Close a PR without merge only under its own explicit authorization. |
| release-deploy | HUMAN | Publish releases/packages, deploy or invoke privileged workflows only under separate authority. |
| force-protected-foreign | REFUSE | No force-push, protected-ref write or alteration of another owner's branch through the routine workflow. |
| self-approve-bypass | REFUSE | No self-approval, fabricated independent review, review dismissal or administrator bypass of an unmet gate. |

Routine security-code changes may be proposed within an owned branch and receive
independent review. Installing their trusted controller, policy or credential
arrangement still requires a human decision after the source PR merges.

## Structured grant contract

The following field groups define the required future grant record, not an input
format accepted by existing tools. The synthetic fixture is documentation only.
Missing, unknown, conflicting or unverified authority refuses new effects. A
task narrows a grant; it cannot expand it or select a more permissive revision.

| Field group | Required binding |
| --- | --- |
| identity | Unique grant ID, immutable policy revision/digest, human activator identity and trusted-channel activation evidence; never a caller-supplied `approved: true`. |
| target | Immutable repository ID, fixed API origin and verified publisher immutable identity; names alone are insufficient. |
| objective | One named objective, exclusions and admitted task identity/incarnation, owner, session/generation and current revision. |
| scope | Explicit action IDs, fields, owned paths, task branch prefix/ref, existing label names and assignee IDs; downstream workflow/cost effects included. |
| lifetime | Activation and expiry timestamps, revocation/renewal authority and current revocation state; human-controlled selection of the active revision. |
| budgets | Durable grant-wide counters/reservations for issues, metadata, unresolved attempts and worker/lane limits; no reset on restart or new operation ID. |
| evidence | Exact request/payload digest, operation/attempt identity, task fences, public-text constraints and retained authorization source `STANDING_GRANT`. |

Approved design defaults for the first pilot are repository ID **1422648445**
(`GSA-TTS/agentic-coding-maintainers`), fixed `https://api.github.com`, one verified
publisher and one finite objective excluding live administration, releases and
deployments. The separately activated grant must name its actual publisher,
branch prefix, paths, labels, assignees and workflow/cost scope. Defaults are:

- At most **2 implementation lanes** and **6 total workers**, reviewers included.
- At most **5 new issues** and **20 remote metadata mutations per UTC day**;
  issue creation consumes both counters. Reserve before dispatch; uncertain
  effects remain charged. Counters and reservations survive restart.
- At most **1 unresolved mutating attempt per target** and **3 new unresolved
  attempts per grant** before pausing new remote mutations. Resolving a target
  does not reset the grant's cumulative unresolved-attempt budget.
- A **24-hour grant**, renewed or revoked only by an explicit human action.
  Expiry/revocation stops new dispatch, not observation, durable settlement or
  preservation of already-issued work; it never clears an uncertain effect.
- Public text contains only task-relevant repository/code facts and synthetic
  fixtures, with no credentials, host inventory, private state or sensitive prose.

## Dispatch and conflict rules

Every future effect rechecks the current grant, admitted task and fresh remote
identity/permissions, narrows to exact fields/ref, and durably reserves the budget
and target fence before dispatch. Unsupported endpoints remain disabled. Reuse
the existing coordinator and journal through one typed executor; do not fabricate
TTY evidence for `STANDING_GRANT` authorization or rewrite old journal rows.

Issue creation bootstraps from an owned intake task with `tracker: none`. Deduplicate
against current owning-repository work, record intent, then create and retain the
returned repository/issue IDs. Only afterward admit implementation against the
issue. An uncertain create pauses for reconciliation, never blind retry with a
new operation ID. An issue required for governance is not an impossible
prerequisite to admitting this narrow issue-creation task.

GitHub generally lacks conditional unsafe writes. Comparing retained content and
a fresh body/ETag detects some drift; it is not atomic compare-and-swap or a
distributed lock. Prefer dedicated agent-owned objects and stop on detected
conflict. If the residual concurrent-edit race is unacceptable, use a separately
authorized additive comment or request a human decision. Grant scope includes
workflow triggers and cost from labels, issue events and pushes, not just API calls.

Keep historical completion, current desired-state satisfaction, producer state and
acceptance separate. A GET can show satisfaction without proving an earlier write.
Unknown creates/comments/merges are not automatically replayed; new IDs do not
make duplicates safe. A future supervised containment path may release capacity
only after proving the original producer cannot dispatch again, preserving UNKNOWN
history and conflicting target fences until action-specific reconciliation. Killing
a local process cannot retract an issued remote request.

Existing #154 evidence and pending reservation remain unchanged and UNKNOWN.
Existing #158 remains paused; its manual-pilot approval is not a standing grant.
Neither record is migrated, released or reinterpreted by this policy. Any new
pilot requires fresh admission and its own activated grant.

## Human merge decision and closure

Present one compact request with human approver identity, immutable repository
and PR identity, exact full head SHA, base branch, permitted method and policy
revision, plus current CI/review/acceptance evidence and every closure/deletion
effect. Retain the explicit human decision through the trusted channel. A review
or “looks good” without this scope is insufficient merge authorization. An
agent-set approval flag or an unverifiable model vote cannot self-authorize.

Immediately before submission, recheck head, base, current policy/decision,
required checks, independent fixed-head QA/security, applicable CODEOWNER and
repository rules, resolved threads, draft status, dependencies and acceptance.
A changed head invalidates human authorization, even if CI is green; obtain a
new decision and current-head review. One decision never approves a stack or a
later revision. Green CI plus agent QA without a human decision produces zero
merges. The agent submits only the permitted normal SHA-guarded method and
observes the remote outcome; approval, submission, queue entry and merge differ.
An uncertain merge is reconciled, not blindly resubmitted. Auto-merge and queue
enablement are distinct human decisions and are deferred from the first delivery.

Merge approval alone does not authorize issue closure. Require separate explicit
authorization naming **every affected issue**, including cross-repository targets,
before including closing keywords. Inspect PR descriptions and all commit text
reaching the base, including the final squash message. Use neutral references
unless closure is authorized; report closure effects in the merge request. A
closing keyword in commit text is as consequential as one in a PR body.

## Staged delivery and rollback

1. Adopt this policy with exact-head human merge approval. No grant activates.
2. Implement and review one typed executor on the existing coordinator/journal.
   Stage 1 is cooperative automation on the trusted host: the same host account
   can obtain credentials outside it. File permissions and prompts do not protect
   against arbitrary hostile same-account code. Candidate execution remains in
   independently justified isolation. Do not claim a worktree is a sandbox.
3. Qualify each endpoint with real executor refusal/crash fixtures before enabling
   it: wrong repository/field, exhausted budget, expiry/revocation, changed head,
   duplicate operation, disk failure and interrupted dispatch. Policy fixtures
   alone cannot qualify this behavior. Under a separate one-use pilot grant,
   qualify one issue creation and additive assignment on a fresh synthetic target;
   then qualify the remaining workflow without a general metadata switch.
4. Human activates a finite objective grant. Covered routine actions proceed
   without further prompts: intake → issue → implementation → isolated checks →
   normal push → PR using [description guidance](PR-DESCRIPTIONS.md) → fixed-head
   QA/security and CI → exact-head human decision → guarded merge. Report
   executed, observed, failed and unknown distinctly; stop on a mandatory failure.
5. Later, independently promote a protected broker under a separate service/account
   or VM with selected-repository GitHub App credentials. Workers cannot access
   credentials or active policy; expose no token-return, arbitrary URL, shell or
   GraphQL endpoint. Contents-write can also permit merge, so typed endpoint/ref
   enforcement and native rules must complement token permissions. App setup and
   trusted-controller installation remain human-controlled.

Revoke or let the grant expire to stop new dispatch; retain the journal, pending
reservations, counters and dirty work for reconciliation. Rolling back source or
checking out an older controller never erases evidence or activates an older
grant. Validation caching and merge queues are outside this first delivery. Run
the required strict suite once when it already includes `make check`; required
hooks and hosted CI remain intact pending separately reviewed receipt reuse.

## Offline contract coverage

[Synthetic fixtures](../tests/fixtures/scoped-autonomy/README.md) check this
matrix, required field groups, scenario-to-rule references, consumer separation
and command-copy parity. They are not a grant resolver, executor, authentication
test or evidence of live enforcement. Behavioral qualification belongs to the
actual executor; structural passing results cannot authorize any effect.
