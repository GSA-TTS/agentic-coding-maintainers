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

### Run maintainer work from this repository

The skills are self-contained. For this engagement, copy
`orchestrator.example.json` to the gitignored `orchestrator.json` and review
its repository list and Project board before using it. The default example
does **not** become live configuration automatically.

```bash
bin/orchestrator-state.sh reconcile
bin/orchestrator-state.sh list
bin/portfolio-status.sh
bin/epic-status.sh patterns#357
# After creating a kind=monitor task named portfolio-monitor, claim and exec
# in the SAME process (the recorded worker PID must be the monitor's PID):
sh -c 'bin/orchestrator-state.sh claim portfolio-monitor --owner monitor --pid $$ >/dev/null && exec bin/orchestrator-monitor.sh --task-id portfolio-monitor --loop'
```

The `bin/` scripts are thin entry points into the canonical skills. A missing
monitor config exits 3 (UNVERIFIED). Keep `.orchestrator/` task records,
`work/` task worktrees, `clones/` upstream clones, and `orchestrator.json`
host-local and uncommitted. `.opencode/agents/` contains installed copies of
the canonical role profiles; the test suite checks their byte equality.
Restart OpenCode after changing agents or commands.

See `AGENTS.md` for worker limits, ownership, recovery and the trust boundary:
a worktree is not a sandbox for untrusted PR code.

## Checks

For an operator-invoked, read-only **current-state** task-record scorecard, run
`python3 -I -B scripts/evaluate-workflow.py --workspace .`. See
[`docs/WORKFLOW-EVALUATION.md`](docs/WORKFLOW-EVALUATION.md) for its unmeasured
outcomes, cohort design and reflection guardrails. An empty or unreadable task
store exits 3 (`UNVERIFIED`), never a healthy-looking zero-work report.

The first **recorded-cohort** reflection parser is
`python3 -I -B scripts/cohort-reflection.py --ledger /absolute/private/cases.jsonl
--key-file /absolute/private/report.key --as-of <UTC>`. Its [contract](docs/COHORT-REFLECTION.md) distinguishes recorded
events from independently verified outcomes; it cannot infer intake
completeness or verified completions from the ledger alone.

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
