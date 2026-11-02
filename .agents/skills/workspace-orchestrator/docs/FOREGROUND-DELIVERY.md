# Foreground delivery for an admitted task

`run.sh foreground-delivery TASK` reports retained progress and a candidate next
action. With `--request REQUEST`, it executes one bounded local step. It does not
discover tasks, claim workers, invoke a model, provision a sandbox, apply a patch,
change Git refs or publish a PR. The independently installed controller remains
outside candidate worktrees; tests of candidate controller code run in isolation.

This production composition replaces manual translation between the existing
review collection, review acceptance, correction preparation and owner-proposal
admission/collection entrypoints. Owner proposals route through `repair-proposal.apply`.
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
findings. Applying a bundle, committing, executing and independently re-reviewing
remain separate guarded operations. This is proposal routing, not an autonomous
repair loop.

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
| Owner/correction scope, head, generation, lease, checkout or admitted source context no longer matches | `OWNER_PROPOSAL_CONTEXT_RECONCILIATION_REQUIRED` |

Status uses the latest admission for the current correction, not an older bundle
or an earlier cycle. Settled repair history points to commit/execution/re-review
or explicit reconciliation; once a new committed review generation exists, normal
review status resumes. Terminal, readmission and dispatcher pause boundaries take
precedence. Status is a read-only boundary projection, not authorization to execute
the suggested step; mutations recheck all domain guards.

## Pause and recovery

Pause is **dispatcher-scoped**: it refuses new collect/accept/prepare and owner-proposal operations
through this command. It does not terminate a worker, release capacity, change
task lifecycle or disable other installed entrypoints. Resume only clears that
gate, after current identity/revision checks; it does not re-admit lost ownership.
The first mutation sets `foreground_initialized` alongside the control ledger.
Missing control history on an initialized task is UNVERIFIED, never implicitly
resumed. This detects partial record loss, not coordinated rollback or deletion
of both the initialization marker and its ledger.
Missing workers, unresolved execution/repair or uncertain reservations cannot be
automatically repaired by this dispatcher.

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
and remain replayable without migration. Receipt capacity
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
unset. Runtime review and owner-proposal bundles are synthetic and labelled
accordingly. The tests include review → Rework → correction → original-owner
reclaim → proposal admission/collection, inability, exact paused replay, stale
context, role/source substitution, evidence loss and unchanged candidate files.
They measure composition/replay/pause/error handling, not model review quality.
Run the fixture from a writable sandbox copy when checking package hygiene:
read-only mounts can silently suppress Python cache writes. The fixture sets
`PYTHONDONTWRITEBYTECODE=1` for its child processes because the coordinator's shell
entrypoint starts a new Python interpreter without inheriting the test parent's
`-B`. An end-of-test inventory assertion checks that the installed canonical
package gained or lost no paths; the normal preflight manifest check remains strict.

Next rollout gates remain: explicit model/sandbox provisioning, controlled local
effect dispatch and lifecycle operation replay, longer foreground continuation,
live PR/check collection, and human approval. The human-approved delivery lane
does not require the parked App or automatic approval/merge functionality.
