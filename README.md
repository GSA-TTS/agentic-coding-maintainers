# Agentic Coding Maintainers

Internal tools, runbooks, and automation for GSA-TTS agentic-coding
maintainers. This repository is the canonical home for both included skills
after their initial reviewed imports.

## Included Skills

The skill at `.agents/skills/cross-repo-epic` provides read-only portfolio and
epic reconciliation for the agentic-coding repositories. See its `SKILL.md`
for requirements and use instructions.

The skill at `.agents/skills/workspace-orchestrator` provides reusable,
host-side coordination for multiple implementation/review workstreams: bounded
worker admission, one-writer worktrees, fixed-head QA/security review,
foreground GitHub monitoring, and fail-closed recovery. It accepts arbitrary
GitHub repositories and an optional Project v2 board through validated consumer
configuration. It is not an `acq` guest kit or a sandbox boundary.

Both skills use the portable Agent Skills layout and are tested with OpenCode
1.19+ and 2.0+. See
[`docs/OPENCODE-COMPATIBILITY.md`](docs/OPENCODE-COMPATIBILITY.md) for verified
interfaces, provider-config differences, and model-free runtime probes.

## Provenance And Sync

The skill originated in the source author's `review_things` repository and was
hardened in the agentic workspace. Its `PROVENANCE.md` records the authorized
source commit and destination adaptations. Keep that record when moving or
revising the skill.

After this repository's initial import, make authoritative changes here. The
old `scripts/import-review-things.sh` expected skill files at obsolete root
paths in `review_things` and could no longer import them. It was removed rather
than encouraging a broken, backwards import from a consumer into the canonical
repository. The original authorized import remains documented in each skill's
`PROVENANCE.md`.

The workspace-orchestrator import is separate because its source includes
multiple binaries, role profiles, tests, and docs:

```bash
IMPORT_DIR="$(scripts/import-workspace-orchestrator.sh /path/to/review_things | sed -n 's/^STAGED=//p')"
diff -ru "$IMPORT_DIR" .agents/skills/workspace-orchestrator
```

The import records SHA-256 for every staged source file. After initial import,
this repository is canonical; do not automatically overwrite reviewed
destination adaptations with a newer workspace copy.

The agentic workspace consumes these skills at
`agentic/.agents/skills/<skill-name>`. From this repository, update one selected
copy with:

```bash
scripts/sync-agentic-workspace.sh /path/to/agentic cross-repo-epic
scripts/sync-agentic-workspace.sh /path/to/agentic workspace-orchestrator
```

The script stages then replaces only the selected canonical skill directory,
with a transaction marker and trap that restores the previous copy if interrupted
before installation completes. The brief two-rename replacement is not a
cross-platform atomic exchange. An atomic per-skill lock refuses concurrent or
uncertain stale transactions; process death outside trap handling requires human
inspection rather than automatic takeover. It cannot delete a sibling skill.
Review the destination diff, run every applicable
fixture suite for the selected skill, and record this repository's canonical
commit in the destination `PROVENANCE.md`.

Do not sync runtime state or review artifacts. In particular, exclude secrets,
Nexus records, certificate authority bundles, handoffs and unposted issue
drafts. Reviewed maintainer runbooks and nonsensitive operating records may
live here; check their contents, not only their filenames.

## Development

```bash
make test
make check
```

`make check` uses ShellCheck when it is already installed. It does not download
tools.

Repository administrators must complete and verify
[`docs/REPOSITORY-SETUP.md`](docs/REPOSITORY-SETUP.md) after bootstrap.
Maintainers troubleshooting GitHub Actions log downloads on managed macOS hosts
should use [`docs/MACOS-GITHUB-TLS.md`](docs/MACOS-GITHUB-TLS.md).

## License

This repository is dedicated to the public domain under CC0 1.0 Universal. See
`LICENSE`. Source provenance is retained for audit and attribution context.
