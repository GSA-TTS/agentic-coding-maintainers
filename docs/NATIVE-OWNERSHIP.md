# Native ownership: retained-state preflight and proposed contract

Issue #116, first slice. **Implemented:** a read-only check of actual retained
schema-2 task, global-slot, and scope records. **Proposed:** native ownership and
authenticated-caller enforcement. Existing coordinator task JSON remains the
authority; there is no new claim store, capture envelope, or native API bridge.

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
`.orchestrator` and lose the retained ownership context. Pass the canonical
coordinator workspace to the wrapper and this preflight explicitly. The script
does not use environment defaults, discover roots, or scan neighboring stores.

Both roots must be absolute physical directory paths with no symlink ancestors,
empty/dot/parent components, or trailing slash; `/` is refused. On macOS use
`/private/var/...` rather than the `/var` symlink. Device/inode identity must
agree, so two distinct existing roots conflict even if their contents agree.
Missing roots and symlink aliases are unverified.

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
authenticated-caller checks are not implemented or invented in task JSON.
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
