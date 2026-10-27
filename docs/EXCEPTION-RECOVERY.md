# Exception recovery — shadow-mode first slice

`scripts/plan-exception.py` is a bounded, deterministic, **offline** classifier
for typed exception evidence. It does not fetch GitHub, run measurements,
change task state, file issues, approve/merge a PR or call a model. It outputs
one suggested next action as JSON and always reports `current_verdict:
"UNVERIFIED"`, `mode: "SHADOW_ONLY"`, and `execution_performed: false`.

```bash
python3 -I -B scripts/plan-exception.py \
  --attempt-ledger /absolute/private/attempts.jsonl \
  < private-sanitized-snapshot.json
```

The v1 snapshot has exactly these fields: `schema_version: 1`; opaque
`task_id`; `blocker` in `PARTIAL_WRITE`, `STALE_HEAD`, `POLICY_DECISION`,
`CI_OUTAGE`, `MISSING_PROVENANCE`, `CODE_BUG`, `UNKNOWN`; full 40-hex or null
`task_head_sha` and `evidence_head_sha`; `evidence_coverage` in `complete`,
`partial`, `none`; `observed_at` (UTC);
`operation` in `local_read`, `remote_read`, `remote_write`; optional allowlisted
`measurement` (`check_status`, `head_identity`, `source_provenance`,
`worker_liveness`); boolean `policy_authorization` and
`independent_work_ready`; and `write_settlement` in `not_attempted`, `unknown`,
`confirmed`. No raw issue text, URL, reviewer name, hostname, token or command
*field* is accepted. `task_id` is a syntactically bounded opaque string, **not
a secret detector**: a caller must sanitize IDs before submitting a snapshot,
and must not place tokens, PII or private hostnames into them. The ID is echoed
in the shadow output for local correlation. The input is capped at 8 KiB; unknown fields, wrong types and
malformed evidence return `UNVERIFIED` (exit 3), not a guessed action.

An additional required `--attempt-ledger /absolute/private/attempts.jsonl`
is read before planning. Its parent must be current-user-private, its file
regular/private and non-symlinked, and it is capped at 128 KiB / 1,000 records.
Each JSONL line has exactly `schema_version: 1`, a unique opaque `attempt_id`,
opaque `task_id`, full `head_sha`, allowlisted `measurement`, `outcome` in
`complete`/`unverified`, and UTC `recorded_at`. Records must be timestamped in
append order and not later than the supplied snapshot. The planner derives
`attempts_for_head` for the matching task and SHA; a changed head gets a fresh
budget. A missing, corrupt, symlinked, wrong-permission, or partial ledger
returns `UNVERIFIED` (exit 3). An empty private ledger is valid evidence of
*zero recorded* attempts, not proof of zero real-world attempts. No writer or
retry executor is added by this change.
Head-budgeted diagnostics require a measured `task_head_sha`; a null head
cannot match any record, so treating it as a fresh budget would be fail-open.

## Priority of recommendations

1. A possibly completed write: `RECONCILE_WRITE_READ_ONLY`. Never blind retry.
2. Unapproved remote write: `HUMAN_AUTHORIZATION`.
3. Head mismatch: `REMEASURE_HEAD_READ_ONLY`; SHA-A evidence cannot certify B.
4. Policy hold: `HUMAN_POLICY_DECISION`.
5. CI outage: `DEFER_CI_MEASUREMENT`, or `REVIEW_INDEPENDENT_WORK` when a
   separate ready case was supplied. Neither grants this check a green result.
6. Complete, head-bound code failure: `OWNER_REWORK_REVIEW`.
7. Missing provenance with an allowlisted measurement and remaining budget:
   `MEASURE_SOURCE_READ_ONLY`; other bounded diagnostics:
   `MEASURE_READ_ONLY`.
8. Exhausted diagnostic budget: recommend review of independently ready work,
   or `HUMAN_TRIAGE`. An exhausted task remains UNVERIFIED.

The private attempt ledger is **operator-controlled data**, not an authenticated
attempt history. It prevents accidental undercounting by this CLI, but a
caller able to rewrite it can still understate attempts; there is no sealed
writer, signed provenance, wall-clock backoff or live-read executor. A suggestion is
**not authorization**: a future executor must re-read live evidence and current
head, validate allowed operations, enforce budgets and per-action GitHub-write
authorization, and stop on uncertain write settlement. No automatic executor
is included in this slice.

The blocker and coverage fields are likewise **caller assertions**, not
independently corroborated diagnostics. A `CODE_BUG` suggestion is not proof
of a reproducible bug; `independent_work_ready` does not verify dependencies,
ownership, or PR review state. Invalid combinations (a read with write
settlement, a partial write not marked uncertain, or equal/missing stale
heads) refuse the entire snapshot. The planner never marks anything PASS.

Evaluate it in shadow mode first: compare classifications with a maintainer's
decisions on sanitized cases. Any false PASS or unauthorized-write proposal is
a rollout blocker. Measure wrong blocker categories, wasted read calls,
age of unresolved cases, and time to recommend independent work—not raw PR
counts or agent utilization. Nexus model commentary is advisory only; the
panel consulted during this design returned `no_quorum` because it could not
read repository artifacts, so it supplied **no approval evidence**.
