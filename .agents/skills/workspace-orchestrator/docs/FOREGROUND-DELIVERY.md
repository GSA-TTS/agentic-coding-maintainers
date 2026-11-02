# Foreground delivery for an admitted task

`run.sh foreground-delivery TASK` reports retained progress and a candidate next
action. With `--request REQUEST`, it executes one bounded local step. It does not
discover tasks, claim workers, invoke a model, provision a sandbox, apply a patch,
change Git refs or publish a PR. The independently installed controller remains
outside candidate worktrees; tests of candidate controller code run in isolation.

This first production composition replaces manual translation between the existing
review collection, review acceptance and correction-preparation entrypoints.
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
foreground step can prepare the bounded correction. The owner still reclaims
its lane before repair, and fresh commit/execution/re-review are separate guarded
operations. Full claim coverage is not validated tests, current CI or approval.

## Pause and recovery

Pause is **dispatcher-scoped**: it refuses new collect/accept/prepare operations
through this command. It does not terminate a worker, release capacity, change
task lifecycle or disable other installed entrypoints. Resume only clears that
gate, after current identity/revision checks; it does not re-admit lost ownership.
Missing workers, unresolved execution/repair or uncertain reservations cannot be
automatically repaired by this dispatcher.

Exact operation retry returns its historical receipt without a new revision or
repeated domain mutation. A pause receipt replay does not re-pause a subsequently
resumed task. Changed reuse, recreated task, stale new operation, invalid evidence
or unknown fields fail closed. Retained receipts resolve to the actual domain
operation or correction and are checked before status/replay. Receipt capacity
is 64; the task payload retains the existing 900KB bound. No automatic eviction
of replay protection occurs.

The command holds the existing coordinator lock and calls lock-free domain APIs,
then publishes the domain change and dispatcher receipt in a single task write.
Domain artifact publication may precede task commit; an orphan artifact grants
no claim. An ambiguous file/fsync result is UNVERIFIED. No network or candidate
code executes under the lock. Bounded artifact validation may still delay other
writers; this is not a general high-throughput scheduler.

## Honest outcomes and operating boundary

Exit 0 means the requested local operation completed or its historical receipt
was recovered, or a validated status projection was returned. Exit 3 means the
operation cannot be established; usage errors exit 2. `candidate_ready`,
`execution_credit`, `delivery_credit`, and current applicability of historical
acknowledgments are false. A green local protocol result is not a green PR.

The production-path integration tests use actual task reservations, Git fixture
checkouts, artifact storage and fresh CLI processes, with the test-mode bypass
unset. Runtime review bundles are synthetic and labelled accordingly. The tests
measure composition/replay/pause/error handling, not model review quality.

Next rollout gates remain: explicit model/sandbox provisioning, controlled local
effect dispatch and lifecycle operation replay, longer foreground continuation,
live PR/check collection, and human approval. The human-approved delivery lane
does not require the parked App or automatic approval/merge functionality.
