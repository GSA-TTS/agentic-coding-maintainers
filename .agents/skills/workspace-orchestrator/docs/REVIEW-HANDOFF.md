# Bounded reviewer source handoff (v1)

The installed controller's `foreground-delivery` action `export-admitted-review`
exports selected packet bytes and the exact admitted review context. The guest's
`review-materialize` writes those bytes into a fresh private output root and emits
a mount plan plus `review-run.py` argv. Neither operation mounts, launches a
reviewer/model, executes candidate code, installs anything, or contacts a remote.

## Controller export

Use the ordinary foreground request envelope with current task ID, incarnation,
expected revision and an operation ID, `action: "export-admitted-review"`, and
`payload: {"admission_id": "<digest>"}`. Invoke the independently installed
`run.sh foreground-delivery TASK --request /private/export-request.json`.

Only an exact `prepare-repaired-review` → `assign-prepared-review` →
`admit-prepared-review` chain is exportable. Direct collection admissions are
refused. The dispatcher validates all retained links, the current incarnation,
revision, live full worker identity and reservations, unpaused Implementing state,
stopped execution and settled repair. The exporter rechecks the original owner,
full worker, scope, material epoch, current generation, clean exact head and
origin before and after constructing the projection. Already collected or
reported attempts are refused. Missing evidence returns `UNVERIFIED` (exit 3).

Export creates no task receipt, revision, packet or artifact-store entry. It uses
the existing coordinator lock, whose acquisition/release creates and removes an
**ephemeral lock directory**. “Read-only” describes authoritative task/artifact
state, not an absence of these lock filesystem operations. There is no unlocked
mode. Before reservation, a repeat revalidates current state. After reservation,
export returns the validated frozen historical bundle described below.

Success is `REVIEW_HANDOFF_EXPORTED` with `bundle` and `bundle_sha256`. Save only
the `bundle` object as JSON in operator-selected private staging. The hash is over
canonical JSON (sorted keys, ASCII escaping, compact separators, trailing newline).
It detects byte inconsistency, not sender authenticity. Transfer and authenticate
the exported file through the operator's separately authorized channel.

### Strict transport projection

`review-handoff.py` owns the v1 schema and recursive validation. All objects have
exact keys; duplicate keys, nonfinite numbers, nested extras and invalid types
are refused. The canonical bundle is at most **8,000,000 bytes**, including
base64 expansion and metadata. It has:

- `schema_version: 1`, `kind: "admitted-review-handoff"`;
- `binding`: task ID, incarnation, export revision, admission input revision,
  admission ID, foreground admit operation ID, generation, material epoch,
  original base, exact head, packet and policy digests;
- `runtime`: assigned run ID, reviewer, session, profile/binary hashes, model,
  agent and exact admitted cwd;
- `context` and its canonical SHA256: acceptance criteria, all obligations and
  recursively validated finding/disposition history, at most **50,000 bytes**;
- `sources`: **1–20** explicit records with guest path, packet path base64,
  before/after side, exact byte count, SHA256 and canonical content base64.

Context is copied byte-for-byte in its canonical representation from the
admission **AS OF `admission_revision`**, not recomputed from later reports.
No obligation or finding is dropped to meet the size budget. A packet side must
be a regular blob (`100644` or `100755`); absent sides, symlinks and gitlinks are
refused. Executable Git blobs become non-executable read-only materialized files.
Only selected blobs travel: no raw task, worker, leases, environment, host checkout
paths, Git metadata, diff, or unselected source content. Free-form admitted prose
and selected source are preserved as untrusted data; this is not a secret or
prose-redaction service.

Source destinations must be canonical descendants of `/candidate`, using bounded
ASCII path components; `.git`, traversal, duplicate destinations and file/directory
collisions are refused. Cwd is exactly `/candidate` or `/review`. In particular,
`/home/node/review` and arbitrary previously admitted layouts are **unexportable**;
v1 refuses them rather than silently rewriting the admission. Sessions must match
the existing runner's `ses_…` format.

Discovery/control names are also refused case-insensitively in **every** destination
component, including when cwd is `/candidate`: `opencode`, `agents`, `claude` and
their dot-suffixed variants (including `opencode.json/jsonc`, `AGENTS.md`,
`AGENTS.override.md`, `CLAUDE.md`, `CLAUDE.local.md`); `.opencode*`, `.agents*`,
`.claude*`; and `.agent`, `agent.md`, `.git`, `.github`, `.mcp.json`, `mcp.json`,
`.cursor`, `.cursorrules`, `.gemini`, `GEMINI.md`. Such destinations are rejected,
never remapped. This is a bounded allowed-layout restriction, **not** a claim that
all discovery is disabled: installed profiles, runtime/global configuration,
ancestor directories outside the mount and future tool conventions remain the
operator's responsibility. Original repository names remain untrusted metadata.

