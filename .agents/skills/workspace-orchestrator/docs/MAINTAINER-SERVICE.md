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
In a protected-broker stage, workers receive source and bounded task effects,
without controller state, accepted evidence, active policy or GitHub credentials.
A cooperative trusted-host pilot cannot promise that boundary against hostile
same-account code: that account may obtain credentials outside the executor.
Candidate execution still requires independent isolation. Self-maintenance edits
a candidate worktree; installing its trusted controller or policy requires a
separate human decision even after the source PR merges.

Resolve action classes and grant fields from the consuming workspace's canonical
authority, not from this packaged guide. Routine effects within an explicitly
activated scoped grant need no repeated confirmation; adoption of a policy or
command does not activate that grant. Existing per-action approval mechanisms
remain required until separately qualified support and human activation. Admission
may precede a tracking issue only when consumer authority permits that bootstrap;
it never independently grants a write. Labels and model output are not authority.
Retain action, task, publisher, repository, fields/ref, lifetime, revocation,
budget and downstream-effect bindings; preserve authorization-source distinctions
and old evidence when extending the existing coordinator and journal.

In human-reviewed delivery every merge needs an explicit human decision binding
approver identity, repository/PR identity, exact head, base, method and policy
revision. A changed head invalidates it; green CI and agent QA alone never
authorize merge. Auto-merge enablement and queue admission also need explicit
human decisions. Closing issues, including through PR/commit/final-squash closing
keywords, requires separate authorization naming every affected issue. The agent
submits the approved normal SHA-guarded method only after current native rules,
checks, review and acceptance gates pass, then observes the result. Agent booleans
cannot self-authorize or supply independent review. The consumer controls actual
activation; this skill does not export maintainer-repository policy or defaults.

## Rollout and rollback

1. Private review/repair with a frozen positive/adversarial corpus.
2. Consumer-approved policy, then a typed executor reusing coordinator/journal;
   separately qualify each endpoint with refusal and interrupted-dispatch tests.
3. Explicit human activation of a finite cooperative pilot grant; covered routine
   actions are prompt-free, while every merge retains its human decision.
4. Separately promote a protected credential broker under a protected account or
   VM. No worker access to credentials/active policy, token-return endpoint,
   arbitrary URLs, shell or GraphQL. Token permissions alone cannot fence merges;
   enforce typed endpoints/refs and native rules. App setup is human-controlled.
5. Broaden consumer scope only through separately approved qualification and grants.

Until implemented and qualified, service commands, remote transports and
migration are unavailable. Do not advertise them from this decision document.
Keep the installed controller pinned while candidate tests run. Additive source
packet tooling does not migrate existing task JSON. A future state migration
requires quiescence, private backup/manifest, dry-run validation and a rollback
that preserves evidence written after migration; checking out older code is
insufficient.

Expiry/revocation stops new dispatch, never observation or preservation of issued
work. Retain UNKNOWN history and target fences; current desired-state satisfaction
does not prove historical completion. Do not replay unknown creates/comments/merges
or clear reservations by timeout. Any future capacity release requires qualified
producer containment and action-specific reconciliation. Fresh body/ETag comparison
detects drift but provides no atomic unsafe-write guarantee against concurrent
human edits. Endpoint fixtures and an explicit consumer grant remain necessary;
documentation tests cannot prove enforcement.

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
