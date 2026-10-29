# Candidate-to-review-task association

`run.sh bind-candidate TASK --config CONFIG --request REQUEST` associates a
durable observed PR generation with an **already-created review task**. This is
provenance, not admission, scheduling, review completion or remote action authority.
Run the trusted installed controller; candidate copies are tested in isolation.

## Request and preconditions

```json
{
  "schema_version": 1,
  "action": "bind-candidate",
  "operation_id": "bind-review-42",
  "task_id": "review-42",
  "incarnation": "<task incarnation SHA-256>",
  "expected_revision": 3,
  "poll_seq": 7,
  "config_sha256": "<normalized monitor config SHA-256>",
  "candidate": {
    "store_id": "<32 lowercase hex characters>",
    "repo": "owner/repository",
    "number": 42,
    "generation": 2,
    "head": "<40 lowercase hex characters>",
    "fingerprint": "<material observation SHA-256>"
  }
}
```

The task incarnation is SHA-256 over canonical JSON of task_id, created_at and
the existing scope_token. It is stable through claims and lifecycle transitions,
but not a new global identity or protection against coordinated state rollback.
Canonical JSON here uses sorted keys, compact separators, ASCII escaping and no
trailing newline. Config hashing uses the existing monitor's normalized config,
including its `project: null` when absent. Candidate identities come from the
validated journal, never a PR title or model-generated path.

A new binding requires kind=review, state Ready/Claimed/Reviewing, exact task
revision/incarnation and PR tracker identity, matching repository/head, no
pending transition, valid scope/worker reservations, and a clean assigned review
checkout at that head. The candidate must be the latest retained generation in
the configured source set and present in the visible open PR set. The latest
poll must match the requested sequence/config and have successful target-repo
coverage. An unrelated Project/repository failure remains disclosed in the
overall poll status and does not erase the target's measured observation.

No age threshold or live GitHub query is implied. This is an explicit binding to
an **as-of-poll** observation; `live_github_freshness` remains UNVERIFIED. Draft
PRs can be reviewed. Check/approval summaries do not authorize integration.

## Task authority and duplicates

One optional `candidate_binding` stores the exact request, request hash,
historical observation/coverage and result in the same atomic task write. Base
task readers validate the extension whenever present. No lifecycle, ownership,
source head, review finding or worker capacity is modified. The result explicitly
grants no readiness or remote authority. Existing tasks without the field retain
their schema and need no migration.

Each task incarnation can receive one immutable association. A changed request
or second operation cannot replace it. Separate explicitly admitted QA/security
tasks may reference the same candidate; this command does not claim exclusive
ownership of a PR or deduplicate review purposes. Future admission/scheduling
must define that policy rather than infer it from this provenance link.

## Commit and acknowledgment recovery

The lock order is monitor poll.lock → coordinator lock → short SQLite
transaction. An initial coordinator-only receipt lookup never waits on poll.lock.
No network work occurs under these locks, and no SQLite transaction spans a
task-file write. Contention never authorizes stale-lock takeover.

Task replacement and its fsync barrier are the authoritative commit point. Only
after reading that committed receipt does the command attempt a journal
acknowledgment. A crash after the task commit but before acknowledgment is safe:
an exact retry returns the original result without a second revision and repairs
the acknowledgment where possible. A prior uncertain write is inspected and its
file/directory durability barrier re-established on replay, not rolled back.

Replay precedes fresh-source/config checks. A moved PR, completed task, missing
journal or changed config cannot erase an established association. The returned
result is historical; it is not a fresh current-head permission. Journal failure
is reported separately as `journal_ack: UNVERIFIED`. A missing task or corrupted
task receipt is never reconstructed from an acknowledgment. An absent journal
is not recreated by this command.

The first acknowledgment transaction extends a validated journal from version1
to version2 with a bounded advisory `binding_acks` table; store identity and all
observation history are preserved. Monitor readers/writers accept both versions.
Status never performs migration and reports task admission UNMEASURED because it
does not read task authority. Old v1-only installations will refuse the upgraded
database; rollback requires the original journal backup or a compatible version,
not blind replacement. No automatic downgrade or receipt pruning is provided.

Exit0 means task binding committed/replayed, with acknowledgment separately
qualified; exit4 is a verified refusal; exit3 is unavailable/ambiguous evidence
or contention. CLI usage errors exit2. This is one task-authoritative dual-write
operation, not the complete M02 service, generic operation engine or remote outbox.
