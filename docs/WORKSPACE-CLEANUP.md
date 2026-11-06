# One workspace cleanup round

Loose-file quarantine and skill-sync outboxes share **one root `tmp/cleanup/`
store and one ongoing review process**. Root `/tmp/` is gitignored in this
repository. Consumer Git repositories must explicitly add their own root
`/tmp/` ignore rule before using this store; the tools never edit their ignore
policy. Paths in either HEAD or the index block storage, including staged
deletions. Ignored does not mean disposable, nonsensitive, or inactive.

HEAD/index guards compare literal root components using case folding, even on
case-sensitive filesystems. A disk-only case rename cannot bypass tracked-file
protection, and tracked `TMP/` descendants also block `tmp/` allocation. This
conservatively refuses distinct case-variant names on Linux. No filename is
interpreted as a glob or Git pathspec. Each check reads NUL-delimited index names
and nonrecursive HEAD root names; Git's timeout still applies, but index output
is buffered in memory without a separate byte cap (cost grows with index size).

## Operator round after handoff

1. Reconcile live task/PR ownership, outstanding workers and retained evidence.
   Confirm no process is using the selected artifact. Obtain its owner's review
   of both purpose and sensitivity. A filename or age cannot prove it vestigial.
2. Run read-only inventory from the canonical checkout:

   ```sh
   bin/workspace-cleanup.sh --workspace /absolute/workspace
   # Explicit spelling: append inventory
   ```

   Output is JSON: root entries, protected/runtime directories, loose regular
   files needing owner review, and shared cleanup entry kinds/journal states.
   Journals are not a verified health report. Unknown/partial entries require
   inspection; `deleteme` is always flagged `migration-needed`.
3. Select **one root-level, nonhidden, untracked regular file**. Preview first:

   ```sh
   bin/workspace-cleanup.sh --workspace /absolute/workspace quarantine scratch.txt --reason 'Owner confirmed superseded scratch output'
   bin/workspace-cleanup.sh --workspace /absolute/workspace quarantine scratch.txt --reason 'Owner confirmed superseded scratch output' --apply
   ```

   Apply prints a UUID. Inspect `tmp/cleanup/<uuid>/manifest.json` and `payload`.
   Reasons are limited to 1–1024 UTF-8 bytes; never put sensitive text in them.
4. To return an intact file, use that exact UUID:

   ```sh
   bin/workspace-cleanup.sh --workspace /absolute/workspace restore UUID
   bin/workspace-cleanup.sh --workspace /absolute/workspace restore UUID --apply
   ```

   Restore refuses occupied (including dangling symlink) or tracked destinations,
   malformed journals, wrong-root bindings, changed payloads and sync entries.

There is no delete, purge, batch selection, glob expansion, TTL, cron, or hook.
Quote literal filenames; the CLI does not expand patterns. Inventory and previews
do not create directories, locks or journals. Reads may update filesystem access
times. Exit 3 means refused/unverified; inspect the message and retained artifacts.
Argument syntax errors use argparse's exit 2.

## Storage and trust boundary

The command is Python stdlib behind a thin shell entry point. File moves require
an explicit actual Git top-level workspace (linked worktrees supported). Git
calls have a 15-second timeout, strip inherited `GIT_*` variables, disable
optional locks, global/system configuration, hooks and fsmonitor. The tools
still trust the locally installed executables and owning user's repository.
Neither worktrees nor this CLI are a sandbox for executing untrusted code.

The allocator checks both ignore policy and HEAD/index occupancy before creating
the store. `tmp`, `cleanup`, and generated entry directories must be owned by
the current user, mode 0700, on the root filesystem, and opened without following
symlinks. Existing unsafe directories are refused, never chmodded into compliance.
Manifests are private mode 0600, bounded to 16 KiB, and exclusively created.
Payload modes are preserved by rename rather than rewritten; containing private
directories prevent traversal by other users. Hardlinks, symlinks, special files,
directories, hidden names, runtime/config paths and reserved Git layout names
cannot be selected. Hashing is bounded to 256 MiB per file.

Regular-file device numbers are bound to that file's identity, not compared to
directory device numbers: overlayfs can report different devices for a directory
and its files even when rename succeeds. Directory-hierarchy device checks remain
required. A preview cannot guarantee rename will succeed. Cross-filesystem file
moves are rejected by the actual atomic `os.rename` operation (`EXDEV`), with no
copy/delete fallback. On `EXDEV`, quarantine retains the source and `prepared`
journal without a payload; restore retains the payload and unchanged journal.

**Exclusive cooperative access is a precondition.** Quiesce the selected file,
Git index and workspace lifecycle before applying. An exclusive per-root
`tmp/cleanup/.lock` serializes cooperative mutations, not arbitrary processes.
Checks immediately before rename do not provide a portable atomic no-overwrite
guarantee against hostile concurrent writers. Manifests are trusted owning-user
data, not authenticated attestations. Do not claim protection from a malicious
same-user editor. Locks are never silently taken over.

## Crash recovery, not automatic repair

File quarantine checks path identity against the opened no-follow descriptor,
hashes that descriptor and binds device/inode, size,
mode, mtime, SHA-256, root device/inode, basename, UTC and reason. It fsyncs a
`prepared` manifest **before** renaming, then syncs the affected directories and
updates the journal to `quarantined`. A crash may leave:

| Evidence | Action |
| --- | --- |
| Prepared journal, source present, no payload | No move proven; inspect manually. Restore refuses. |
| Prepared journal, source absent, intact payload | Restore accepts after full identity/hash/root checks. |
| Both paths present, neither present, missing journal, invalid hash | Preserve everything; investigate manually. |
| `manifest.next` present | Interrupted journal update; inspect both journals and artifacts. No automatic replacement. |
| Restore moved payload but final journal update failed | Restored bytes remain at root; tool reports partial state, not success. |
| Journal restored, no payload, root file still matches identity/hash | Repeated restore reports verified already-restored. |
| `.lock` remains after process death | Verify no live sync/cleanup owner, preserve evidence, then manually recover in a maintenance window. |

Exceptions do not delete source, payload or entry journals. Normal cooperative
file operations release their empty lock; abrupt death may leave it. Moving a
workspace or copying files to another filesystem can invalidate identity/root
bindings; inspect rather than editing journals to bypass checks.

## Skill sync uses the same store

`scripts/sync-agentic-workspace.sh` calls internal `allocate-sync --skill NAME
--apply` before consumer mutation. This helper only allocates an entry with
kind/root metadata; it cannot move arbitrary directories. It checks filesystem
compatibility and transfers the shared root lock to the sync caller. Do not call
it as an ordinary operator: successful allocation deliberately leaves that lock
held until the sync trap finishes. Failed callers require manual inspection.

Sync retains its existing per-skill lock, marker, staging, rollback behavior and
`DISPOSAL_OUTBOX=` output. The outbox now lives at `tmp/cleanup/<uuid>/`, with
`manifest.json` for common inventory, **`MANIFEST.md` for sync outcome/recovery**,
and, when present, `previous/`, `stage/`, `marker/`, `lock/`, `cleanup-lock/`.
The generic journal's `allocated` state does not assert installation succeeded.
The sync manifest is written before shared-lock release; its COMPLETE disposal
record is not final success without the retained `cleanup-lock/` and absence of
the root lock. A failed shared-lock move rewrites the manifest with exit 3 and
`FAILED_CLEANUP_LOCK`. If that rewrite also fails, stderr explicitly reports that
the manifest is not success authority; preserve the root lock and inspect manually.
An uncertain prior lock/marker or blocked rollback is preserved. On finalization,
this invocation's shared lock is retained inside its outbox, not deleted.

Non-Git consumers are supported for sync and inventory only; they still use the
same private same-filesystem storage. Ignore policy has no effect until Git is
initialized. Generic file restore refuses sync entries: inspect `MANIFEST.md`,
the installed skill and any external backup paths before skill-specific recovery.

### One-time migration of legacy `deleteme`

There is **no automatic move** and no new `deleteme` output. In an explicitly
scheduled maintenance window:

1. Stop and verify absence of all sync/cleanup processes in this consumer. Review
   every legacy manifest and its destination/backup paths; preserve unresolved
   transactions. Do not treat a stale lock as proof there is no live owner.
2. Review consumer `/tmp/` ignore policy and confirm neither HEAD nor index tracks
   anything under it. Inspect the legacy directory for links, ownership and
   filesystem boundaries. Establish the same owner-only, no-symlink, same-device
   `tmp/cleanup` hierarchy described above; do not reuse unsafe directories.
3. With exclusive access, reserve a fresh, never-existing private entry named
   `legacy-<UTC>-<UUID>` under `tmp/cleanup`. Record the original location, operator,
   time and reviewed legacy manifests in a migration note in that entry.
4. Use a reviewed **same-filesystem directory rename** to move the entire intact
   `deleteme` directory into that entry as `legacy/`. Do not merge directory
   contents, copy across devices, overwrite an existing target, or move individual
   active transactions. If preconditions cannot be established, leave it in place.
5. Verify all old manifests/backups/locks remain intact, record the new location,
   and resume only the unified cleanup round. Inventory deliberately labels this
   non-UUID legacy wrapper for manual inspection; generic restore cannot move it.

This is a one-time operator migration procedure, not a second cleanup process or
a directory-moving CLI. Retention/purge policy is deferred: quarantines and sync
outboxes accumulate until separately authorized human disposition. Nothing here
authorizes removal of retained evidence.

## Separate lifecycle decisions

`work/`, `clones/`, `.orchestrator/`, containers and volumes require their own
manual owner/lifecycle review after handoff. Never rename worktree directories
using quarantine. Tracked vestigial source requires ordinary reviewed Git PR
deletion. Avoid `git clean -x`: ignored content includes live runtime state.
Authoritative references: [git-clean](https://git-scm.com/docs/git-clean) and
[git-worktree](https://git-scm.com/docs/git-worktree).

## Validation

Run only in the independently justified workspace sandbox:

```sh
python3 -I -B tests/workspace-cleanup-test.py
bash tests/import-sync-test.sh
make check
pre-commit run --all-files
```

The Makefile preserves existing suites and includes cleanup fixtures. The root
cleanup Python files also need direct pinned Ruff/Pyright/Bandit review: the
existing core-quality script does not scan root scripts automatically. Tests
exercise byte/mode roundtrips, no-write previews, tracked/staged-deleted paths,
unsafe types/hierarchies, lock contention, malformed/corrupt journals, bounded
inputs, differing directory/file devices with real file identities, directory
device refusal, path/descriptor replacement, injected `EXDEV` in both directions
with source/payload/journal retention, other rename/journal failures, Git
redirection and linked worktrees.
