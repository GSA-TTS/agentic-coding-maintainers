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
mode. A repeat revalidates current state; it is not historical receipt replay.

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

## Guest materialization

Install trusted `review-materialize.py` and `review-handoff.py` together outside
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
`metadata/context.json` and `metadata/plan.json`. Root `MANIFEST.json` is written
first and describes every payload file and disposal ownership. `READY.json` is
written last after file verification and fsync, and means only materialized plan,
never candidate readiness. A replay checks the entire tree, not just the marker.
An I/O failure preserves partial artifacts; missing READY or any failed replay is
nonready. A failure before the first manifest write can leave an empty/partial
root: the CLI explicitly reports preserving that chosen root for disposal.
The operator must dispose of failed roots; retry never repairs one in place.

The emitted plan mounts `candidate/` read-only at **`/candidate`** and `metadata/`
read-only at **`/review-input`**. `mkdir_guest` explicitly lists the mount points
and `/review` when that is the admitted cwd. It is an operator plan, not performed
filesystem work outside the chosen output root. Runner argv uses these exact
guest source paths and `/review-input/context.json`. Python, runner, binary,
profile and output absolute paths come only from CLI, never the bundle. Arguments
remain an array of data; no shell string, subprocess or network API is used.

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
