# Foreground delivery for an admitted task

`run.sh foreground-delivery TASK` reports retained progress and a candidate next
action. With `--request REQUEST`, it executes one bounded local step. It does not
discover tasks, claim workers, invoke a model, provision a sandbox,
change Git refs or publish a PR. It can explicitly apply a collected owner proposal
through the bounded repair engine. The independently installed controller remains
outside candidate worktrees; tests of candidate controller code run in isolation.

This production composition replaces manual translation between the existing
review collection, review acceptance, correction preparation and owner-proposal
admission/collection entrypoints. Owner proposals route through `repair-proposal.apply`.
Application and reconciliation route through `repair-apply.apply_repair` and
`repair-apply.reconcile`, with a separate foreground linkage ledger.
It preserves their exact validators and receipts. It is not the fixture-specific
`qualify-review-repair.py` driver and creates no second task lifecycle authority.

## Request

```json
{
  "schema_version": 1,
  "task_id": "admitted-task",
  "incarnation": "<task incarnation digest>",
  "expected_revision": 12,
  "operation_id": "collect-attempt-1",
  "action": "collect-review",
  "payload": {
    "admission_id": "<existing review admission digest>",
    "artifact_sha256": {
      "receipt.json": "<digest>",
      "transcript.jsonl": "<digest>",
      "session-export.json": "<digest>",
      "stderr.txt": "<digest>",
      "export-stderr.txt": "<digest>"
    }
  }
}
```

Incarnation uses the existing candidate-binding derivation: task ID, creation
timestamp and scope token. Obtain expected_revision from current task state;
never substitute a new revision into an old request to bypass a refusal.

| Action | Payload | Required surrounding work |
|---|---|---|
| `collect-review` | admission_id and exact five artifact hashes | Reviewer was already assigned/admitted; supply `--bundle DIR` |
| `accept-review` | admission_id | Collection is retained and current; structured final response must validate |
| `prepare-correction` | empty object | Rework already admitted using the coordinator; original-owner rules still apply |
| `admit-owner-proposal` | correction_id, session, model, agent, binary_sha256, profile_sha256, cwd, sources | Prepared correction; original owner has separately reclaimed and entered Implementing with live reservations and a clean exact checkout |
| `collect-owner-proposal` | admission_id and exact five artifact hashes | Current owner proposal admission; supply `--bundle DIR`; owner worker, context and source hashes must still match |
| `apply-owner-proposal` | admission_id | Latest admission for the current prepared correction has a retained collected bundle; exact owner worker, context, source hashes and clean checkout still match; no `--bundle` |
| `reconcile-owner-proposal` | apply_operation_id | Existing foreground application; current revision and ownership; allowed while paused; observes only, never resumes writes |
| `adopt-owner-repair-head` | apply_operation_id, head (full commit object ID) | Operator has committed exactly the applied repair on the original owner's branch; final APPLIED_UNREVIEWED application and current original-owner context required; no `--bundle` |
| `prepare-repaired-review` | adopt_operation_id | Current original owner and adopted head; authenticate and retain a direct original-task-base packet, begin a fresh claims generation in one task write; no `--bundle` |
| `pause` / `resume` | empty object | Current nonterminal admitted task; changes only foreground control |
| `status` | empty object, or omit request entirely | Reads retained task/domain evidence; no state initialization |

Example sequence:

```bash
run.sh foreground-delivery TASK --request collect.json --bundle /staging/reviewer-output
run.sh foreground-delivery TASK --request accept.json
run.sh foreground-delivery TASK
```

These are separate committed revisions. `accept.json` uses the revision after
collection, or a replay of its own original request. A retained finding produces
an owner-rework handoff; after separately authorized Rework admission the next
foreground step can prepare the bounded correction. The original owner separately
reclaims its worker and enters Implementing through the coordinator, then can use
foreground owner-proposal admission and collection. Full claim coverage is not
validated tests, current CI or approval.

