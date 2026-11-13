# Repository Setup

Apply and verify these settings after the bootstrap push.

## Repository

- Visibility is **internal**.
- Default branch is `main`.
- Issues are enabled. Wiki, discussions and projects are disabled initially.
- Squash merge and auto-merge are enabled.
- Merge commits and rebase merges are disabled.
- Head branches are deleted after merge.
- The issue template routes security reporters to the project mailbox for an
  approved private GSA channel. Do not claim GitHub private vulnerability
  reporting for this internal repository.

## Access

- `@wz-gsa` is the bootstrap administrator and CODEOWNER.
- Do not add direct collaborators without a documented need.
- Move ownership to a visible organization team only after it has explicit
  repository access and confirmed maintainers.

## Default-Branch Rules

Protect `main` with a ruleset that:

- blocks deletion and force pushes;
- requires pull requests and linear history;
- during the operator-authorized solo-maintainer phase, requires zero approving
  reviews and does not require CODEOWNER or extra unattributed-change approval;
- dismisses stale approvals after a new commit;
- requires review conversations to be resolved;
- requires the `Repository checks` status check with strict branch freshness;
- permits squash merges only; and
- records any administrator bypass in the repository audit trail.

### Temporary Solo-Maintainer Review

The operator authorized the temporary approval settings on 2026-11-05 for this
repository only. Review is enforced by the maintainer workflow rather than a
GitHub approval count: inspect the exact head, obtain independent agent QA
evidence, and verify green required CI and resolved threads. The additional
[human merge decision](SCOPED-AUTONOMY.md) must identify the approver,
repository/PR, exact head SHA, target base branch, merge method and applicable
policy revision before an agent submits the normal SHA-guarded squash merge.
A changed head requires renewed authorization. Neither zero required GitHub
approvals nor agent review evidence substitutes for this human decision. These
workflow requirements do not change the native zero-review setting.
Administrator bypass is not part of this workflow.

Before collaborative development, restore these pull-request parameters on
the `Protect main` ruleset:

- `required_approving_review_count`: `1`;
- `require_code_owner_review`: `true`;
- `require_extra_approval_for_unattributed_changes`: `true`.

Reinspect the live ruleset before updating it; preserve unrelated changes.
Verify effective default-branch rules and a collaborator's applicable CODEOWNER
access after restoration. Keep PRs, strict required checks, resolved threads,
squash-only integration, linear history, deletion and force-push protections
throughout both phases. The host-local `.orchestrator/solo-maintainer-rules/`
contains the original update payload and recovery notes; those runtime records
are not a substitute for checking live settings.

## Actions And Security

- GitHub Actions is enabled.
- Allowed actions are restricted to GitHub-owned actions where organization
  policy permits; any exception receives explicit review.
- Full-length commit SHA pinning is required for actions.
- Default workflow permissions are read-only.
- GitHub Actions cannot create or approve pull requests.
- Secret scanning, push protection and validity checks are enabled where
  available.
- Dependabot alerts and security updates are enabled.
- Verify the first hosted CI run downloads the pinned Gitleaks archive, checks
  its SHA-256 and completes the repository scan.

CI runs syntax checks and the foreground delivery and handoff suites in one
15-minute job and syntax checks, the remaining tests, inventory checks, core
quality checks and Gitleaks in a second 15-minute job. Each has its own checkout
and pinned Python 3.12.15.
The required `Repository checks` job always evaluates both results without a
checkout and succeeds only when both are exactly `success`; failed, skipped,
cancelled or missing results cannot pass. Keep the existing required-check name
and ruleset. Measure both jobs' actual hosted runtimes after changes.

Local `make check` and `make strict-check` still run all suites, with foreground
tests exactly once. `make test-foreground` and `make check-rest` are the explicit
CI partitions. Both depend on `check-syntax`, as do `make test` and
`make test-rest`: Python, shell and JSON syntax checks finish before behavioral
tests even with `make -j`. Use `make check-syntax` for the fast development pass
inside the workspace sandbox. The shared prerequisite runs once per make
invocation; local test partitions remain serialized. `check-rest` includes the
remaining tests followed by the same `check-static` integrity and scanner checks
used after the complete local suite.

## Retirement

Archive the repository by default. Transfer or deletion must use applicable
GSA administration and records processes.
