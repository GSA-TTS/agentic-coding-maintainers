# Bounded Issues connection observation

`scripts/observe-github-issues.py` performs **two bounded read-only GraphQL
scans** of the Issues connection for one validated `owner/repo` over a fixed
UTC creation window. GraphQL's `issues` connection returns Issues rather than
the REST `/issues` endpoint's mixture of Issues and PRs; this avoids silently
counting PRs in the issues intake category. It requests only `number` and
`createdAt`, plus pagination metadata—never title, body or comments.

```bash
python3 -I -B scripts/observe-github-issues.py \
  --repository owner/repo \
  --window-start 2026-10-01T00:00:00Z \
  --as-of 2026-10-26T00:00:00Z \
  --key-file /absolute/private/report.key
```

Use the same private 32–128-byte report key as the cohort reporter. The key
file lives under a current-user-private directory, mode `0600`. The command
does not create or publish a key. It emits the number of Issues visible to the
current GitHub credential, page count, and a keyed HMAC of the repository,
window and observed issue numbers—no issue titles, raw issue numbers,
repository name or GraphQL response are printed.
The tool refuses inherited proxy variables and GitHub host overrides; it
assumes direct GitHub API routing. A managed endpoint requiring a corporate
proxy remains UNVERIFIED until that transport is explicitly reviewed. Do not
disable TLS verification to force a run.

Each page response and its diagnostics are capped at 64 KiB, at most 10 pages
per pass and one shared 60-second deadline across both passes. Timeout, a
failed API call, malformed response, cursor cycle, duplicate issue number,
unexpected creation ordering, or a page cap before termination returns
`UNVERIFIED` (exit 3). The second pass must see the same ordered in-window
numbers and page grouping as the first. An empty result requires two
successful terminal responses; no evidence is never an empty backlog.

`TWO_CONSISTENT_VISIBLE_READS_NOT_ATOMIC` (exit 0) means only that two reads
returned the same visible list under this credential. Page-number/connection
pagination during mutations is not an atomic GitHub snapshot: transfers,
deletions or change-and-reversal between passes may escape detection. This
does **not** prove all historical issues were visible at the declared `as_of`,
nor include PR review requests, Project items or direct requests. The tool
does not produce a `source-capture.json` accepted by `check-intake-sources.py`
yet; a later adapter must preserve per-page provenance and reconcile stable
issue IDs to opaque case IDs. Do not use its HMAC or count as a verified intake
denominator or as authorization for a remote write.
