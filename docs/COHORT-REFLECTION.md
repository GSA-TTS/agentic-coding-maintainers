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
`needs_maintainer_disposition` queue: keyed case label, case type, whole-day age
and a `review_due` flag at seven full days. Unlike the 28-day performance
cohort, this queue retains older unknowns until a disposition is recorded.
This is a **read-only report cue**, not an
automatic exclusion or a GitHub label/comment. Consult the private ledger to
identify the case, record a maintainer decision through the correction process
when available (issue #30), and report the disposition delay as part of process
quality. Until corrections exist, an unknown remains unknown in this pilot.

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
correction events, 30-day escape windows and outage-adjusted latency remain future acceptance
work under issue #21/#22. Do not relabel this pilot as the completed
event-ledger system.