Owner admission uses the same v1 request envelope, with this payload:

```json
{
  "correction_id": "<prepared correction digest>",
  "session": "ses_owner_attempt_1",
  "model": "provider/model",
  "agent": "owner",
  "binary_sha256": "<runtime binary digest>",
  "profile_sha256": "<owner profile digest>",
  "cwd": "/review",
  "sources": {"/candidate/source.py": "source.py"}
}
```

Sources map one or two explicit guest paths to unique in-scope candidate-relative
paths. The owner session must be distinct from every retained reviewer session.
Admission returns the domain `admission_id` and context inside `domain_result`.
Provisioning the read-only owner runtime and obtaining its artifacts remain
separate work. Collection uses that admission ID and the same five artifact hash
keys as review collection; it checks the owner-proposal role, context, session,
source observations, completion and rendered replacement bundle.

`PROPOSAL_COLLECTED` retains a content-addressed replacement bundle and returns its
`bundle_sha256`. `UNABLE_OBSERVED` retains a corroborated inability response and
returns a null bundle hash. Neither outcome changes candidate files or resolves
findings. Applying a bundle requires a separate `apply-owner-proposal` request;
committing, executing and independently re-reviewing remain separately guarded
operations. There is no autonomous repair loop.

### Explicit application and reconciliation

Use the same request envelope with `action: "apply-owner-proposal"` and
`payload: {"admission_id": "<collected admission digest>"}`. The controller reads
the retained bundle; callers cannot substitute replacement bytes at apply time.
It checks the latest admission, the complete admitted worker record, correction
context, current source hashes, scope, live ownership and current revision before
handing the bundle to the existing repair engine.

The engine performs exactly two durable task writes. The first publishes its
`APPLYING` intent, review invalidation and the foreground application link
**atomically before any target write**. The second publishes the verified domain
`APPLIED_UNREVIEWED` phase and foreground final receipt together. There is no
dispatcher outer write or third receipt write. One or two existing ordinary
non-executable files can be replaced under the existing repair restrictions.
Application still requires a fresh committed head before execution/re-review.

Interrupted application retains a pending foreground entry. Exact retry returns
`REPAIR_RECONCILIATION_REQUIRED` (exit 3) without writing targets or task history;
it never retries the replacements. Use a new current-revision request with
`action: "reconcile-owner-proposal"` and
`payload: {"apply_operation_id": "<foreground apply operation ID>"}`. This calls
only the existing repair observation API. It persists its own immutable outcome
and, for `APPLIED_UNREVIEWED` or `NOT_APPLIED_OBSERVED`, finalizes the foreground
application in the same write. `PARTIAL` and `UNVERIFIED` observations exit 3 and
leave application pending. Another observation requires a new operation ID and
the current revision; replay of an earlier partial observation stays partial
even after a later terminal observation. No automatic rollback or write completion
occurs. Missing artifacts fail closed before reconciliation as well as replay.

An initial persistence failure before durable intent leaves targets untouched.
A final persistence failure can leave all targets replaced and the operation
pending; reconciliation is mandatory. An ambiguous persistence/fsync result must
be resolved from retained history, never by assuming an exception means no write.

### Adopt an operator-created repair commit

After separately creating the repair commit, submit the ordinary v1 foreground
envelope with `action: "adopt-owner-repair-head"` and
`payload: {"apply_operation_id": "<foreground apply ID>", "head": "<full commit ID>"}`.
The controller invokes no commit, checkout, add, status, or ref-write command.
The original owner must still be Implementing with the same full worker identity,
live reservations, correction scope, cycle and post-application material epoch.
The application must be final `APPLIED_UNREVIEWED`, including explicit successful
reconciliation, and linked to the latest collected proposal for that correction.

