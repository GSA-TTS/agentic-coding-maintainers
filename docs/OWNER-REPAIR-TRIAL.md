# Bounded owner repair trial — 2026-10-29

AI-assisted continuation after PR80 merged at
`3a386713d879d64f6b6df48bd6b7b87f60054657`.

## Implemented behavior

Prepared corrections retain the original owner, source/scope, findings, cycle,
generation and epoch before the owner reclaims rework. The replacement transport
accepts at most two existing ordinary files, retains exact bounded bytes and
preconditions, persists APPLYING and review invalidation before writing, and
verifies results without executing candidate code. Per-file replacement is
atomic; interruption may leave a partial bundle and retains the repair fence.

Exact replay performs no writes. Reconciliation only observes pending current
operations; settled history is immutable. Existing unresolved findings remain
until new-head independent review. Repair application does not commit, execute,
approve or grant readiness. The running controller/state and protected agent/
Git/CI policy paths remain outside this ordinary-file transport.

## Actual isolated VM trial

The operator authorized fresh fixture worktrees inside the Ubuntu Multipass VM.
The actual CLI performed review begin/claim retention, Rework admission,
correction preparation, original-owner claim, two-file replacement, replay and
head update. Candidate assertions executed only inside the VM.

The first trial was refused because its implementation checkout was outside
`work/`; a second was refused before mutation because default VM file modes were
0664 instead of the transport's allowed0600/0644. A fresh correctly provisioned
third fixture then observed:

```text
before assertion: exit1, assert double(3) == 6 failed
different owner: refused
apply: APPLIED_UNREVIEWED
exact replay: unchanged task state and no additional writes
after assertions: exit0 for positive, negative and zero input
old head: 9fa1af606a92f20f51f3ff6e24a2ad6fb7073d73
new head: d82289d14583155d2dab8a0f92726d53d3aa84c0
new-generation claim assessment: CLAIMS_COMPLETE, no unresolved findings
candidate_ready/execution_credit/delivery_credit: false
```

Review and re-review claims in this trial were explicitly fixture-driven, not
live model judgments. The test execution, filesystem mutation, CLI admission,
new commit and replay were actual observations. The host's installed controller
was not replaced or granted authority. No network/provider call or remote write
was involved in the trial.

## Independent review and corrections

Parallel architecture/security analysis preceded implementation. Parallel
fixed-revision QA/security reviewed `23ddede44463f7f4de50429b448b4b3c5d556a4a`:
scope case aliases, unprotected root OpenCode configs, missing-artifact guards,
and mutable settled reconciliation were found. Repairs were re-reviewed at
`77cb3625c2d217ac43718437fa1c6f17f2f0fc4f`.

That re-review found late reports could invalidate a prepared historical
correction, and case-folded ownership could broaden authority on case-sensitive
filesystems. The final correction freezes same-generation assignment/report
changes after preparation, uses exact ownership matching, and conservatively
case-folds only restrictions. Regression tests cover these paths.

## Validation and remaining scope

Thirteen targeted repair tests pass, plus the18 legacy evidence tests. Tests
cover full public rework lifecycle, original-owner refusal, two-file replacement,
no-write precondition failure, pre-intent persistence failure, partial interruption,
lost final receipt recovery, protected paths/hardlinks/symlinks, artifact loss,
immutable historical reconciliation, pending terminal refusal, late evidence
refusal and review after the third allowed repair. Static Ruff/Pyright/Bandit
passed. Full Docker repository checks passed before review-driven corrections;
final full verification is required before publication.

This is a bounded data-application transport under cooperative exclusive
ownership, not an OS sandbox against a hostile same-user writer. General patch
generation, protected self-maintenance mutation, unattended whole workflow,
durable PR monitoring and GitHub effects remain subsequent work. No readiness,
App/rules/merge authority or controller promotion is activated.
