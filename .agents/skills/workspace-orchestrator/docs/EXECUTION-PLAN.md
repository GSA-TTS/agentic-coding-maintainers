# Frozen execution requirements and current assessment

`run.sh execution-plan TASK` is an artifact-aware, read-only assessment. With
`--request REQUEST --packet PACKET --definition DEFINITION ...`, it admits an
operator-reviewed plan before dispatch. Definitions and requests must reside
outside candidate-controlled paths; a digest is identity, not approval.

## Admission

The task already owns an active slot and has a current review generation.
Provision the exact execution guests and approve their oracle definitions first.
Then supply a request with exactly:

```json
{
  "schema_version": 1,
  "operation_id": "freeze-tests",
  "expected_revision": 5,
  "action": "plan-execution",
  "payload": {
    "generation": 1,
    "obligations": {
      "correctness": [{"operation_id": "probe", "definition_sha256": "<64 lowercase hex characters>", "cases": ["positive", "negative"]}],
      "acceptance": [],
      "test-adequacy": [],
      "maintainability": [],
      "baseline-security": []
    }
  }
}
```

Obligation keys must exactly match the review generation, including specialist
obligations where present. Empty arrays explicitly mean NOT_REQUIRED for
execution; they do not mean the review obligation was assessed. Every case in
each selected definition must be included somewhere in the plan. No selection
is admitted after an execution in that generation. A changed selection requires
a new generation and fresh executions; retrying the exact plan is idempotent.

Definitions must bind the generation's commits and a single read-only worktree
mount. Every selected source file must match a regular after-blob in the captured
packet. Each case argv must explicitly reference such a guest source. This
syntactic check prevents unrelated commands accidentally obtaining source credit;
it does not establish that arbitrary code actually exercised its argument.
Oracle adequacy remains an independent design/review responsibility. Unchanged
context files are not yet supported by the packet selector.

The plan retains task/repository/owner identity, generation/material epoch,
packet/policy/commits, required operation/definition/case identities and hashes
of the installed controller modules. It uses the existing coordinator lock and
atomic task write, retains oracle bytes first, and shares the task evidence-size
bound. There is one plan per generation and at most 16 per task. No SQLite,
secondary lifecycle authority or state migration is introduced.

## Dispatch

On tasks with a plan, `execution-observe` refuses unselected operations or
definitions and checks the current plan/owner/controller before each dispatch.
Attempts record their plan origin. Missing origin ledgers cannot silently become
legacy execution. Observer-only legacy tasks retain their earlier limited
behavior but cannot acquire current planned-obligation credit.

Controller upgrades after plan admission yield UNVERIFIED until a new generation
and plan are admitted. The controller hash includes the relevant local modules;
it does not authenticate the interpreter, host or Docker daemon. Definitions
remain independently approved external inputs, never model-generated authority.

## Read-only assessment

Assessment reads task state before and after validation, refusing a changed
snapshot. It validates review claims/collection links and plan artifacts, then
each required settled observation. It rechecks definition-bound source bytes and
actual checkout HEAD. It requires the exact operation selected before dispatch,
matching controller digest and owner, complete retained streams, valid stop
evidence, original applicability and no recorded integrity loss.

Normal worker-slot release does not erase historical settled observations.
Cancelled/blocked tasks, changed ownership/source/controller, new generations,
unsettled guests, missing artifacts and corrupted evidence yield UNVERIFIED.
Recorded evidence loss cannot be cleared by restoring bytes or altering phase.
Read-only assessment detects current loss but cannot persist a loss event; use
explicit controller reconciliation to record a durable integrity failure.

Per obligation: PASS means all selected cases currently pass; FAIL means a
current required case demonstrably fails; UNVERIFIED means a required case
cannot be established; NOT_REQUIRED means explicitly no execution selection.
Case details retain gaps even alongside a failure. The execution summary exits
0 for a nonempty all-passing required set, 1 for failure, 3 for incomplete or
entirely unselected evidence. The separate review section may still be incomplete
or HOLD; execution PASS neither closes findings nor claims adequate tests.

`candidate_ready` and `delivery_credit` remain false. This command does not
authorize repair, review publication, approval, merge or controller promotion.
The practical positive result is current per-obligation evidence for the
controller to use in the later explicitly authorized workflow.
