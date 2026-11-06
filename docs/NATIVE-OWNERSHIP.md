# Native ownership: retained-state preflight and cooperative pilot

Issue #116, first slice. **Implemented:** a read-only check of actual retained
schema-2 task, global-slot, and scope records. **Proposed:** native ownership and
authenticated-caller enforcement. Existing coordinator task JSON remains the
authority; there is no new claim store, capture envelope, or native API bridge.

## Opt-in core lifecycle pilot (schema 3)

Issue #116 now includes a bounded cooperative binding pilot in the core state
CLI. New tasks still default to schema 2, and prototype schema-1 migration is
retained. An inactive `Ready` task opts in only through an explicit claim:

```sh
"$SKILL_DIR/run.sh" state claim selected-task --owner pilot-owner --pid <owner-pid> \
  --session-id aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --expected-generation 0 --expected-revision <observed-revision>
```

The fictional session label is an operator-provided ASCII token of 1–128
characters (`[A-Za-z0-9][A-Za-z0-9._-]*`); UUID hex is convenient. Use opaque
labels without personal data. Labels are private correlation inputs, not native
session identity or authenticated authority. The task becomes schema 3 with
`cooperative_binding = {session_id, generation}` at generation 1. The worker and
its complete global-slot/implementation-lane metadata carry the same session and
generation. Counts use exact integers bounded by `2^63-1`. Scope metadata must
also agree exactly with the existing task scope and token.

`record`, `update-head`, `transition`, and `resolve-finding` on active bound tasks
require all four explicit `--expected-session-id`, `--expected-worker-id`,
`--expected-generation`, and `--expected-revision` flags. Comparisons and complete
reservation checks run under the coordinator lock before task/reservation writes.
Missing comparisons yield exit 3; a complete mismatch yields exit 4. Values are
never defaulted from the current record. Copied current values can still pass:
this is cooperative fencing against accidental cross-session/stale writes, not
authentication against another process of the same account.

Release retains the binding and generation. Inactive mutation requires
`--operator-action --operator-reason <rationale>` plus explicit generation and
revision. This is a recorded declaration, not authenticated operator identity.
An active operator action is limited to cancellation when the retained worker
belongs to this host and `ps` verifies that its PID is absent. Alive, reused, or
unmeasurable PIDs cannot grant takeover. Existing execution/repair stop gates
still apply. For a routine pilot handoff, the current owner transitions to
`Blocked`, the operator makes a guarded transition to `Ready`, and a new explicit
claim increments the retained generation. Bound claims require inactive `Ready`;
they cannot claim directly from `Rework`.

Core `show`/`list` explicitly accept schema 3 and retain their existing raw,
private JSON output. Observations confer no authority. Keep their output and
command arguments out of public evidence. Public `read_task`, `validate_record`,
`write_task`, and `command_list` defaults reject schema 3 so existing controllers
using those entry points cannot dispatch or silently discard its binding.
Previous schema-2-only core readers also reject schema 3. The existing native
preflight intentionally remains schema-2-only and reports schema 3 unsupported.

Automatic reconciliation refuses with exit 3 whenever any bound task is present
in the authority, including selected-task calls. All tasks are preflighted before
legacy recovery can mutate an earlier task. Interrupted bound transitions remain
preserved and block mutations/admission; automatic and guarded interrupted-intent
recovery are pending a separately reviewed design.

**Core-CLI-only boundary:** standalone monitor polling accepts only schema 1 or 2.
It rejects schema 3 before loading configuration or creating its monitor directory,
poll lock, checkpoint, failure record, or SQLite store. Durable polling repeats
the guard before opening the store. Execution observation rejects schema 3 before
reading the execution definition or inspecting the runtime binary, and repeats
the rejecting read under the coordinator lock before runtime-config creation.
Other existing state-aware controllers retain the public reader's rejecting
default. These guards refuse unsupported tasks; they do not enable foreground,
monitor, domain, or execution dispatch for the pilot. Full production session
binding, native authentication, and the GitHub bridge remain pending. This pilot
does not close issue #116. Isolated runtime validation remains required.

### Migration, stopping the pilot, and rollback

