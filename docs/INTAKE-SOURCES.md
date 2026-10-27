# Intake source registry — offline validation pilot

`scripts/check-intake-sources.py` checks a **private captured registry** of
source/page metadata against required source ID/type pairs supplied separately
from the captured registry.
It reads no GitHub data, creates no issues, and never attests that every
real-world request was seen. Run with an absolute current-user-private file:

```bash
python3 -I -B scripts/check-intake-sources.py \
  --registry /absolute/private/source-capture.json \
  --required-source issue-feed:github_issues \
  --required-source review-feed:pr_review_requests \
  --required-source project-feed:project_items \
  --required-source direct-feed:direct_requests
```

Schema v1: `window_start`, `as_of`, and `sources`, plus
`schema_version: 1`. Initial types are `github_issues`,
`pr_review_requests`, `project_items`, `direct_requests`. Source IDs are
stable opaque names and can be extended by a later schema revision. Each
source has `source_id`, `source_type`, `captured_at`, `coverage` (`complete` or
`partial`), and `pages`. Each page records `cursor_in`, `cursor_out`,
`has_next`, and bounded opaque `request_ids`.

The validator refuses duplicate sources/requests, unknown source IDs,
broken/repeated cursors, inconsistent page ordering, missing pages and
malformed timestamps. A required source missing or declared partial yields
`UNVERIFIED` (exit 3) with diagnostic counts. A coherent caller-supplied
terminal page may yield `SUPPLIED_CHAIN_COHERENT` (exit 0). That means only
that the **supplied pages** form a coherent chain: the tool cannot tell
whether the first page was omitted, whether an API omitted a request, or
whether a caller intentionally omitted a whole source from the required CLI
arguments. Those arguments need a separately controlled policy before source
coverage can be claimed; the validator cannot authenticate them.
The `coverage: complete` flag and capture time are caller assertions, not
independent pagination provenance.

This does not yet reconcile Project items to their owning issue/PR, collect
direct requests, or verify the GitHub API pages. The separate
`INTAKE-INVENTORY.md` policy initially requires all four categories and
keeps eligibility unknown pending maintainer disposition for duplicates,
suspected spam and external PRs. Do not use `SUPPLIED_CHAIN_COHERENT` as
global intake coverage or as a verified-outcome denominator.
