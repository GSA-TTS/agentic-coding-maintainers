# Conditional intake coverage from a separate request inventory

The case ledger cannot reveal requests never recorded as cases. To measure a
bounded intake denominator, capture a **separate**, private request inventory
from each declared source and run the read-only reflection CLI with it:

```bash
python3 -I -B scripts/cohort-reflection.py \
  --ledger /absolute/private/cohort/cases.jsonl \
  --key-file /absolute/private/cohort/report.key \
  --inventory /absolute/private/cohort/requests.json \
  --required-source issue-feed --required-source review-feed \
  --as-of 2026-10-23T00:00:00Z
```

The source list is specified **outside** the inventory; an inventory cannot
claim completeness merely by omitting a source. Specify every expected source
before assessing it. The inventory is a JSON object with exactly:

```json
{
  "schema_version": 1,
  "as_of": "2026-10-23T00:00:00Z",
  "window_start": "2026-09-25T00:00:00Z",
  "sources": [{
    "source_id": "issue-feed",
    "enumerated_at": "2026-10-23T00:10:00Z",
    "coverage": "complete",
    "requests": [{
      "request_id": "opaque-case-1",
      "received_at": "2026-10-05T00:00:00Z",
      "eligibility": "eligible"
    }]
  }]
}
```

Request IDs must match the ledger's opaque case IDs exactly. This pilot has no
title-based matching or many-to-one mapping; an unmapped request remains
missing. Record excluded and unknown eligibility explicitly. The inventory
must cover the same 28-day UTC window, identify each source exactly once, and
have unique request IDs across sources. Missing or partially enumerated
sources, unknown eligibility, ledger-only intakes, and conflicting eligibility
make the inventory status `UNVERIFIED` (exit 3). Malformed, duplicate,
oversized, stale or out-of-window inputs fail closed. A complete inventory
with zero eligible requests is also not an eligible-cohort measurement.

The report prints the eligible enumerated and matching recorded counts,
missing/unknown/ledger-only/conflicting **keyed pseudonyms**, incomplete source
labels, and a domain-separated keyed HMAC identifying the exact inventory
bytes. It never prints raw request IDs or titles. `source_attested_conditional`
means only: **of requests independently enumerated in these declared sources
and this window, the reported number were recorded as eligible intakes**. The
`coverage: "complete"` flag is an upstream/operator assertion, not proof that
all pages or all real-world requests were observed. Review the collection
method separately; do not call this global intake completeness or verified
outcome throughput. No GitHub request or write occurs in this CLI.
