# Agentic Coding Maintainers

Internal tools, runbooks, and automation for GSA-TTS agentic-coding
maintainers. This repository is the canonical home for the included
`cross-repo-epic` skill after its initial import.

## Included Skill

The skill at `.agents/skills/cross-repo-epic` provides read-only portfolio and
epic reconciliation for the agentic-coding repositories. See its `SKILL.md`
for requirements and use instructions.

## Provenance And Sync

The skill originated in the source author's `review_things` repository and was
hardened in the agentic workspace. Its `PROVENANCE.md` records the authorized
source commit and destination adaptations. Keep that record when moving or
revising the skill.

After this repository's initial import, make authoritative changes here. To
bring in a later authorized change from a `review_things` checkout:

```bash
IMPORT_DIR="$(scripts/import-review-things.sh /path/to/review_things | sed -n 's/^STAGED=//p')"
diff -ru "$IMPORT_DIR" .agents/skills/cross-repo-epic
make check
```

The importer creates a new unique staging directory under ignored `.import/`
and never overwrites the canonical hardened copy or an earlier import. Review
the diff for sensitive state and unsafe behavior, apply selected changes
manually, and update `PROVENANCE.md` with the source revision and material
adaptations before merge.

The agentic workspace consumes this repository at
`agentic/.agents/skills/cross-repo-epic`. From this repository, update that copy
with:

```bash
scripts/sync-agentic-workspace.sh /path/to/agentic
```

The script copies only the canonical skill and removes stale files inside the
destination skill directory. Review the destination diff, run both fixture
suites, and record this repository's canonical commit in the destination
`PROVENANCE.md`.

Do not sync runtime state or review artifacts. In particular, exclude secrets,
Nexus records, certificate authority bundles, handoffs, issue drafts, and
engagement artifacts.

## Development

```bash
make test
make check
```

`make check` uses ShellCheck when it is already installed. It does not download
tools.

Repository administrators must complete and verify
[`docs/REPOSITORY-SETUP.md`](docs/REPOSITORY-SETUP.md) after bootstrap.

## License

This repository is dedicated to the public domain under CC0 1.0 Universal. See
`LICENSE`. Source provenance is retained for audit and attribution context.
