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

The parser rejects missing intake, orphan/cross-case/wrong-type references,
duplicate IDs or intakes, invalid or unexpected fields, contradictory head
references, out-of-order recorded timestamps, and incomplete final lines. It
limits total bytes and event count; any failure is `UNVERIFIED` (exit 3), not a
partial clean report. The cohort is the 28-day window of **first intake** events
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
classification corrections and cross-cohort disposition delay remain work under
issue #30. The fixed intake cohort does report writer-recorded disposition
delay for corrected unknowns, not verified source-to-decision time.

`correction_quality` reports recorded classifications, not a productivity
score: a fixed `denominator_first_intakes`, corrected-case counts and keyed
labels grouped by **original** eligibility, original-unknown count, pending
unknown labels, and resolved-unknown disposition delays. Delays use the
writer-set `recorded_at` of intake and correction, not backdatable
`occurred_at`. A correction appended after `--as-of` does not alter the
historical report; correcting more cases can increase the count without
implying that the process got worse. These figures are from recorded events
only, not a complete independent intake inventory or verified outcomes.

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
input. A later, separately reviewed attestation step must bind current PR
head, required checks, independent approval and repository outcome together.

Use the recorded-case IDs behind each bucket when reflecting, not a composite
productivity score. Recommendations are advisory and capped to two fixed
next-step prompts. An operator-invoked append writer is documented in
`COHORT-APPEND.md`. Operator-asserted inventory reconciliation is available
through `INTAKE-INVENTORY.md`; independently evidenced collection,
other correction events, 30-day escape windows and outage-adjusted latency remain future acceptance
work under issue #21/#22. Do not relabel this pilot as the completed
event-ledger system.