## Guest materialization

### Controller reservation (groundwork; launch remains BLOCKED_PROFILE)

The same foreground envelope accepts `reserve-review-attempt` with exactly:

```json
{
  "admission_id": "<admission SHA256>",
  "bundle_sha256": "<current canonical export SHA256>",
  "destination": {
    "backend": "docker",
    "sandbox_id": "<opaque bounded identity>",
    "created": "2026-11-04T00:00:00Z",
    "endpoint_sha256": "<operator endpoint identity SHA256>",
    "result_root": "/review-results/attempt"
  }
}
```

Backend is exactly `docker` or `msb`. Sandbox identity is an ASCII token (at most
80 characters); creation identity is a UTC timestamp with optional fractional
seconds; endpoint identity is a SHA256, never a URL, socket, credential or command.
The result root is one bounded token below `/review-results/`. These fields are
operator declarations, **not verified sandbox identity or an executable route**.
No backend is contacted and no result directory is created.

Reservation first exports the **current** prepared admission under the existing
lock and all current exporter prerequisites. The caller's hash must match exactly.
It retains canonical bundle bytes as a private `0400` content-addressed file under
`review-handoffs/`, fsyncs the file/store/root, then persists one admission-keyed
task entry and one reverse-linked foreground receipt. Entry fields retain the
original export revision, bundle pointer, original owner/full worker snapshot,
destination and admit-operation pointer; worker/endpoint metadata never enters
the export bundle. The initialization marker, schema, domain links and both receipt
directions are validated, including on shared lifecycle mutation paths.

Only `RESERVED` and `CANCELLED_UNCONSUMED` exist. One admission can be reserved
**once forever**, including after cancellation: another operation ID, request-file
path or destination cannot reserve it again. Exact operation replay acknowledges
retained history only. Exports and reservation results always carry
`replay_only: true`, `launch_authorized: false`, and `launch_gate: BLOCKED_PROFILE`.
There is no production consume/spawn action or profile bypass. This establishes
reservation groundwork, **not at-most-once inference**.

`cancel-review-reservation` takes exactly `{"admission_id": "<digest>"}` at the
current task revision. Cancellation validates retained artifacts, domain links,
capacity reservations and exact original owner/full worker, but does not require
that worker to remain alive. It works while paused. A dead owner does not free
capacity until cancellation permits ordinary coordinator reconciliation.
Pause remains available subject to receipt capacity. Each pending reservation
reserves one cancellation receipt slot and projects maximum-size cancellation
metadata through the production serialized task-size limits; other actions cannot
spend that capacity. Cancellation neither releases coordinator leases nor asserts
anything about a spawned process: no consumer exists. Reserved admissions cannot
acquire runtime collections or reports even after cancellation.

Pending reservations block lifecycle, head and evidence mutations through the
shared guard. After cancellation, those ordinary APIs are available again. Export
of a reserved admission continues to return the **original canonical bundle bytes**
after pause, cancellation, reclaim or generation/head supersession. It validates
the retained packet, bundle hash and domain references, but no longer requires
the historical worker/head to be current. The request still names the current task
incarnation/revision. Historical exports never authorize launch. Missing artifacts,
markers, or links return `UNVERIFIED`; they are not reconstructed by replay.

An artifact write followed by a failed task write may leave an unreferenced
content-addressed file. It grants no reservation and is never inferred into the
ledger. An exact retry validates it and completes durability before task persistence.
The controller lock is cooperative; rollback of all authoritative state or a
malicious same-UID writer is outside this consistency protocol's guarantees.

### Materialization CLI

Install trusted `review-materialize.py`, `review-handoff.py` and `review-source-map.py` together outside
candidate mounts. Example (all CLI paths are trusted operator choices):

```bash
python3 -I -B /trusted/review-materialize.py \
  --bundle /private/admitted-bundle.json \
  --output-root /private/review-attempt \
  --python /usr/bin/python3 \
  --runner /trusted/review-run.py \
  --binary /trusted/opencode \
  --profile /trusted/reviewer-profile.json \
  --output /runtime/reviewer-results
```

The output root's parent must already exist, be owned by the current user, and
have mode `0700`. Root must be fresh (even a pre-existing empty directory is
refused), or a complete byte-identical replay of this bundle **and plan**. There
is no merge, overwrite or cleanup path. Root/ancestor symlinks, source symlinks,
hardlinks, special files, extras, incomplete trees or altered permissions fail
closed. Files are `0400`, directories `0700`; every path walk/create is relative
to held directory descriptors with `O_NOFOLLOW` and exclusive file creation.
There is no archive extraction. Complete validation, including an optional
profile's exact admitted hash, happens before any output-root creation.