Fresh adoption reads bounded hermetic `git config --null --get-all remote.origin.url`
output and requires exactly one configured URL matching the task repository.
Accepted forms are `https://github.com/OWNER/REPO`,
`ssh://git@github.com/OWNER/REPO`, and `git@github.com:OWNER/REPO`, with optional
`.git` suffix and case-insensitive owner/repository matching. Credentials, custom
ports, query strings, other hosts/protocols, absent and multiple URLs are refused.
This checks configured identity without applying `insteadOf` URL rewrites or
contacting GitHub; historical status/replay does not inspect current origin.

The helper reads the actual raw commit (tags are refused), requires its single
parent to be the repair's original head, and compares the entire tree inventory.
For BOTH original and new commits it extracts the root tree ID from authenticated
commit bytes, reads and hashes every root/descendant raw tree object, then parses
its entries. Full inventories are derived only from these authenticated bytes,
not `diff-tree`/`ls-tree` output or unbounded `git fsck`. Duplicate names, invalid
ordering, unsafe paths, unsupported modes, empty descendant trees and truncated
object IDs fail closed. A parseable loose tree stored under the wrong object hash
is refused before adoption and during retained status/replay validation.
Exactly the retained one or two modified `100644` paths must appear. Before blob
SHA-256 and after raw bytes must equal the retained bundle; raw object IDs are
independently recomputed. Additions, removals, renames, executable/mode changes,
merges and alternate parents are refused. Filesystem repair modes must retain
their original `0600` or `0644` values.

Adoption checks the actual worktree root, full branch ref and HEAD, compares the
entire stage-zero index with the head tree, and reads every tracked file without
filters. An explicit filesystem walk includes ignored and untracked paths;
assume-unchanged and skip-worktree bits cannot hide bytes. Symlinks, gitlinks,
special files, untracked directories, and oversized inventories fail closed.
The helper reuses the installed bounded Git object reader: all inherited `GIT_`
variables are stripped, global/system configuration, hooks, fsmonitor, lazy fetch
and replacement objects are disabled and protocols are denied. The comparison
invokes no diff driver or textconv. No clean/smudge or attributes conversion is
used. Each Git read is limited to 15 seconds; aggregate checks allow 1,100 Git
calls, 16 MB observed bytes, 512 tracked files, 1,024 filesystem entries and 60
seconds checked between reads (an in-flight read can take its remaining 15-second
bound). Each complete tree inventory additionally permits at most 512 tree
visits and 32 directory levels; all tree reads share the Git operation/byte/time
budgets. Individual tracked files are capped at 1 MB; repair blobs and individual
raw tree objects at 262,144 bytes.

One atomic coordinator write advances task head and material epoch, advances an
existing legacy disposition epoch, clears reviewers/reviewed SHA/validation, and
retains the foreground receipt. The receipt references application, domain repair,
proposal and bundle, with an immutable comparison witness containing commit/diff
hashes, exact blob IDs/hashes, paths and modes. It consumes one existing receipt
slot and checks both canonical 900 KB and durable 1 MB serialization budgets
before writing. Pause blocks new adoption; exact historical retry stays read-only.
A second operation cannot adopt the same application again.

Status and replay validate those retained Git objects (including both complete
tree hierarchies) and the witness rather than
the current checkout. Later heads or dirty bytes do not reapply adoption, advance
epochs, or acquire fresh credit. Missing/corrupt retained objects, artifacts or
references produce UNVERIFIED, including historical replay. Objects must therefore
remain available in the assigned repository. No object pinning/GC policy is added.
The controller cannot authenticate who authored a commit from Git metadata;
operator creation is an operating requirement, not a cryptographic identity claim.
Exclusive cooperative ownership is still required against concurrent filesystem
changes. Successful adoption reports `REPAIR_HEAD_ADOPTED_UNREVIEWED`; fresh
execution and independent review remain required.

### Prepare the adopted head for independent review

