# Cohort reflection: first read-only ledger slice

`scripts/cohort-reflection.py` is an operator-invoked, **read-only** parser for
sanitized local JSON Lines events. It neither fetches GitHub state nor writes
issues, task state, files, or model prompts. Run it with a private ledger and a
fixed UTC cutoff:

```bash
python3 -I -B scripts/cohort-reflection.py \
  --ledger /absolute/private/path/cases.jsonl \
  --key-file /absolute/private/path/report.key \
  --inventory /absolute/private/path/requests.json \
  --required-source issue-feed --as-of 2026-10-22T00:00:00Z
```

The ledger is host-local, current-user-owned and private (`0700` directory,
`0600` file). It must not be committed: real case IDs may identify private
reviews. Keep only bounded opaque identifiers, enumerated classifications,
full 40-hex heads and UTC timestamps. No titles, finding descriptions,
credentials, operator IDs, URLs, raw PR text, or shell output. Each line has
`schema_version: 1`, an opaque unique `event_id` and `case_id`, `event_type`,
`occurred_at` and `recorded_at`, followed by exactly these typed fields. Generate
the separate private report key with `python3 -I -B -c 'import secrets,sys;
sys.stdout.buffer.write(secrets.token_bytes(32))' > /absolute/private/path/report.key`
under a `umask 077`; never commit or publish it. Keep this key stable across
reports so a case can be followed by the same pseudonym, and rotate it when
access to the mapping changes:

| Event | Additional fields |
|---|---|
| `intake` | `case_type`: implementation/review/security/documentation/other; `eligibility`: eligible/excluded/unknown |
| `transition` | `state`: open/blocked/cancelled/abandoned/ready_for_human_review |
| `review` | `head_sha`; `independent`: yes/no/unknown |
| `rework` | `review_event_id`; distinct `changed_sha`; `substantive`: yes/no/unknown |
| `handoff` | `review_event_id`; matching `head_sha`; `checks`: passing/failing/unavailable/unknown/not_applicable |
| `outcome` | `handoff_event_id`; matching `head_sha`; opaque `repository_event_id` |
| `eligibility_correction` | earlier same-case `intake_event_id`; `replacement`: eligible/excluded/unknown; `reason_code`: duplicate_review/spam_review/external_pr_review/eligibility_review/clerical_error |
| `pr_association` | earlier same-case `intake_event_id`; `repository` (`owner/repo`); `pr_number`; full `head_sha`; `provenance: agent_recorded` |

The parser rejects missing intake, orphan/cross-case/wrong-type references,
duplicate IDs or intakes, invalid or unexpected fields, contradictory head
references, out-of-order recorded timestamps, and incomplete final lines. It
limits total bytes and event count; any failure is `UNVERIFIED` (exit 3), not a
partial clean report. It admits at most one `pr_association` per case in this first schema. A changed
PR head or association requires a separately reviewed append-only correction
design. Recording an association proves only that the agent wrote it, not
that a maintainer confirmed it or that it warrants cohort delivery credit. The
cohort is the 28-day window of **first intake** events
before `--as-of`. Eligible blocked and cancelled cases stay in the denominator;
excluded and unknown eligibility cases are disclosed separately. Report IDs
are keyed pseudonyms, not raw case IDs; preserve the private key to reconcile
them with the ledger. Late-recorded
transitions use occurrence time to determine current state, with append order
as a tie-breaker.

Unknown-eligibility cases also appear in the private
`needs_maintainer_disposition` queue: keyed case label, case type, whole days
**since writer-recorded intake**, and a `review_due` flag at seven full days.
Caller-supplied `occurred_at` may be backdated and cannot establish how long a
request existed before recording; historical request age is UNVERIFIED without
independent source timing. Unlike the 28-day performance
cohort, this queue retains older unknowns until a disposition is recorded.
This is a **read-only report cue**, not an automatic exclusion or GitHub label.
A maintainer can append one `eligibility_correction` event referencing the
original intake; it preserves the first classification and records a reason
code. A corrected unknown leaves the queue, but the 28-day **intake cohort
retains the original eligibility**, even for recent corrections. The report
shows both original counts and effective eligibility labels; its correction
count uses the fixed first-intake cohort as denominator. A queue removal is a recorded maintainer
decision, **not proof that the decision was corroborated by an older source
inventory**; the inventory report covers only the current 28-day window. The
report counts corrected cases in the
current intake cohort, not correction cycles or all historical cases. Inventory
classifications have no source-decision timestamp, so any corrected case makes
inventory coverage UNVERIFIED until source-time evidence is designed. Other
classification corrections remain work under issue #30. The fixed intake cohort reports writer-recorded disposition
delay for corrected unknowns, not verified source-to-decision time.

