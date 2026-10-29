# Durable PR observation trial — 2026-10-29

AI-assisted first observation-journal slice for #67/M02 and #74/M09 after
PR82. Existing #29 source-enumeration scope remains separate; no new tracker
duplicates, automatic admissions or GitHub effects were created.

## Implemented and tested

The existing foreground monitor optionally records private SQLite poll intents,
per-source coverage, material PR generations and current candidate references.
Observed failures preserve known candidates. Disappearance is NOT_IN_OPEN_SET,
not inferred closure/merge. Status is read-only and explicitly as-of a retained
poll, never proof of ongoing monitoring or current GitHub health.

Fifteen journal tests pass, covering restart deduplication, A→B→A history,
interrupted and conflicting finalization, successful-empty versus failed source,
partial Project failure, capacity rollback, malformed/duplicate source data,
read-only status, SQLite/path corruption, contending writers, public CLI replay,
lost candidate projection and coverage count, and concurrent status consistency.
The two-connection test uses test-only WAL to force a writer commit between
status reads; production uses rollback journaling. The explicit read transaction
keeps all returned data on one snapshot.

An existing shell-test lock leaked into later cases and hid their failures.
Removing it exposed a repository-path validation gap; dot traversal components
are now rejected before GitHub. Project truncation now asserts its own failure
reason. Strict raw field validation prevents malformed status fields and null
Project items from being normalized into successful durable coverage.

## Actual capture and isolated replay

The operator authorized a read-only trial using existing Ubuntu VM tools. `gh`
was absent there, so **live candidate transport remains UNVERIFIED**. No host
credential was copied and no new tool was installed. The authorized fallback
used real host `gh pr list --state open --limit 501` captures of the four
ecosystem repositories, then replayed their material fields in isolation.

Captured visible-open-set counts: Maintainers0, Patterns20, Quickstart17,
Playbook6. Titles, authors, body text, URLs and raw stderr were not journaled.
The retained replay projection transcribed the exact heads/draft/review/merge
and check-conclusion multiplicities. It is not a raw-page attestation.

The repeatable `tests/monitor-capture-replay.py` ran in the Ubuntu VM without
network calls. Observed output:

```json
{"repositories":4,"candidates":43,"restart":"CURRENT","stable_references":true}
```

The first ingestion created43 candidate observations; reopening the database
and ingesting the same capture created no new generations. These are observed
PR candidates, not43 admitted tasks or completed reviews. Synthetic fault tests
provide the gap/change/recovery cases; the live capture did not manufacture
changes to upstream PRs.

## Review and qualifications

Parallel fixed-revision QA/security at
`2a4478e77e8febfd8a270e45ef1b461874eadfe0` found mixed-revision status reads,
raw-schema normalization, and incomplete reverse projection validation. Repairs
add a transactional status snapshot, pre-normalization type checks, reconstructed
source coverage and complete candidate/event sequence checks. Final re-review
and full repository checks are required before publishing the repaired revision.

Hard journal limits fail closed rather than pruning current candidates. No
automatic archival/migration, task-mutation outbox, supervisor/daemon, App,
rules change, review dispatch, remote effect or merge authority is activated.
This advances durable observation, not completion of M02/M09 or the overall plan.
