# Shadow exception recommendation replay

`scripts/evaluate-exception-replay.py` compares supplied, sanitized planner
recommendations with separately supplied labels. It is **offline,
read-only and shadow-only**: it never fetches GitHub, calls a model, changes
orchestrator state, retries a command, files an issue or authorizes a write.

```bash
python3 -I -B scripts/evaluate-exception-replay.py \
  --manifest /absolute/private/frozen-cohort.json < private-planner-results.json
```

The private manifest contains `schema_version: 1`, `frozen_at` UTC and a
bounded `cases` array. Each row has one opaque `case_id`, a bounded
`maintainer_action` (or null), and boolean `independent_label`. It must be
current-user private (`0700` parent, `0600` file), absolute and nonsymlinked.
The separate bounded planner-results JSON on stdin contains
`schema_version: 1` and rows with `case_id`, `planner_action`, and
`planner_verdict`; it cannot supply or override labels. IDs absent from the
planner input remain in the denominator. A changed or self-selected manifest
could still omit difficult cases, and the `independent_label` flag is a
caller assertion—not verified reviewer identity or rollout evidence. The
`frozen_at` timestamp does not attest when a label or planner result was
produced: this is a comparison of supplied current inputs, not historical
as-of replay evidence. Keep
both inputs outside git. Neither accepts title, raw PR text, URL, hostname,
token field or free-form recommendation text.

The output contains aggregate counts:
received/expected/missing, caller-asserted independent labels, unlabelled, comparable,
verdict-measured/missing, agreement and unsafe-recommendation counts. All
comparable cases need a measured `UNVERIFIED` planner verdict for exit 0; a
missing verdict is incomplete evidence. It does **not** output raw case IDs,
an agreement percentage or a detailed confusion matrix: even five cases can
include a unique label, and marginal totals can reconstruct suppressed cells.
Aggregate counts can still reveal properties of a tiny private cohort, so do
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