Opt-in is per task. Keep ordinary tasks on schema 2 unless the operator intends
to use the core-only lifecycle. There is no bulk migration. Older core readers
cannot use schema-3 tasks, and replacing the CLI with an older version does not
make those records compatible.

To stop the pilot, stop admitting bound claims. Ask the retained owner to release
its task through a guarded transition to `Blocked`; if that owner has exited,
independently verify termination and use the guarded absent-worker cancellation
path when applicable. Preserve dirty worktrees and all unsettled evidence.
An interrupted transition stays blocked pending separately reviewed recovery.

Keep the original authority state intact. Export a complete private backup of
task records, reservations, and referenced evidence through operator-approved
backup tooling; keep it access-restricted and out of commits, logs, and review
attachments. Core `show`/`list` output is private observation, not a complete
backup of the authority or its artifacts.

Rollback means stopping use and quarantining the affected authority from legacy
automation, not rewriting task JSON. Do not remove the binding, lower its
generation, downgrade schema 3 to schema 2, delete leases, or move individual
records away to let reconcile proceed. Retain the guarded CLI for inspected
lifecycle actions, or keep the entire backed-up authority quarantined until a
reviewed migration/recovery tool exists. Any fresh legacy authority must have
separately admitted work and no overlapping active owners, branches, or worktrees.

`tests/cooperative-session-binding-test.py` copies the installed core into an
independent temporary fixture and invokes its actual CLI for claim, mutation,
release, re-claim, malformed/mismatched binding and reservations, stale callers,
reader compatibility, and reconciliation preservation. Git probes in its
update-head case use a fixture executable. Standalone monitor cases prove refusal
without poll files or forge dispatch, and execution-observation cases prove that
definition/config/runtime work is not reached. Run the fixture, `make check`, and the
strict hook only in an independently isolated validation environment.

## Select the correct authority explicitly

```sh
python3 -I -B scripts/check-native-ownership.py \
  --authority-root /physical/coordinator-workspace \
  --invoking-root /physical/coordinator-workspace \
  --task-id selected-task \
  --expected-revision 7 \
  --expected-worker-id 11111111111111111111111111111111 \
  --expected-branch feat/selected-task \
  --expected-repo example/project
```

The values above are fictional. Roots name the **workspace containing
`.orchestrator`**, not `.orchestrator` itself. `--invoking-root` means the
explicitly chosen state authority for the invocation, not the current checkout.
A worktree wrapper that defaults its root to its checkout can select a different
`.orchestrator` and lose the retained ownership context. The repository wrapper
now refuses that implicit linked-worktree selection. Pass the canonical
coordinator workspace to the wrapper and this preflight explicitly. The script
does not use environment defaults, discover roots, or scan neighboring stores.

Both roots must be absolute physical directory paths with no symlink ancestors,
empty/dot/parent components, or trailing slash; `/` is refused. On macOS use
`/private/var/...` rather than the `/var` symlink. Device/inode identity must
agree, so two distinct existing roots conflict even if their contents agree.
Missing roots and symlink aliases are unverified.

### Repository shell-wrapper admission guard

`bin/orchestrator-state.sh` defaults to its physical checkout root in a primary
checkout (ordinary `.git` directory), and retains that implicit default for an
archive copy without `.git`. When its checkout has a regular `.git`
gitfile, every invocation except the exact sole argument `--help` requires an
explicit `WORKSPACE_ORCHESTRATOR_ROOT`. This includes `list`, `show`, and
`reconcile`: the state CLI can initialize directories for reads too. Refusal
occurs before imported-skill dispatch or state initialization, with exit 3, empty
stdout, and the fixed stderr line:

```text
orchestrator: UNVERIFIED - shared authority root required
```

An explicitly set empty variable is invalid. The explicit root must already
exist, be absolute, equal its `cd`/`pwd -P` physical path, and contain a primary
`.git` directory. Symlink aliases, relative/dot/parent/trailing-slash spellings,
missing directories, another linked checkout, and unrelated primary repositories
are refused. Metadata-only `git rev-parse` compares canonical common Git
directories for the wrapper checkout and selected primary; it uses explicit Git
paths, clears inherited `GIT_*` variables, disables system/global configuration,
optional locks, hooks, and fsmonitor, and performs no repository discovery.
The wrapper creates no directories during admission and does not select another
root as a fallback. Exact `--help` prints wrapper-local usage without dispatch.