`correction_quality` reports recorded classifications, not a productivity
score: a fixed `denominator_first_intakes`, corrected-case counts and keyed
labels grouped by **original** eligibility, original-unknown count, pending
unknown labels, and resolved-unknown disposition delays. Delays use the
writer-set `recorded_at` of intake and correction, not backdatable
`occurred_at`. A valid correction recorded after `--as-of` does not alter the
historical reflection projection; correcting more cases can increase the count without
implying that the process got worse. These figures are from recorded events
only, not a complete independent intake inventory or verified outcomes.

### Cross-cohort unknown disposition and recorded-event availability

The additive `cross_cohort_unknown_disposition` section retains **all ages** of
original-unknown first intakes with `recorded_at <= --as-of`, including old
resolved cases and pending cases that have aged out of the performance cohort.
`denominator_original_unknown_first_intakes` and
`original_unknown_case_labels` identify that exact population. `resolved_count`
and `pending_count`, with their `resolved` and `pending` rows, form a disjoint,
exhaustive partition. Rows are sorted by the existing HMAC `case_label`; labels
use the same private key and collision refusal as the rest of the report.
No raw case IDs, event IDs, reason codes or source text are added.

- Resolved rows carry `recorded_delay_hours`: correction recording minus intake
  recording. A correction is visible at its exact recorded cutoff, even if its
  occurrence was backdated. Resolution is a recorded classification decision,
  not an independently verified outcome.
- Pending rows carry `recorded_pending_hours`: cutoff minus intake recording.
  Both durations are numeric hours rounded to two decimal places, not elapsed
  time since source receipt or proof of when a human actually decided.
- Both row types carry `in_current_intake_cohort`, using the unchanged half-open
  occurrence window `[as_of - 28 days, as_of)`. An intake recorded at the cutoff
  is visible here; an intake occurring at the cutoff is not in that cohort.
- `other_original_eligibility_now_unknown_labels` separates originally eligible
  and originally excluded cases corrected to unknown. They remain in the
  existing operational queue, but **never enter this original-unknown
  denominator**. Neither `correction_quality` nor original eligibility,
  delivery/rework denominators, queue order or its seven-day rule changes.

Coverage is `recorded_events_only` when an original unknown is visible,
`no_original_unknown_evidence` when other events are visible, and
`no_recorded_evidence` when no events are visible at the cutoff. Empty buckets are not evidence of complete
intake or successful disposition. `recorded_event_availability` separately gives
`visible_event_count`, `latest_recorded_at` and `hours_since_latest_recorded`
(two-decimal numeric hours) for **all** events recorded at or before the cutoff.
With no visible events, count is zero and timestamp/elapsed hours are `null`.
`source_freshness` and `source_completeness` are explicitly `UNMEASURED`: a recent
ledger record is not proof of fresh or complete upstream collection. Inventory
coverage retains its separate, current-window meaning.

The whole ledger is validated **before** cutoff filtering. A valid future
append leaves the historical `reflect()` projection unchanged, including these
sections; a malformed future record fails closed with no partial CLI report.
This does not promise byte-identical CLI output after an append: the
whole-ledger identity HMAC below must change with the consumed input bytes.

The report includes `ledger_identity_hmac`, a domain-separated keyed HMAC over
the complete input bytes. An unkeyed digest would let a reader test guessed
small ledgers and case IDs offline, defeating pseudonymization. The cutoff
alone does **not** make a historical run immutable: a later append claiming an
earlier `recorded_at` can revise the same `--as-of` result. Compare the digest
before comparing two reports, and retain the private ledger and key versions if a
historical report needs to be reproduced. This HMAC is an input identity,
not proof that timestamps were recorded at the time claimed.

## Critical limits of this slice

The CLI requires a separate timestamped request inventory and a predeclared
source set for a successful intake-coverage exit. Its source `complete` flag
is an **operator assertion**, not independently verified enumeration; the
status is therefore `operator_asserted_source_coverage`, not proof that all
eligible requests were admitted. See `INTAKE-INVENTORY.md`. A recorded independent
review, passing check or repository-event ID is a **claim**, not live GitHub
attestation. Therefore **all** documented outcomes remain
`documented_outcome_ids_unverified`, `verified_completion_ids` is empty, and
every eligible case remains in `unfinished_for_verified_throughput`. This is
intentional: no count of verified throughput is manufactured from operator
input. A later, separately reviewed attestation step must bind the applicable
**delivery event** to repository evidence. Review/check compliance is measured
separately: see [`VERIFIED-OUTCOMES.md`](VERIFIED-OUTCOMES.md). For old merges,
present-day GitHub state is a labelled historical proxy, not at-merge proof.

Use the recorded-case IDs behind each bucket when reflecting, not a composite
productivity score. Recommendations are advisory and capped to two fixed
next-step prompts. An operator-invoked append writer is documented in
`COHORT-APPEND.md`. Operator-asserted inventory reconciliation is available
through `INTAKE-INVENTORY.md`; independently evidenced collection,
other correction events, 30-day escape windows and outage-adjusted latency remain future acceptance
work under issue #21/#22. Do not relabel this pilot as the completed
event-ledger system.