Submit the v1 foreground envelope with `action: "prepare-repaired-review"` and
`payload: {"adopt_operation_id": "<foreground adoption ID>"}`. The original owner
must remain Implementing with the same full worker identity, live reservations,
cycle, correction scope and post-adoption material epoch. A later generation,
changed head, paused dispatcher or second preparation of the same adoption is
refused. The operation grants no reviewer, model, execution, commit or lifecycle
authority.

Preparation checks the configured origin and complete clean checkout using the
adoption reader, then captures a **direct original task base → adopted head**
packet. This includes implementation changes outside the repaired files. Both
commits and every root/descendant tree in their inventories are independently
hash-authenticated, including the original base that adoption did not inspect.
The packet's changed path set, statuses, before/after modes, object IDs, byte
counts, hashes and content must equal the raw-tree-derived comparison and
hash-authenticated blobs. Capture output alone is insufficient. Nonregular tree
entries fail closed. The textual diff is supplementary; authenticated file sides
are the source evidence. Current origin and checkout are checked again after
packet retention; cooperative ownership is still required against concurrent
changes after that observation.

The new obligation list is the sorted union of baseline IDs, fresh packet IDs
and IDs from **every** prior generation. More than 32 fails closed with no waiver.
All findings, reports and dispositions remain in history. The normal
`review-evidence.apply(begin)` API creates its ordinary domain receipt using
`fgreview.<SHA256(canonical full foreground request)>`. This namespace is
reserved. Structural reverse-link validation in the evidence API requires the
matching foreground receipt, adoption and generation without importing the
foreground dispatcher or recursively replaying it. The dispatcher additionally
validates the retained packet and forward links.

The canonical packet is retained at the private state root's
`review-packets/<digest>.json`, with mode `0400`. File, containing directory and
parent-directory fsync complete before task commit, including an existing-object
retry. Publication failure or an invalid existing object blocks the task write.
A failed task write may leave a valid content-addressed packet; deterministic
retry validates it and completes durability before trying the single task write
again. Ambiguous task-write outcomes require reading retained history.

One coordinator write persists the new generation, normal begin receipt and
foreground receipt, advancing revision once. The canonical 900 KB and serialized
1 MB task budgets apply; packet actual/canonical bytes are capped at 8 MB and
changed files at 200. Capture reads without an explicit limit (including the full
diff) retain the packet reader's 8 MB output ceiling; explicit per-read limits,
including the 256,000-byte blob ceiling, remain in force.
Capture, authenticated comparison and both current checks
share adoption's 16 MB / 1,100 Git-call / 60-second budget (a read already in
flight retains its 15-second bound). Historical packet verification uses bounded
raw-object reads, never a new capture or today's policy. Exact replay after later
heads, pause or dirty checkout returns the historical domain result without
mutation. Missing packets, objects, domain/adoption links or substituted content
produce UNVERIFIED. Retained Git objects must remain available; no GC pinning is
introduced.

### Next boundaries

Status considers the prepared owner correction before unresolved review findings:

| Retained/current state | `next_action` |
|---|---|
| Rework without prepared correction | `PREPARE_CORRECTION` |
| Prepared correction in Rework | `ORIGINAL_OWNER_RECLAIM` |
| Original owner reclaimed, still Claimed | `ORIGINAL_OWNER_IMPLEMENTING_REQUIRED` |
| Original owner Implementing, current correction, no proposal | `ADMIT_OWNER_PROPOSAL` |
| Latest current owner proposal admitted | `COLLECT_OWNER_PROPOSAL` |
| Latest current proposal yielded a retained bundle | `COLLECTED_OWNER_BUNDLE_REQUIRES_GUARDED_APPLY` |
| Latest current proposal reported inability | `OWNER_PROPOSAL_UNABLE_REQUIRES_OPERATOR` |
| Pending domain repair or foreground finalization, including while paused | `REPAIR_RECONCILIATION_REQUIRED` |
| Adopted current repair head without a newer current review generation | `PREPARE_REPAIRED_REVIEW` |
| Prepared fresh generation with missing coverage or inherited unresolved findings, without current findings/persists report | `FRESH_EXECUTION_AND_INDEPENDENT_REVIEW_REQUIRED` |
| Unresolved current-generation finding or unresolved finding whose latest current disposition is persists | `OWNER_REWORK_ADMISSION_REQUIRED` |
| Owner/correction scope, head, generation, lease, checkout or admitted source context no longer matches | `OWNER_PROPOSAL_CONTEXT_RECONCILIATION_REQUIRED` |

