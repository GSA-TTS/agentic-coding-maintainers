# Durable PR observations

The existing foreground monitor optionally retains a private SQLite journal:

```bash
run.sh monitor --task-id CLAIMED_MONITOR --config /trusted/orchestrator.json --durable
run.sh monitor --task-id CLAIMED_MONITOR --config /trusted/orchestrator.json --durable --loop
run.sh monitor --config /trusted/orchestrator.json --status
```

Direct Python invocation must use `python3 -I -B`. Polling requires the existing
process-bound monitor task/global slot and the common poll lock. Status is a
read-only as-of view and requires no worker. It does not create missing state.
There is no daemon installation or background persistence of execution. Process
exit stops monitoring; a persisted poll does not prove uptime.

## Store and candidate semantics

`.orchestrator/monitor/history.sqlite3` retains poll intents, per-source coverage,
material PR observations and current candidate references. Task JSON remains the
only task/admission/lifecycle authority; no journal entry grants work or a GitHub
effect. A stable reference includes store identity, repository, PR number and
observed generation. A changed head/draft/review/check summary/presence produces
a new generation; A→B→A creates three revisions. Titles, authors, bodies, comments
and raw tool stderr are excluded. No model call occurs during monitoring.

An absent previously observed PR remains with `NOT_IN_OPEN_SET`; the monitor
does not infer merged, closed, delivered or ineligible. Removing a source from
configuration marks its candidate projection OUT_OF_SCOPE without deleting it.
Failure preserves candidates with unverified source coverage. A successful empty
snapshot differs from failure. Project coverage is recorded independently, so
a failed Project query does not discard valid repository observations.

The live transport is read-only `gh pr list` and optional `gh project item-list`.
The 500-open-PR ceiling is explicit; reaching501 is UNVERIFIED. GitHub CLI handles
pagination internally, so OBSERVED means a bounded **visible open set**, not a
page-attested exhaustive intake denominator or atomic GitHub snapshot. Review
requests on older/closed PRs remain the separate #29 intake/evaluation scope.
Summary checks are not named-check/producer or approval evidence.

## Restart, replay and failure

Under the common poll lock, the monitor commits STARTED plus all expected
sources before network calls. Network work has a shared120-second budget and
30-second per-invocation ceiling; combined output is bounded to5MB per command.
Unattempted sources report NOT_ATTEMPTED. After config/owner revalidation, source
results and candidate updates commit in one transaction. The printed result
follows commit. Identical finalization returns the original result; conflicting
replay is refused. Older/interrupted attempts cannot insert or overwrite after
a newer successful empty snapshot. Local poll sequences order commits; wall
clock or GitHub updatedAt is not used as an authority for freshness.

An unfinished poll becomes INTERRUPTED on the next admitted poll, preserving
prior candidates. This does **not** authorize stale `poll.lock` removal or worker
takeover: reconcile ownership explicitly. A lock contender reports failure but
does not modify shared coverage/checkpoints. Poll configuration or ownership
changes discard candidate updates and record a coverage gap.

Exit0 means all configured sources were observed and committed (CHANGED or
CURRENT). Exit3 means UNVERIFIED, contention, unavailable storage/coverage or
capacity exhaustion. Status returns AS_OF_POLL only for the last completed
fully observed matching source set; it never claims present network health.
CLI usage errors exit2. The legacy JSON checkpoint path remains available
without `--durable`, but is neither imported into nor authoritative over SQLite.
History starts with the first journal poll; no earlier coverage is invented.

## Privacy, corruption and retention limits

The journal directory/files must be current-user owned and private; database
and sidecars must be regular single-link files, not symlinks. Private-parent
checks are check-then-use defenses, not a sandbox against same-user tampering.
SQLite uses rollback journaling, FULL synchronous writes, short lock waits and
bound SQL values. Unsupported/corrupt schemas are refused, never recreated as
empty history. Fingerprints and structural references detect inconsistent
retained observations but do not authenticate the controller against its owner.

Hard ceilings:10,000 polls,50,000 material events,10,000 current candidates and
64MB database. At capacity the monitor fails closed, preserving records rather
than dropping pending candidates. No automatic pruning/migration is included.
Archive/rotation requires an explicit operator procedure that preserves current
candidate identities; absence of that procedure is a rollout limit. Do not use
this journal as a long-running production service without capacity planning.

This is the observation part of M02/#67 and M09/#74. Durable effect outbox,
authoritative cross-store task-mutation receipts, automatic review dispatch,
supervised restart and GitHub writes remain later work.
