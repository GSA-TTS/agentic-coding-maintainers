# Shadow exception recommendation replay

`scripts/evaluate-exception-replay.py` compares supplied, sanitized planner
recommendations with separately supplied maintainer labels. It is **offline,
read-only and shadow-only**: it never fetches GitHub, calls a model, changes
orchestrator state, retries a command, files an issue or authorizes a write.

```bash
python3 -I -B scripts/evaluate-exception-replay.py < private-replay.json
```

The bounded JSON input contains `schema_version: 1`, `expected_case_ids`
(unique opaque IDs), and `cases` with one row per observed case: `case_id`,
`maintainer_action`, `planner_action`, `planner_verdict`, and
`independent_label` boolean. Expected IDs must be set **separately from the
rows being evaluated** or missing difficult cases disappear from the
denominator. The tool cannot verify that the caller included every eligible
case, that labels were independently authored, or that actions were taken.
Keep the private input outside git. It accepts no title, raw PR text, URL,
hostname, token or free-form recommendation field.

The output contains aggregate counts and, only with at least five comparable
cases, a typed action confusion matrix:
received/expected/missing, independently labelled, unlabelled, comparable,
verdict-measured/missing, agreement and unsafe-recommendation counts. All
comparable cases need a measured `UNVERIFIED` planner verdict for exit 0; a
missing verdict is incomplete evidence. It does **not** output raw case IDs
or an agreement percentage that hides missing cases. A small
cohort suppresses the detailed matrix to avoid directly revealing one label;
aggregate counts can still reveal properties of a tiny private cohort, so do
not publish a report without checking its disclosure risk. A malformed
input fails `UNVERIFIED` with no report; missing/unlabelled/unsafe cases yield
exit 3 alongside diagnostic counts. Even on exit 0 `rollout_status` is always
`NOT_EVALUATED`: a small or self-selected clean corpus is not evidence for
autonomous execution. Zero unauthorized-write proposals and zero false PASS
are prerequisites to *considering* any executor, not a rollout approval.

Future work must bind expected cases and independent labels to an auditable
source, record attempts and decisions with provenance, and measure false-pass
and misclassification rates on a predeclared cohort before allowing any
bounded read-only executor. Remote writes still require current-head evidence
and action-specific maintainer authorization.