Status uses the latest admission for the current correction, not an older bundle
or an earlier cycle. Settled repair history points to commit/execution/re-review
or explicit reconciliation. A newer current review generation clears historical
`NOT_APPLIED_OBSERVED` even at the same HEAD; `APPLIED_UNREVIEWED` additionally
requires a changed committed head. A newer but stale generation clears neither.
Normal review status then resumes. A later refutation or fix of a current finding
or persists disposition removes that finding's rework signal without deleting
reports. Other inherited findings still awaiting current dispositions keep the
fresh independent-review boundary. Terminal and readmission boundaries take
precedence; pending repair takes precedence over dispatcher pause. Status is a
read-only boundary projection, not authorization to execute
the suggested step; mutations recheck all domain guards.

## Pause and recovery

Pause is **dispatcher-scoped**: it refuses new collect/accept/prepare, owner-proposal
admission/collection, application and head-adoption operations
through this command. It does not terminate a worker, release capacity, change
task lifecycle or disable other installed entrypoints. Resume only clears that
gate, after current identity/revision checks; it does not re-admit lost ownership.
The first mutation sets `foreground_initialized` alongside the control ledger.
Missing control history on an initialized task is UNVERIFIED, never implicitly
resumed. This detects partial record loss, not coordinated rollback or deletion
of both the initialization marker and its ledger.
Pause/resume remain available with a pending repair and affect no worker, lease
or lifecycle state. Explicit reconciliation is also available while paused.
Missing workers, unresolved execution or uncertain reservations cannot be
automatically repaired by this dispatcher. The foreground retention-only validator
calls existing domain/artifact validators directly to read pending history;
settled checks on other mutation entrypoints are unchanged.

Exact operation retry returns its historical receipt without a new revision or
repeated domain mutation. A pause receipt replay does not re-pause a subsequently
resumed task. Changed reuse, recreated task, stale new operation, invalid evidence
or unknown fields fail closed. Retained receipts resolve to the actual domain
operation or correction and are checked before status/replay. Proposal receipts
reference the exact `repair_proposals` admission key and reproduce the admission
or collection result from validated domain history, including inability outcomes.
Missing/substituted admissions, collections, runtime artifacts or rendered bundles
make status and exact replay UNVERIFIED. Replay during pause acknowledges history
without collecting again or changing the pause state. Foreground control and
requests retain schema version 1; existing v1 receipts keep their original shapes
and remain replayable without migration. Repair application/reconciliation history
lives in the separate version-1 `foreground_repairs` ledger (`applications` and
`reconciliations`). The domain operation ID is reserved as `fgrepair.` followed by
the SHA-256 of the canonical full foreground request, including task incarnation.
Links validate in both directions: a reserved domain intent without its foreground
application is UNVERIFIED, including when the entire foreground repair ledger is
missing. Public foreground requests cannot use the reserved prefix. Exact requests,
incarnations, domain bundle/worker bindings and nonoverlapping revision history
are checked before status or replay. These checks detect partial loss/substitution,
not coordinated rewriting of all task history by a principal able to edit it.
Receipt capacity
is 64 across control, applications and reconciliations, with at most three
applications; the task payload retains the existing 900KB bound. Application
requires capacity for its entry and at least one explicit recovery observation,
and projects concrete normal-completion and all possible recovery outcome records
before the first intent persist or target write. These size-only projections use
the shared coordinator serializer (sorted, indented, ASCII-escaped JSON plus
newline, 1MB durable limit), as well as the 900KB canonical limit. They include
writer revision/timestamp fields, final application metadata and a recovery
request/receipt with maximum permitted operation-ID/revision lengths. They never
pass synthetic phases through domain validators. Actual writes still validate
their real retained history and both size bounds. This replaces the guessed
20KB margin; later mutations can still consume byte capacity and must pass their
own guards.
Status `receipt_count` reports the combined control, application and reconciliation
entry count used by admission checks.
While a foreground application remains pending, every mutation except a
reconciliation targeting a pending application must leave the final receipt slot
available. At 63 entries, pause/resume and reconciliation of a completed older
application refuse without changing task history; status and exact replay remain
available, and reconciliation of the pending application can use entry 64.
Reconciliation observations still
consume the finite budget: a partial/unknown observation in the final slot fails
closed on subsequent new requests rather than evicting history or granting
automatic recovery.
No automatic eviction
of replay protection occurs.

