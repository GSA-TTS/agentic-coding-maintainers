# Exception recovery — shadow-mode first slice

`scripts/plan-exception.py` is a bounded, deterministic, **offline** classifier
for typed exception evidence. It does not fetch GitHub, run measurements,
change task state, file issues, approve/merge a PR or call a model. It outputs
one suggested next action as JSON and always reports `current_verdict:
"UNVERIFIED"`, `mode: "SHADOW_ONLY"`, and `execution_performed: false`.

```bash
python3 -I -B scripts/plan-exception.py < private-sanitized-snapshot.json
```

The v1 snapshot has exactly these fields: `schema_version: 1`; opaque
`task_id`; `blocker` in `PARTIAL_WRITE`, `STALE_HEAD`, `POLICY_DECISION`,
`CI_OUTAGE`, `MISSING_PROVENANCE`, `CODE_BUG`, `UNKNOWN`; full 40-hex or null
`task_head_sha` and `evidence_head_sha`; `evidence_coverage` in `complete`,
`partial`, `none`; `attempts_for_head` (integer 0–100); `observed_at` (UTC);
`operation` in `local_read`, `remote_read`, `remote_write`; optional allowlisted
`measurement` (`check_status`, `head_identity`, `source_provenance`,
`worker_liveness`); boolean `policy_authorization` and
`independent_work_ready`; and `write_settlement` in `not_attempted`, `unknown`,
`confirmed`. No raw issue text, URL, reviewer name, hostname, token or command
is accepted. The input is capped at 8 KiB; unknown fields, wrong types and
malformed evidence return `UNVERIFIED` (exit 3), not a guessed action.

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

`attempts_for_head` is supplied by the caller; the planner does not yet verify
an append-only attempt ledger or enforce wall-clock backoff. A suggestion is
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
