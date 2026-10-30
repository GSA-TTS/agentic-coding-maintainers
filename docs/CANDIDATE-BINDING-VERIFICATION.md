# Candidate/task reconciliation verification — 2026-10-29

AI-assisted local reconciliation slice after PR83. It connects an observed
candidate to an already-created fixed-head review task, without admitting,
claiming or dispatching new work.

## Measured isolated behavior

Nineteen tests ran in the approved network-off Docker sandbox using actual
temporary Git repositories, coordinator task JSON and SQLite transactions.
The public CLI test commits one binding revision, transitions the task to a
terminal state, and replays the exact receipt without changing task bytes.
Other cases exercise:

- Correct task/candidate identity and no lifecycle/capacity/readiness changes.
- Historical replay after later task revisions and changed PR observations.
- Task commit followed by failed/missing acknowledgment, then repair on retry.
- Injected process interruption after task commit and before acknowledgment.
- Simulated uncertain task-file durability, followed by explicit replay barrier.
- Poll-lock contention, including fsync failure before contended replay.
- Task corruption between receipt lookups and fixed-head corruption.
- Wrong incarnation, conflicting request and second-binding refusal.
- Missing journal/config without creating replacement history.
- Replaced journal identity and orphan acknowledgment refusal.
- Populated v1→v2 acknowledgment-table migration preserving observations.
- SQLite-denied migration metadata update rolls back table/version changes while
  retaining the authoritative task receipt.
- Read-only journal status does not mutate history or claim task admission.

These are deterministic local integration/fault-injection tests. They do not
claim a power-loss durability benchmark, daemon restart qualification, or live
GitHub/current-head coverage. The preceding journal capture replay remains its
separate evidence; this operation requires the explicitly selected as-of poll.

## Review-driven changes

Parallel architecture and security analysis preceded implementation. Fixed-head
QA/security reviewed `a7500fc1f8e5cee3ba6bdf8a40561c64df1f5166` and found that
cached replay success could escape before a durability barrier or after a failed
second task read, and that retained task-head corruption was not rejected.
Repairs place the barrier under the first coordinator lookup, confine fallback
success to journal-lock availability, preserve task-authority errors, and require
the bound review task's fixed head to match its candidate. Added tests cover all
reported paths. Subsequent re-review is recorded with the PR evidence.

## Boundary and next step

Each task has one immutable binding. Multiple explicitly admitted QA/security
tasks may reference the same PR generation; this link is provenance, not a
unique scheduling reservation. Task incarnation derives from existing creation
and scope-token identity. This is not protection from coordinated rollback of
all state copies.

The result is CANDIDATE_BOUND with journal acknowledgment separately reported.
Candidate readiness and remote authority remain false; live GitHub freshness is
UNVERIFIED. No remote write, model call, service/daemon or new credential is used.
Generic authoritative operations, automated candidate admission, live-source
freshness, and the GitHub effect outbox remain subsequent M02/M03 work.
