# Bounded Nexus research workflow

These are illustrative tool calls and decision rules, **not an execution log**.
No Nexus discovery, panel vote, live source research, or impact run is represented
as completed. The offline validator and fixtures need no Nexus runtime.

## Admission and budgets

The primary orchestrator owns admission, reservations and reconciliation. Before
dispatch, verify the task, owned worktree/scope and live capacity. Count all active
workers, monitors, nested experts and **every concurrent voter seat** against the
workspace limit of **six workers**, with at most **two implementation lanes**.
The caller/primary and other active work consume capacity too. Reserve seats
through the existing workspace reservation process before invoking a tool; no
tool's internal fan-out is assumed to reserve them for you. Do not edit state
directly or silently take over stale reservations.

A default seven-seat panel cannot fit within this cap. A three-seat quick panel
is permissible only with three explicit free seat reservations, plus caller and
other activity accounted for, and a verified guarantee that this call cannot
escalate or create unreserved extra workers. If fan-out/escalation cannot be
bounded, do not dispatch: use serial reserved reviews or report unverified.
Avoid development pipelines whose automatic panel escalation exceeds capacity.
Never spawn nested workers merely because the Nexus tool allows it.

Set the attempt budget before research, for example: maximum two plan revisions,
two consensus attempts total (retries count), one discovery query of five results,
one registry query of five results, 10,000 model tokens total, five minutes per
attempt and ten minutes total foreground time. These are caller-enforced limits,
not a claim that every tool implements token/time enforcement. Where accounting
or safe cancellation is unavailable, stop at that boundary as unverified rather
than launch an unbounded call. Polling consumes the same foreground time budget.
Do not claim a call was cancelled until its terminal status is observed.

## Example plan attempts (placeholders, not authority claims)

Use Nexus to inspect existing leads and develop a bounded research plan, not to
decide legal truth. Example read-oriented inputs:

```json
{"action":"search","query":"SYNTHETIC scoped rule authority leads"}
```

Pass that input to `research_query`; locally cap reviewed hits at five if this
tool exposes no limit. A registry hit may be stale or untrusted and is not a
primary-source citation. For discovery, one example `research_discover` input:

```json
{"topic":"SYNTHETIC editorial authority research methods","source":"all","maxResults":5}
```

Research discovery searches research venues, not a complete official-law index.
Manually locate the appropriate official law/FR/EO/OMB/owner publications under
METHOD.md. Do not call `research_add`, `research_add_source`, catalog approval,
issue filing or any mutating operation as an automatic side effect.

Draft a plan with scoped rule IDs, questions, proposed primary publishers,
quote/version/date checks, applicability and exceptions, conflict/supersession
checks, missing access, owner/legal-review needs and impact evidence gaps.
After reserving a bounded three-seat panel, an illustrative `consensus_vote`
input is:

```json
{
  "proposal": "Review this SYNTHETIC research plan for completeness only, not legal truth: inspect operative primary text, dates, applicability, exceptions, supersession and conflicts; require owner/legal review and fixed-byte real-engine impact evidence. Missing evidence stays unverified.",
  "quickMode": true,
  "strategy": "unanimous",
  "errorPolicy": "absolute_quorum",
  "dispatch": "async"
}
```

If presenting named alternatives, declare them in `options`; do not mistake
approve/reject agreement for agreement on an alternative. Verify the tool's
actual seat count, assignments and evidence coverage. A simulated vote, errored
seat, uninspected summary or missing assignment/evidence cannot constitute a
verified plan review. Consensus reviews methodology, not the truth of law.

For attempt 1, capture unresolved objections and evidence gaps. Revise only the
plan, then use attempt 2 if capacity and budget remain. After two attempts stop;
unresolved questions remain unverified. Never iterate until a desired approval
appears or count a majority as independent legal review.

## Async and degraded capture

On an async response preserve the actual job ID in approved runtime evidence;
poll `get_job_result({"jobId":"<returned-id>"})` in the foreground until a
terminal status or budget boundary. Pending is not success. Check failure,
cancellation, abandoned status, partial/redacted/truncated evidence and unmeasured
coverage explicitly. Request `cancel_job` at a timeout boundary where available,
then reconcile termination before releasing seats; if still running, report it
and retain reservations for the primary to reconcile. No background polling or
daemon is permitted. Do not rerun a pending job just because it is slow.

Capture attempts in approved local runtime notes, never commit raw Nexus records
or private source material here. A suggested summary shape (not actual output):

| Field | What to capture |
| --- | --- |
| Attempt/time/budget | Plan revision, UTC time, elapsed time, usage measured/unmeasured, remaining caps. |
| Tool/job status | unavailable, pending, complete, failed, cancelled; job ID if returned. |
| Reservations | Caller, other active workers, all reserved voter seats; measured fan-out. |
| Review evidence | Actual assignments, coverage, seat errors/abstentions, objections and whether the plan was inspected. |
| Source access | Which official artifacts were inspected, unavailable, stale or conflicting. |
| Outcome | Plan-review result separately from metadata verdict and unresolved legal/impact questions. |
| Next action | Owner and foreground re-review trigger/due date; no automatic remote write. |

If Nexus is unavailable, record the actual unavailable status and proceed only
with explicitly admitted manual/offline work. Do not invent a plan attempt,
approval, source discovery result, or successful tool transcript. Event-triggered
and monthly review are explicit foreground sessions; stale notes are not proof
of ongoing monitoring. No GitHub write is automatically authorized by this skill.
