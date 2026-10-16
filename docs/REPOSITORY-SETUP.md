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
- requires one approval and applicable CODEOWNER review;
- dismisses stale approvals after a new commit;
- requires review conversations to be resolved;
- requires the `Repository checks` status check;
- permits squash merges only; and
- records any administrator bypass in the repository audit trail.

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

## Retirement

Archive the repository by default. Transfer or deletion must use applicable
GSA administration and records processes.
