# Maintainer service decision

Status: proposed implementation; remote capabilities inactive.

Current delivery direction: automated GitHub App activation and automated review
publication are parked. Continue bounded native OpenCode implementation and
QA/security review, delivering main-based PRs under existing authority for human
approval. See `OPERATOR-GUIDE.md` and the consuming workspace's delivery runbook.
The future service stages below are not prerequisites for that work and do not
claim an activated runtime or remote permission.

## Outcome and boundary

Extend the existing coordinator with evidence-bound review and owner-directed
repair, then durable reconciliation and separately authorized GitHub effects.
The first release must demonstrate an installed harness reading real source,
an independently checked repair, and current-revision re-review. Protocol tests
alone do not qualify that release.

Task JSON remains the ownership and lifecycle authority. A later SQLite journal
records observations, intents, receipts and scheduling; it must not duplicate
task states. Before using that journal, authoritative mutations must atomically
retain operation ID, canonical request digest and result. Identical retries
return that result; conflicting reuse is refused. Expected revision alone does
not establish whether a lost-response mutation happened.

An assignment binds an immutable admission/comparison generation. Acceptance
also checks the current task revision under the coordinator lock. Recording one
review must not invalidate another applicable assignment; material changes to
source, policy, required context or obligations invalidate the generation.

## First boundary: source and review

Capture committed Git objects without executing checkout code, hooks, filters,
external diffs or text conversion. Preserve exact base/head semantics and a full
changed-file inventory. Binary blobs, symlinks and gitlinks are explicit review
limitations. Unchanged context must be selected at the same revisions; adding it
produces a new immutable packet. Complete change capture does not mean sufficient
review context.

Trusted installed policy requires correctness, acceptance, test adequacy,
maintainability and baseline security. Models may add specialist coverage, never
remove mandatory obligations. A worker's report is a submitted claim; a digest
establishes identity, not whether the worker read source or a test ran.

Accept bounded staged evidence into controller storage before atomically
referencing it from authoritative state. An interrupted publication may leave an
unreferenced object, which grants no readiness. Missing referenced evidence is
UNVERIFIED. Findings and dispositions remain append-only; a new head requires
current evidence and cannot erase the original finding or reset task budgets.

## Execution and authority

Use a qualified OpenCode/acq adapter for real workers and an explicitly fake
adapter for deterministic protocol tests. Probe actual start, observation,
collection and cancellation capabilities before claiming them. Session slot
accounting is distinct from independent process identity and termination proof.
Workers receive source and bounded task effects, without controller state,
accepted evidence, active policy or GitHub credentials. Candidate instructions
cannot redefine that external boundary. Self-maintenance edits a candidate
worktree and requires independent promotion of the installed controller.

Capabilities are independent: observe, admit, publish review, push owned branch,
open PR, create issue, edit designated metadata, link dependencies, approve,
integrate, and close a verified delivered issue. Routine effects within explicit
standing authority need no repeated confirmation. Labels and model output do
not grant authority. Sensitive policy, identity, isolation, CI and verifier
changes retain their independent human/governance gate.

The executor uses scoped GitHub App installation credentials and current native
rules. It cannot self-approve, bypass CODEOWNERS, force-push or manufacture an
independent reviewer. An enabled automated integration lane additionally needs a
required eligibility check bound to the designated App. Submission, approval,
queue admission, merge and downstream delivery are separate observations.

## Rollout and rollback

1. Private review/repair with a frozen positive/adversarial corpus.
2. Durable PR observation and separately enabled current-head publication.
3. Qualified current-policy integration and bounded grooming.
4. Explicitly activated eligible autonomous-delivery class.
5. Two-repository consumer delivery, including partial release/pin recovery.

Until implemented and qualified, service commands, remote transports and
migration are unavailable. Do not advertise them from this decision document.
Keep the installed controller pinned while candidate tests run. Additive source
packet tooling does not migrate existing task JSON. A future state migration
requires quiescence, private backup/manifest, dry-run validation and a rollback
that preserves evidence written after migration; checking out older code is
insufficient.

## Rejected alternatives

- A second supervisor would duplicate admission and recovery ownership.
- Model-generated shell/API commands would bypass typed effect authorization.
- Mutable task strings cannot establish immutable review or execution evidence.
- Always refusing integration would fail the required positive delivery path.
- Broad worker filesystem access would make controller-owned evidence mutable.

## Acceptance accounting

Report implemented interfaces, qualified runtime behavior, activated permission
scope and measured outcomes separately. Unknown, aborted and unfinished work
remains in the denominator. No unauthorized effect, false current readiness,
lost work or substituted evidence is acceptable in a pilot.