The layout is `candidate/<admitted relative destination>` plus separate
`metadata/context.json`, `metadata/source-map.json` and `metadata/plan.json`. Root `MANIFEST.json` is written
first and describes every payload file and disposal ownership. `READY.json` is
written last after file verification and fsync, and means only materialized plan,
never candidate readiness. A replay checks the entire tree, not just the marker.
An I/O failure preserves partial artifacts; missing READY or any failed replay is
nonready. A failure before the first manifest write can leave an empty/partial
root: the CLI explicitly reports preserving that chosen root for disposal.
The operator must dispose of failed roots; retry never repairs one in place.
For an already complete, byte-identical tree, replay verifies everything and then
fsyncs **every regular file, every directory bottom-up, and the output root's
parent** before success. This completes durability after an earlier READY-file,
final-directory or parent fsync failure left visible bytes. A persistent fsync
failure remains UNVERIFIED; replay does not change any bytes or merge missing
files. A READY marker alone proves neither validation nor durability.

The emitted plan mounts `candidate/` read-only at **`/candidate`** and `metadata/`
read-only at **`/review-input`**. `mkdir_guest` explicitly lists the mount points
and `/review` when that is the admitted cwd. It is an operator plan, not performed
filesystem work outside the chosen output root. Runner argv uses these exact
guest source paths and `/review-input/context.json`. Python, runner, binary,
profile and output absolute paths come only from CLI, never the bundle. Arguments
remain an array of data; no shell string, subprocess or network API is used.

### Selected-source provenance through the runner

`review-source-map.py` defines a separate strict canonical JSON object with exactly
`schema_version: 1`, `base`, `head`, `packet`, and `sources`. Each source has exactly
`guest_path`, `side` (`before`/`after`), `path_base64` (original repository path
bytes, including non-UTF-8 bytes), and `sha256`. It is at most 200,000 bytes and
contains 1–20 entries, sorted by guest path when projected. There are no arbitrary
extras, duplicate destinations, truncated inventories or inferred paths.

The plan always supplies `--source-map /review-input/source-map.json`.
`review-run.py` validates its complete path/hash inventory against the actual
`source_manifest` before invoking the runtime. It includes the explicit mapping
as **untrusted JSON data** in the prompt, explaining that `before` belongs to
`base` and `after` to `head`, without inferring provenance from guest filenames.
It hashes map bytes before and after invocation; changed bytes downgrade the
receipt. `source_map_sha256` binds the initial canonical bytes. This leaves the
admitted context bytes and `context_sha256` entirely unchanged.

Collection compatibility is explicit: historical receipts without
`source_map_sha256` remain legacy-compatible. When the field exists (including on
every run using a handed-off plan), the collector recomputes the **entire** map
from the admitted source selections, hashes, original base, head and packet;
null, partial, altered-side/path or altered-comparison digests are refused.
Read-only export records no receipt, so the collector cannot distinguish a legacy
run from a worker that omits the optional map field. This is consistency binding,
not proof that a model obeyed the mapping or that worker artifacts are authentic.

### Limitations

- No sandbox/isolation attestation, source execution, review, approval or delivery
  credit. `candidate_ready`, `execution_credit`, `delivery_credit` are false.
- Operator must supply an independently trusted runner/runtime and qualify the
  guest, mounts and permissions before choosing to run the plan. The binary is
  hash-checked by the existing runner at execution, not executed or inspected by
  materialization. The profile is hash-checked when supplied; omitting it emits
  `profile_verified: false` and cannot yield a collection matching the admitted
  profile. No runtime configuration is installed here.
- A same-UID writer can change output after verification; filesystem snapshots
  and the mount plan are not an authenticity or isolation boundary. Controller
  locks coordinate cooperative controllers, not malicious host processes.
- Selected-source coverage is bounded, not a complete checkout. No context files
  are inferred, and no review obligations are waived for missing source coverage.

## Validation

`tests/review-handoff-test.py` is a standalone pure bundle/filesystem unittest
module. `tests/foreground-handoff-test.py` explicitly selects three real CLI
fixture cases, reusing the existing test-local compile optimization without
inheriting or rerunning other test methods. Both are included in `make test` and
`make check`. Synthetic fixture reports confer no model or candidate-test credit.
`tests/review-reservation-test.py` selects three additional workflow fixtures with
compiled-source cache reuse: exact replay/frozen export/cancel, metadata and origin
loss, and receipt/byte capacity, write failures and real dead-worker recovery.
