# Review protocol: committed source capture

## Available entry point

```bash
bash bin/review-packet.sh \
  --repo /absolute/candidate \
  --repository owner/repository \
  --base FULL_COMMIT_ID --head FULL_COMMIT_ID \
  --comparison direct \
  --store /absolute/private/controller-packets
```

The canonical invocation is `run.sh review-packet`; it launches Python with
`-I -B`. Run only the trusted installed copy on the controller. Candidate copies
are tested in an isolated environment. `direct` compares the specified commits;
`merge-base` requires exactly one common ancestor and records both the requested
base and effective comparison base. Full lowercase SHA-1 or SHA-256 commit IDs
are required. The repository name is caller-declared, not GitHub attestation.

Output is `CAPTURED` with a content address or `UNVERIFIED` with exit 3. Usage
errors exit 2. Capture establishes neither candidate readiness nor review,
execution, approval or delivery credit. Existing coordinator readiness still
uses legacy claims; packet capture does not upgrade those claims.

## Coverage and bounds

Every changed path is captured with its exact base64-encoded Git pathname,
optional UTF-8 rendering, status, before/after mode and object identity. Renames
are represented as deletion/addition. Text blobs retain exact UTF-8 content;
binary blobs use base64; symlinks retain their target bytes without traversal;
gitlinks retain object identity with explicit UNVERIFIED content coverage.
The full binary-capable diff is included as base64.

The collector allows at most 200 changed paths, 256,000 bytes per blob and
8,000,000 bytes for a packet or Git response. Each Git call has a 15-second
deadline and bounded streaming output. Exceeding a bound fails capture; it does
not silently truncate. Source comes from immutable objects, not dirty worktree
bytes. Git lazy fetching, replacement objects, external diff, textconv and hooks
are disabled. Missing source is a failed capture.

Complete changed-file inventory is separate from sufficient context. Unchanged
consumer/dependency files, GitHub metadata, remote repository identity and test
execution are not collected by this version. Context coverage remains
UNVERIFIED, including for an empty change. Baseline obligations are mandatory;
path/nonregular-source triggers add conservative specialist obligations. This
is a starting obligation list, not complete behavioral classification.

## Retention and trust

The store must be private, current-user owned, outside the candidate checkout,
and reached without symlinked path components. The SHA-256 of canonical packet
bytes is its filename. Creation is exclusive; existing matching bytes are reused
and conflicting/truncated objects are refused. Interrupted creation may leave a
partial object which remains UNVERIFIED and is not overwritten automatically.

These checks are single-user, check-then-use filesystem defenses. They are not
an OS boundary against a same-user process. The real runner must keep the store
and installed policy inaccessible to workers. File mode and a digest alone do
not prove immutability against that process. No packet reference currently
mutates task state or grants an action permission.

Future assignment/evidence acceptance must follow the atomic reference and
operation-replay contract in [MAINTAINER-SERVICE.md](MAINTAINER-SERVICE.md).

## Review claims and operation receipts

`run.sh review-evidence TASK_ID --request STAGING_JSON` accepts a bounded JSON
operation through the installed coordinator lock. Without `--request` it
explains the current claims and returns exit 3 because runtime corroboration is
not yet available. Every request has exactly `schema_version: 1`, `operation_id`,
`expected_revision`, `action` and `payload`. Actions are:

- `begin`: bind `packet` and `policy` SHA-256, task `base`/`head`, and mandatory
  `obligations` to a new generation.
- `assign`: bind `generation`, `run_id`, independent `reviewer` label, `profile`
  SHA-256, assigned `obligations`, explicit `adapter` (`fake` or
  `native-session`) and `session` identifier.
- `accept`: bind `generation`, `run_id`, `packet`, `policy`, `profile`, `session`,
  exact obligation `coverage` (`reviewed` or `unverified`), `findings`,
  `dispositions` and `limitations`.

The operator supplies assignments; this interface does not dispatch a worker or
reserve capacity. A reviewer label different from the owner does not prove
independent execution. Each finding contains `id`, `invariant`, `trigger`,
`path`, `impact` and `evidence`. A later run may append a disposition containing
`finding_id`, `resolution` (`fixed`, `refuted`, `persists`) and `counterevidence`.
Findings and acceptance order survive canonical JSON key sorting. Prior
generations are retained. A disposition applies only to its current generation.

Accepted bounded reports and operation receipts are embedded together in task
JSON, avoiding a second evidence-store transaction in this first slice. The
same operation ID and canonical request returns its original result even after
the task revision advances; changed content under that ID is refused. There are
at most 16 generations, 12 assignments per generation and 100 operations, with
a 900,000-byte authoritative payload ceiling. Exhaustion is UNVERIFIED.

This is additive claim retention, not authenticated execution evidence. A full
review can yield `CLAIMS_COMPLETE`, with a useful retained clean result or
findings. Candidate readiness, execution and delivery credit remain false.
Tasks using this protocol cannot fall through legacy string-based readiness,
including during recovery. New-head results require a new generation; ordinary
acceptance of one report does not invalidate another current assignment.

The source-packet content address and policy binding are supplied claims here;
they are not silently upgraded to source-access attestations. A qualified
runner must corroborate them before this protocol can authorize readiness.

`run.sh review-evidence TASK_ID --correction` derives a bounded, hashed repair
request for the original implementation owner. It carries current source and
task revision, retained unresolved findings, acceptance criteria, owned/restricted
paths and remaining rework cycles. It is a read-only projection: it grants no
writer lease, applies no patch and does not change coordinator state. Changed
owner, stale generation, exhausted budget or absent unresolved findings are
refused. The original owner must enter and claim rework using existing coordinator
transitions before changing its worktree. Review-only external PR tasks cannot
use this projection to obtain implementation authority.

## Verification

Run the acceptance suite in the approved isolated environment:

```bash
python3 -I -B .agents/skills/workspace-orchestrator/tests/review-packet-test.py
```

The baseline case manifest distinguishes protocol tests from the still-required
real review, repair and independently labeled semantic comparison. See
`tests/review-baseline.json` in this skill.
