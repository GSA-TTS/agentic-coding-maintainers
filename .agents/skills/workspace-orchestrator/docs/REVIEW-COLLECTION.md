# Controller-side review collection

`run.sh review-collect TASK --request REQUEST [--packet PACKET] [--bundle DIR]`
runs from the **installed controller**. Candidate copies must be tested in the
isolated execution environment. It uses the existing coordinator lock, ownership
reservations and task JSON. It adds no worker capacity, starts no model, grants
no GitHub action and applies no repair.

## Admission before dispatch

Create the source packet, begin a review generation, and assign a native-session
reviewer with a controller-generated `ses_…` identifier. Then submit:

```json
{
  "schema_version": 1,
  "operation_id": "admit-attempt-1",
  "expected_revision": 5,
  "action": "admit",
  "payload": {
    "generation": 1,
    "run_id": "attempt-1",
    "binary_sha256": "<64 lowercase hex characters>",
    "model": "provider/model",
    "agent": "bounded-reviewer",
    "cwd": "/review",
    "sources": {
      "/candidate/source.py": {"path_base64": "c291cmNlLnB5", "side": "after"}
    }
  }
}
```

Supply `--packet` with the exact packet bytes whose digest the current review
generation references. Source selections must name regular before/after blobs
in that packet. Selected source hashes are recomputed from captured contents.
Repository/object identity remains as qualified by the packet producer; this
collector does not independently fetch GitHub.

The result includes `admission_id`. Invoke the guest runner using the assigned
`--session ses_…`, exact binary digest, model, agent, working directory and
source paths and `--profile` pointing at the installed guest configuration. The
profile bytes are hashed before/after execution and must match the assigned
profile digest. This records supplied bytes, not proof of effective merged
configuration. An observed different session fails closed. The adapter alone does
not guarantee a session is new: the controller must use fresh attempt IDs and
private guest state. Do not pre-admit a run by guessing a later generated ID.

## Collection

Copy the guest output into controller-owned staging through the qualified
transport. Submit `action: collect` with payload `admission_id` and
`artifact_sha256`: a mapping containing exactly `receipt.json`,
`transcript.jsonl`, `session-export.json`, `stderr.txt`, and `export-stderr.txt`.
Pass the staging directory with `--bundle`. All artifacts are bounded regular
files (4 MB each) and symlinked paths are refused. The entire bundle is at most
20 MB. Packet capture has an 8 MB bound and requests a 100 KB bound.

The collector verifies the current generation/epoch/owner/assignment and
recomputes source-read/completion observations from the transcript and export.
Session, binary, model, agent, source hashes, reported summary and artifact
digests must match the admission. A zero exit or a model's self-description is
insufficient. Missing export, stale attempt, cancelled task, changed bundle,
changed summary or unknown state returns `UNVERIFIED`, exit 3.

`OBSERVATION_COLLECTED` certifies **retained internal consistency**, not an
authenticated process or complete review. Worker-provided artifacts could be
fabricated together. They still have `authenticity: UNVERIFIED`, and readiness,
execution and delivery credit remain false. Elevating authenticity requires a
separately qualified controller-owned launch/transport that workers cannot
impersonate. No reviewer findings are automatically converted into accepted
claim reports; that semantic normalization remains a controller responsibility.

## Persistence and recovery

Private, content-addressed bytes live at `.orchestrator/review-artifacts/`,
outside the candidate worktree. Artifacts are written/fsynced to exclusive
temporary files, then atomically linked at their content address without replacement,
then task JSON atomically stores their addresses, admission and operation result.
The task remains authoritative. If a crash occurs before the task write, leftover
unreferenced objects grant nothing. Interrupted temporary files do not block
retry. Retry may reuse identical complete bytes. A changed object at its content
address is refused rather than silently overwritten.

The exact same operation ID/request returns its prior result without advancing
the task revision. Changed reuse is refused. Retained references and receipts
are revalidated, including packet, assignment, bundle, verdict, mutation coverage
and chronology. Missing or changed evidence blocks replay rather than returning
a stale successful acknowledgment. Historical replay returns the historical
result; it is not a new current-head assessment or a fresh action grant.

There are at most 64 collection operations per task and a 900 KB serialized task
budget. Existing task JSON and legacy review claims remain intact. No migration
is performed; collectors only add state to admitted tasks that already use the
review protocol. The filesystem checks are single-user check-then-use defenses,
not protection from another process with the same OS identity. Keep accepted
state and artifacts outside worker mounts. No automatic cleanup or rollback
deletes retained evidence.