The command holds the existing coordinator lock and calls lock-free domain APIs,
then publishes ordinary domain changes and dispatcher receipts in a single task
write. Application uses the engine's two writes as described above; explicit
reconciliation uses one write. The lock stays held throughout application.
Domain artifact publication may precede task commit; an orphan artifact grants
no claim. An ambiguous file/fsync result is UNVERIFIED. No network or candidate
code executes under the lock. Bounded artifact validation may still delay other
writers; this is not a general high-throughput scheduler.

## Honest outcomes and operating boundary

Exit 0 means the requested local operation completed or its historical receipt
was recovered, or a validated status projection was returned. Exit 3 means the
operation cannot be established or a repair is pending/partial/unverified; usage errors exit 2. `candidate_ready`,
`execution_credit`, `delivery_credit`, and current applicability of historical
acknowledgments are false. A green local protocol result is not a green PR.

The production-path integration tests use actual task reservations, Git fixture
checkouts, artifact storage and fresh CLI processes, with the test-mode bypass
unset. Runtime review and owner-proposal bundles are synthetic and labelled
accordingly. The tests include review → Rework → correction → original-owner
reclaim → proposal admission/collection, inability, exact paused replay, stale
context, role/source substitution and evidence loss. Application coverage includes
real two-file CLI application, paused replay/reconciliation, exact two-write
linkage, and failures before the first target, between targets, after all target
writes before final persistence, and at first persistence. Only failure seams
are injected; production validators, reservation checks and repair filesystem
operations run unchanged. The fixtures verify no automatic rollback or repeated
target writes and enforce the fresh-head requirement after application.
They measure composition/replay/pause/error handling, not model review quality.
Run the fixture from a writable sandbox copy when checking package hygiene:
read-only mounts can silently suppress Python cache writes. The fixture sets
`PYTHONDONTWRITEBYTECODE=1` for its child processes because the coordinator's shell
entrypoint starts a new Python interpreter without inheriting the test parent's
`-B`. An end-of-test inventory assertion checks that the installed canonical
package gained or lost no paths; the normal preflight manifest check remains strict.

On an unexpected foreground CLI exit, the fixture emits a bounded structural
diagnostic from that same invocation: exception type and installed-code
file/function/line, plus worker-alive/start-match booleans when available. A
test-local interpreter shim keeps the public `run.sh` path and observes its
Python main with tracing; it never retries a request or changes its expected
exit. Exception messages, task contents, runtime stdout/stderr, host paths and
worker identity values are withheld. Production failure responses are unchanged.
Executable fixture shims require sandbox `TMPDIR=/work/tmp`, not no-exec `/tmp`.

Next rollout gates remain: explicit model/sandbox provisioning, controlled local
effect dispatch and lifecycle operation replay, longer foreground continuation,
live PR/check collection, and human approval. The human-approved delivery lane
does not require the parked App or automatic approval/merge functionality.