From an admitted linked checkout, use the primary root explicitly:

```sh
WORKSPACE_ORCHESTRATOR_ROOT=/physical/coordinator-workspace \
  bin/orchestrator-state.sh list
```

This is a cooperative guard on the repository's top-level state wrapper only,
not native caller authentication or a defense against malicious/replaced Git
metadata, concurrent root replacement, or a caller controlling its environment.
Direct imported-skill entry points bypass it; their explicit standalone-consumer
behavior remains supported, including non-Git consumers. The repository wrapper
itself accepts an explicit root only for its own shared-Git primary checkout.
The skill's test-mode state override also remains caller-controlled after
admission. The static retained-state preflight below is a separate check.

`tests/shared-authority-admission-test.py` copies the wrapper and skill into a
temporary fixture, creates real primary/linked Git checkouts with hooks disabled,
and checks refusal without new authority directories, shared scope contention,
root/identity rejection, metadata environment isolation, and direct-skill
compatibility. Subprocesses have bounded timeouts and download nothing. Run this
fixture and `make check` in the independently isolated validation environment.

Full-suite environment: a primary checkout can run the normal
`make check`/strict hook without an authority-root export. Archive copies retain
the wrapper's implicit default; the full repository gates still require Git.
A linked checkout
requires `WORKSPACE_ORCHESTRATOR_ROOT` exported as its existing physical primary
checkout **inside the validation environment**, with the same common Git
identity. `tests/operating-surface-test.sh` invokes the actual repository wrapper
for `reconcile`; its copied command-parity fixture does not invoke a state
wrapper. The imported production-worktree fixture sets its own temporary
consumer root and invokes the imported skill directly. The new admission fixture
supplies an allowlisted subprocess environment, excluding inherited authority
and test-state overrides, so the validator's root cannot leak into its independent
copied repositories. Test subprocess exports do not change the parent make/hook
environment. No test-source patch or hook bypass is required. An unrelated
exported root, or a host root unavailable in the isolated guest, is refused;
the validator must supply a real shared-Git primary rather than fabricate one.

`--task-id` uses the existing flat 1–80 character task-ID syntax.
`--expected-revision` is a nonnegative canonical decimal integer at most
`2^63-1`; `--expected-worker-id` is the retained private lowercase 32-hex worker
ID. Optional branch and repository arguments compare exact existing strings;
there is no forge lookup, ref resolution, normalization, or invented immutable
repository ID. Worker IDs are private comparison inputs, **not secrets that
authenticate a caller**. Another session of the same account can copy them.
Keep arguments and host process/terminal logs private; never paste private state
into review evidence.

## Implemented check

Only these three files are read, with paths derived from the selected task:

1. `.orchestrator/tasks/<task-id>/task.json`
2. `.orchestrator/scopes/<scope_key>.lock/owner.json`
3. `.orchestrator/slots/<global_slot>.lock/owner.json`

All ancestors are opened with `O_NOFOLLOW`, directory descriptors remain open
during comparison, and state directories must be current-user owned and private
(0700). Input files must be current-user private regular files (0600), with one
hard link and no more than 1,000,000 bytes, matching the coordinator record byte
ceiling. FIFOs/devices, symlinks, hard links, permissive files/directories, and
unavailable operations fail closed. The script creates nothing, takes no lock,
runs no subprocess, opens no network connection, and imports no coordinator
module or plugin. The workspace root itself may be an ordinary checkout
directory; privacy checks begin at `.orchestrator`.

The actual field sets and lease formats are taken from `validate_record`,
`command_create`, `worker_metadata`, and `command_claim` in
`.agents/skills/workspace-orchestrator/bin/orchestrator-state.py`. This bounded
reader accepts the base schema-2 shape with all normal required keys. It does
not upgrade prototype schema 1. Unknown schema versions or additional fields
(including richer optional coordinator protocol extensions) yield `UNVERIFIED`.
It is not a substitute for the coordinator's full validators.

