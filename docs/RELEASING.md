# Release lifecycle

## Scope and bootstrap

This repository versions the maintainer workspace source as one unit. The first
intended release is **v0.1.0**, not a stable 1.0 promise. At task admission the
repository had no tags or releases; verify live state again before activation.
Do not fabricate historical releases from the unversioned changelog summary.

Release Please uses manifest mode and the `simple` strategy. The empty
`.release-please-manifest.json` means no release has been recorded. `version.txt`
contains **0.0.0 as a bootstrap sentinel only**, not a release or a compatibility
claim. `initial-version: 0.1.0` selects the first release in the absence of a
previous release. The bot should propose `version.txt`, the manifest's `.` entry
and the changelog together. Inspect that first PR for exactly 0.1.0 before merge.
Do not seed the manifest with 0.1.0 or add persistent `release-as`: either would
misrepresent bootstrap state or interfere with later automatic bumps.

The workflow maintains a release PR on `main`; after a human merges a reviewed
release PR, it records the corresponding tag and GitHub release. It does not
auto-merge, publish packages, build a VM/kit, or produce signed artifacts.

## Compatibility and version selection

The public contract covers documented CLI commands/flags and exit meanings,
consumer configuration and schemas, persisted task/state formats and recovery
semantics, evidence formats/verification meaning, and adapter interfaces. A
same-numbered schema does not guarantee semantic compatibility. Breaking state
or evidence changes need migration/rollback notes; never silently reinterpret
old evidence as new verification. Undocumented implementation details are not
a stable API, but changes to security or authorization behavior still need review.

Before 1.0, the explicit Release Please settings are:

| Change | Commit/title signal | Bump after bootstrap |
|---|---|---|
| Incompatible public-contract change | `feat!:` / `fix(scope)!:` or `BREAKING CHANGE:` footer | Minor (`bump-minor-pre-major: true`) |
| Compatible feature | `feat:` | Minor (`bump-patch-for-minor-pre-major: false`) |
| Bug fix or performance fix | `fix:` / `perf:` | Patch |

The highest applicable bump wins. Document a breaking change and its migration
in the PR body, and ensure the marker survives the final squash commit. Review
the actual squash title/body, not just the branch's individual commits. After
1.0, normal SemVer breaking-major behavior applies; selecting 1.0 itself requires
a separate explicit stability decision and reviewed release change.

The title check accepts `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
`build`, `ci`, `chore`, and `revert`, with optional scope and `!`. A valid title is
not necessarily release-triggering: Release Please defaults ordinarily need
`feat`, `fix`, or `perf` (or a recognized breaking change). Docs/chore-only work
may leave no release PR, including during bootstrap. Do not mislabel work to
force a release. The bot's `chore(main): release 0.1.0` title is valid; it is not
itself a new feature. Confirm the generated changelog and included commits rather
than assuming every accepted type appears in the default changelog.

## Explicit operator activation

Release generation is disabled unless the repository Actions variable
`RELEASE_PLEASE_ENABLED` compares equal to `true` (GitHub expression string
comparison is case-insensitive; operators should use lowercase `true`). Both main pushes and
manual Release dispatches use that gate; dispatch on another ref is refused by
the job's `refs/heads/main` guard. Top-level permissions are empty; only the release
job receives `contents: write` and `pull-requests: write`. Runs serialize without
cancelling a running release operation. The action is pinned to the reviewed full
SHA for v5.0.0; there is no checkout or candidate-code execution in this workflow.

The admission-time repository setting was
`can_approve_pull_request_reviews=false`. Before enabling the variable, an
authorized operator must explicitly review and enable **Allow GitHub Actions to
create and approve pull requests** under repository Settings → Actions → General
(subject to organization policy), and verify the resulting setting. This is
needed for bot PR creation; it does not authorize bot self-approval, relax review
requirements, or grant authority to merge. If organization policy refuses it,
leave the release gate disabled and report the blocker. This change neither
writes repository settings nor introduces a GitHub App or PAT.

After verifying settings, branch protections, token policy and absence of
conflicting tags/release PRs, explicitly set `RELEASE_PLEASE_ENABLED=true` and
dispatch **Release** from `main` (or use the next main push). Inspect the run and
proposed version. An absent variable or a value other than `true` (ignoring case)
safely skips generation.

## GITHUB_TOKEN and manual CI

The bot uses only `GITHUB_TOKEN`. Its PR creation and updates normally do **not**
trigger other Actions workflows. A release PR with missing checks is not ready
to merge. The existing CI workflow has no `workflow_dispatch`; do not attempt to
dispatch it or invent a successful CI run from the release job.

For each final bot PR head:

1. Confirm the current head, target `main`, release diff and expected version.
   Wait for any in-flight release update to finish.
2. With explicit operator authorization for these PR actions, a **human** closes
   and reopens the bot PR. The human `pull_request: reopened` event starts normal
   CI and the metadata-only title check. If the PR is already closed, reopen it;
   if current-head checks already exist and pass, do not cycle it unnecessarily.
   Repeating this route does not create a new release or a duplicate release PR.
3. Verify that required checks actually ran for the current head. Bot updates
   require fresh current-head checks; rerun this route when necessary. Do not
   treat old green runs as current-head evidence.
4. Obtain exact-head review evidence under the applicable repository policy.
   Close/reopen and subsequent pushes may dismiss/reset reviews under repository
   rules; recheck them and renew review when required. Resolve threads and verify
   all merge gates. A human performs the normal head-guarded merge, never bypass.
5. Inspect the subsequent main-push Release run and verify the tag, release,
   manifest, version file and changelog agree with the merged release commit.
   Record actual results, not just the action's intent.

Manual dispatch of **Release** on main is the retry route for interrupted release
generation. Reconcile existing bot PRs/tags/releases first; let Release Please
reconcile rather than hand-creating duplicate PRs or deleting tags. Never move a
published tag. For a wrong published release, preserve history and review a
follow-up fix/release. To pause generation, disable the activation variable;
this does not cancel an already-running job or undo remote writes.

## Validation and consumers

Run `python3 -I -B tests/release-config-test.py`, `make check`, and
`pre-commit run --all-files` only inside an independently justified workspace
sandbox with the reviewed tools available. The release test checks JSON/mode
invariants, literal workflow safety constraints and synthetic title events. It
does not run Release Please, verify remote settings/tags, or prove GitHub event
delivery. First activation and the human reopen route need live operator evidence.

Consumers and future kits must pin an immutable **full commit SHA**, retaining
source provenance and verifying installed bytes/modes. A release tag is a human
discovery aid, not a substitute for an immutable consumed pin. Signed/provenance
distribution artifacts, their verification procedure and package publishing are
deferred until actually produced and reviewed. See [the MSB workspace plan](MSB-WORKSPACE-PLAN.md)
for deployment acceptance; a source release alone does not qualify any sandbox
backend or harness.
