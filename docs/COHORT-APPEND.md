# Private append-only cohort event writer

The operator can record **one sanitized event** at a time without modifying
existing ledger bytes:

```bash
# First create the private directory and an empty ledger, OUTSIDE git.
umask 077
mkdir -p /absolute/private/cohort
: > /absolute/private/cohort/cases.jsonl

python3 -I -B scripts/append-cohort-event.py \
  --ledger /absolute/private/cohort/cases.jsonl <<'JSON'
{"schema_version":1,"event_id":"event-1","case_id":"case-1","event_type":"intake","occurred_at":"2026-10-23T00:00:00Z","case_type":"review","eligibility":"eligible"}
JSON
```

The writer sets `recorded_at` using the host UTC clock. The input must *not*
contain it. It takes an exclusive advisory lock, validates the complete prior
ledger and the candidate against the same schema as the read-only reflection
CLI, then writes exactly one canonical JSONL line and fsyncs. It refuses an
absent directory, a missing/symlinked ledger, unsafe permissions, duplicates,
or an incomplete/corrupt prior ledger (`UNVERIFIED`, exit 3). It does not
repair an interrupted write silently: inspect it and the private evidence
before any manual recovery. All cooperating writers must use this CLI and its
lock; other processes able to write the same file are outside the guarantee.

**The event fields are claims, not GitHub attestation.** A recorded review,
passing check, or repository-event ID does not by itself establish a verified
completion. `cohort-reflection.py` deliberately leaves verified completion IDs
empty. Event IDs and case IDs must be opaque; do not enter issue titles,
credentials, raw PR text, worker names, hostnames, or findings. The CLI neither
fetches GitHub nor sends event content to a model. Read-only cohort reflection,
request-inventory reconciliation, correction events, and current-head outcome
attestation are separate concerns under issue #21.
