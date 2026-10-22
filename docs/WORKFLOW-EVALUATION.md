# Workflow evaluation: measured state first

The aim is to improve **verified maintainer outcomes**, not maximize agent
activity. This is a small, operator-invoked, read-only evaluation loop. It
creates no GitHub issues, PRs, reviews, or state changes, and sends no evidence
or repository content to a model. The operator decides which recommendations to
adopt.

## V1: what is measurable now

```bash
python3 -I -B scripts/evaluate-workflow.py --workspace /path/to/maintainers
```

The JSON report carries its `as_of` timestamp, task count, state/kind counts,
and one row per recorded task: ID, kind, current state, age since creation,
age since last record write, current `rework_count`, and current unresolved
finding count. The input is the host-local `.orchestrator/tasks/` store and the
canonical state validator. No raw finding, PR body, private journal, secret,
worker identity, or free-text validation is emitted. Any malformed or unsafe
record makes the **whole** report `UNVERIFIED` (exit 3); an empty store returns
`coverage: no_evidence`, exit 3, never zero-work success. A nonempty store
reports `coverage: parsed_task_records`—not measured coordination health.
It does **not** reconcile reservation ownership, worker liveness, or GitHub.
Run the canonical state reconcile command separately before drawing an
operational conclusion.

Age since last write is **not** time in state. `Ready for human review` is
**not** verified completion or a merge. A current reviewer string is **not**
independent-review proof, and validation text is **not** a test pass. The report
explicitly lists unmeasured historical throughput, time in state, review
turnaround, outcome quality, monitor uptime and CI pass rate. Never compute
those from a mutable task snapshot or a single monitor checkpoint.

## Next: a bounded case-ledger pilot

Before adding a dashboard or automated issue filing, design a versioned,
sanitized **case ledger** with append-only transition/intake/outcome events.
Freeze the intake cohort and report numerator/denominator IDs, exclusions,
unknown coverage and snapshot time. Cases still open, blocked, cancelled or
abandoned remain in the denominator. Link a verified outcome to current-head
review, checks and a repository event; do not count PR creation, commits or
`Ready for human review` as completion. Classify substantive post-review rework
by reviewed SHA and changed SHA; preserve older review events when head changes.

For a four-week rolling intake cohort, consider these **paired** measures:

1. Intake coverage = eligible observed requests recorded / eligible observed
   requests (show all exclusions and missing sources).
2. Verified completions **and** still-open/blocked cases, by case type and
   intake cohort. Count only outcomes with current-head evidence.
3. Age from frozen intake to verified handoff, with unfinished ages beside
   completed-case latency; no completed-only average.
4. Cases needing substantive rework after independent review / cases receiving
   such a review. Show the three-cycle escalation count separately.
5. Evidence coverage = attempted handoffs with applicable checks, reviewed
   head and explicit disposition for unavailable evidence / all attempted
   handoffs. `UNVERIFIED` never counts as pass.

Collect **confirmed** 30-day escapes only after the follow-up window has
elapsed, and coarse operator-effort bands only if the collection cost is less
than the decisions they improve. An outage-adjusted waiting time requires a
separately evidenced CI outage interval; lack of checks is not a pause credit.

Run an operator-initiated weekly local reflection, initially with no model:
print the case IDs behind every number, oldest unfinished cases, missing
evidence, and at most three candidate changes. Monthly, compare an adopted
change with its next *comparable* cohort; reject unhelpful changes. If a model
later drafts recommendations, give it only sanitized aggregate data, mark its
recommendations unverified, and require a human to inspect the underlying
cases before filing an issue. Never auto-modify code or controls.

**Anti-metrics:** commits, lines of code, PRs opened, worker utilization,
number of findings, model tokens, unqualified “issues closed,” percentage of
green CI without check coverage, and a single performance score. These reward
splitting work, suppressing findings, or ignoring hard cases.
