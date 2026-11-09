# Contributing

## Before You Start

- Open an issue for material behavior or governance changes.
- Do not include secrets, sensitive state, private infrastructure details, or
  unposted issue drafts. Maintainer runbooks, run journals, and orchestration
  records for the agentic-coding repositories are in scope and welcome.
- Preserve the provenance of imported tools and runbooks.

## Make A Change

1. Create a focused branch.
2. Make the smallest correct change.
3. Add or update offline fixtures for behavior changes.
4. Run `make check`.
5. Install the versions in `tools/precommit-versions.json` and run
   `pre-commit run --all-files` (it invokes the strict suite). If the workstation
   already uses a managed global `core.hooksPath`, do not replace it with
   `pre-commit install`; integrate the command into that managed hook instead.
6. Use a Conventional Commit message and PR title with a verified contributor identity.
7. Open a pull request and complete the template using the canonical
   [PR/MR description guidance](docs/PR-DESCRIPTIONS.md).

Use `type(scope)!: description` for the PR title; scope and `!` are optional.
Accepted types are `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
`build`, `ci`, `chore`, and `revert`. Examples: `fix(state): preserve interrupted
writes`, `feat!: change evidence format`, and the bot's `chore(main): release
0.1.0`. The metadata-only title check has no checkout or write permissions. It
checks syntax, not compatibility or whether a release is due. Ensure the final
squash commit preserves the intended type and any breaking marker/footer.

Before 1.0, breaking public CLI/config/state/evidence/adapter changes and features
bump minor; fixes bump patch. Explain breaking changes and migration/rollback in
the PR body. Docs/chore-only commits ordinarily do not trigger Release Please.
See [RELEASING.md](docs/RELEASING.md) for the v0.1.0 bootstrap, explicit activation
gate, human close/reopen CI route for bot PRs, and release review requirements.
Run checks only inside an independently justified workspace sandbox; a worktree
alone is not a sandbox.

During the explicitly authorized solo-maintainer phase in this repository,
inspect the exact PR head and obtain independent agent QA evidence before a
normal, head-guarded squash merge. Required CI must be green, the branch current,
and review threads resolved. GitHub requires zero approving reviews in this
temporary phase; agent review is evidence, not a GitHub approval. Restore at
least one approval and applicable CODEOWNER review before collaborative
development, as described in `docs/REPOSITORY-SETUP.md`. Do not merge when CI
is failing or required evidence is missing, or use administrator bypass to
satisfy an unmet gate.

Hosted CI runs `make check`, pinned Gitleaks, and the core Ruff/Pyright/Bandit/
ShellCheck/actionlint/zizmor gate under pinned Python 3.12.15. The local strict hook additionally runs
history/staged Gitleaks and Trivy secret scanning. It requires no Nexus runtime.

For a new imported skill, include `SKILL.md`, `PROVENANCE.md`, offline tests,
and any config schema/examples needed to keep consumer-specific values out of
the reusable core. Do not package trusted host-control functionality as a guest
sandbox kit.

## Sync Changes

This repository is canonical after the initial import. Review any later source
change before applying it here. Update the selected skill's `PROVENANCE.md` with
the source revision and material adaptations. A downstream copy in
`agentic/.agents/skills/<skill-name>` must record this repository's canonical
commit in its `PROVENANCE.md` and pass all applicable local fixture suites for
that skill.