JSON must be strict UTF-8, with no duplicate keys at any depth, floats,
non-finite numbers, invalid Unicode, or unknown selected-record fields. Parsing
is bounded to depth 32, 2,000 object/array entries, and 16,000 UTF-8 bytes per
string. Normal task string arrays retain the coordinator's 200-element and
1,000-character item limits; legacy prose strings are accepted and never
rendered. All compared values and counts use exact types, including integers
rather than booleans. Task states, kinds, tracker types, transition intents,
hashes, scope hash, slot/lane ranges, worker metadata, and lease token shapes
are validated. Finite counts are additionally bounded to signed 64-bit range.

The task must be `Claimed`, `Implementing`, or `Reviewing`, with no transition
intent, a worker, and a global slot. Idle/terminal/transitioning state or missing
worker/slot yields `UNVERIFIED`. Complete evidence is compared for:

- selected task ID, expected revision, and expected worker ID;
- retained worker task ID and owner versus the task;
- optional exact repository and linked branch expectations;
- the complete global-slot worker record versus the task worker;
- scope task ID, scope text, and token versus the task's scope reservation.

The implementation-lane index is type/range validated in task metadata, but its
reservation file is not read, to keep this slice at three files. Other slots,
scope overlaps, review reservations, process liveness, configuration, acceptance
criteria, remote issue/PR status, and Git worktree/head identity are not checked.
No timestamps grant freshness or takeover. File descriptor metadata is checked
again after reads to detect observed changes; concurrent replacement, directory
movement, coherent replay, and mutation immediately after inspection are not
excluded. There is no transactional snapshot or action-boundary fencing.

## Output and interpretation

Output has only fixed public keys and codes, including errors:

```json
{"status":"STATIC_MATCH","reason":"RETAINED_WORKER_CONSISTENT","native_session_authentication":"UNVERIFIED","mutation_authorized":false}
```

`native_session_authentication` is always `UNVERIFIED`.
`mutation_authorized` is always `false`: the tool never confers mutation
authority. No private ID, token, account/owner string,
absolute path, PID, hostname, exception text, or input argument is rendered.

| Status | Exit | Meaning |
| --- | --- | --- |
| `STATIC_MATCH` | 0 | Selected retained worker, task expectations, global slot, and scope agree. |
| `CONFLICT` | 4 | Distinct physical roots, or complete metadata exposes an explicit ID/revision/owner/branch/repository/lease mismatch. |
| `UNVERIFIED` | 3 | Missing/unsafe/malformed/unsupported state or incomplete/inactive/transitioning evidence. |

Diagnostics report one first failure. Unavailable or malformed lease evidence
prevents a complete comparison, even if another mismatch is apparent. A missing
task is unverified, not permission to create it. Exit 0 is not readiness,
authenticated ownership, review approval, or permission to act.

## Proposed native contract and operator handoff

Future native ownership must separate public account identity from private
native session/task-claim identifiers. No native session collector exists here.
The existing repository string is not immutable forge identity; binding a forge
host, immutable repository identity, issue, and native session to the retained
task/worker requires separate design and review. Native attempt-generation and
authenticated-caller checks remain proposed. The schema-3 pilot's cooperative
generation is a separate declared local comparison, not a native generation.
Same-account sessions must not inherit each other's ownership merely by knowing
the same worker ID. Revision and eventually generation must be checked at the
action boundary; elapsed time or purported expiry must never grant takeover.

For a handoff or conflict, the orchestrator/operator should:

1. Confirm the explicit authority store and selected admitted task privately.
2. Reconcile retained worker/reservation evidence with the current owner and
   independently establish caller identity and any active execution state.
3. Preserve dirty worktrees and unsettled evidence. Arbitrate ownership through
   the existing coordinator lifecycle and policy; do not edit JSON, steal a
   token, or use timestamps to silently replace a worker.
4. After the authorized lifecycle handoff, obtain the new retained revision and
   worker ID and re-run this static check. Apply existing acceptance and action
   gates separately.

Offline fixtures in `tests/check-native-ownership-test.py` construct actual
schema-2 task and reservation shapes. They are registered only as a `make test`
entry. Execute them and required repository checks in an independently justified
isolated environment; a worktree alone is not a sandbox.
