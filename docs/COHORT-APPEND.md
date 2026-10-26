# Private append-only cohort event writer

The operator can record **one sanitized event** at a time without modifying
existing ledger bytes:

```bash
# First create the private directory, OUTSIDE git. The writer validates it.
umask 077
mkdir -p /absolute/private/cohort
python3 -I -B scripts/append-cohort-event.py \
  --ledger /absolute/private/cohort/cases.jsonl --init </dev/null

python3 -I -B scripts/append-cohort-event.py \
  --ledger /absolute/private/cohort/cases.jsonl <<'JSON'
{"schema_version":1,"event_id":"event-1","case_id":"case-1","event_type":"intake","occurred_at":"2026-10-23T00:00:00Z","case_type":"review","eligibility":"eligible"}
JSON
```

Initialization must run **once**; `--init` uses an exclusive descriptor-relative
no-follow create and refuses an existing ledger. A repeated
shell redirection such as `: > cases.jsonl` destroys existing evidence before
the writer can validate or lock it—never initialize that way.

The writer sets `recorded_at` using the host UTC clock. The input must *not*
contain it. It takes an exclusive advisory lock, validates the complete prior
ledger and the candidate against the same schema as the read-only reflection
CLI, then writes exactly one canonical JSONL line and fsyncs. It refuses an
absent directory, a missing/symlinked ledger, unsafe permissions, duplicates,
or an incomplete/corrupt prior ledger (`UNVERIFIED`, exit 3). It uses
`O_APPEND` to avoid overwriting bytes added by an uncooperative writer and
bounds lock waiting. This is **not a crash-atomic transaction**: an interrupted
write or fsync error can leave either a truncated line or a full line despite
exit 3. On any failure after a possible write, inspect the event ID in the
private ledger *before retrying*. Do not automatically truncate or repair the
ledger. All cooperating writers must use this CLI and its advisory lock; a
concurrent noncooperating writer is outside its consistency guarantee.

**The event fields are claims, not GitHub attestation.** A recorded review,
passing check, or repository-event ID does not by itself establish a verified
completion. `cohort-reflection.py` deliberately leaves verified completion IDs
empty. Event IDs and case IDs must be opaque; do not enter issue titles,
credentials, raw PR text, worker names, hostnames, or findings. The CLI neither
fetches GitHub nor sends event content to a model. Read-only cohort reflection,
request-inventory reconciliation, other correction events, and category-specific
delivery attestation (including private assessment evidence) are separate
concerns under issue #21. Check and review compliance are measured separately
where applicable; a private assessment must not need a public GitHub artifact.
