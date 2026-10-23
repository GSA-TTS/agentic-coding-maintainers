# Conditional intake coverage from a separate request inventory

## Initial maintainer intake policy

The first source categories are **GitHub issues, PR review requests, Project
items, and direct requests**. They are an initial registry, not a permanent
closed list: an additional source needs a stable source ID, a defined request
identity, a documented complete/partial enumeration method and a separately
declared `--required-source` entry before it can contribute to a denominator.
Do not treat the Project board as a replacement for the owning issue/PR state;
its items may duplicate requests seen in GitHub. Deduplicate through a
reviewed one-to-one identity mapping rather than matching titles or dates.

**Routine dependency work is eligible.** Duplicate, suspected spam and
external-PR requests require maintainer review; do not automatically exclude
them or silently omit them from the inventory. Record `eligibility: "unknown"`
until a maintainer makes a reasoned disposition. A requested exclusion also
requires a reasoned, append-only correction record (not implemented yet), so
this pilot must not be treated as an eligibility decision engine.

The meaning and evidence requirements of a **verified outcome** remain an
open policy decision. Neither `ready_for_human_review`, a ledger `outcome`
event, a passing check recorded by an operator nor a closed issue establishes
verified completion by itself. Keep those outcomes UNVERIFIED while the
decision is made separately.

### Evaluation of the intake process itself

Track later corrections as a *quality signal*: counts of cases whose source,
eligibility, duplicate mapping or substantive-rework classification had to be
corrected, by intake cohort and by original decision. Preserve the first
classification and correction time so a high correction rate prompts a
workflow review, not blame or pressure to suppress corrections. Report cases
awaiting disposition beside corrected cases; otherwise avoiding a decision
would falsely improve the rate. The current event schema has no correction
event, so none of these numbers is measurable yet.

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
bytes. It never prints raw request IDs or titles. `operator_asserted_source_coverage`
means only: **of requests supplied in declared operator-asserted enumerations
for this window, all eligible requests have matching eligible intakes**. Missing
eligible requests return `UNVERIFIED`, even if every source claims complete. The
`coverage: "complete"` flag is an upstream/operator assertion, not proof that
all pages or all real-world requests were observed. Review the collection
method separately; do not call this global intake completeness or verified
outcome throughput. No GitHub request or write occurs in this CLI.
