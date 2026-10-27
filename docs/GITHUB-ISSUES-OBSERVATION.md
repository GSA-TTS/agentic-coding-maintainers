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

For an opt-in **private full-terminal capture**, add `--capture-output
/absolute/private/issues-capture.json`. The destination must be absent and its
parent current-user-owned mode `0700`; it is created exclusively at `0600`.
The mode uses the same bounded query, but unlike summary mode it continues to
the API's real terminal page even if an `as_of` boundary appears earlier. It
retains each request's input cursor, validated page continuation and only
`number`/`created_at` Issue nodes, compares both complete passes, then writes
the bounded private artifact. A non-null API terminal endCursor is normalized
to null *as a continuation* in this v1 capture; raw terminal cursor bytes are
not retained. An interrupted exclusive write can leave an incomplete file:
inspect it before retrying, never overwrite or silently repair it. This mode
prints no raw issue identifiers, but its private output contains them and must
not be committed or shared. It can be fed to `adapt-issues-capture.py`, whose
registry entry deliberately remains `coverage: partial` until independent API
provenance is established. Captured timestamps and two matching passes do not
create an atomic historical GitHub snapshot.

The tool refuses inherited proxy variables and GitHub host overrides; it
assumes direct GitHub API routing. A managed endpoint requiring a corporate
proxy remains UNVERIFIED until that transport is explicitly reviewed. Do not
disable TLS verification to force a run.

The GitHub GraphQL query uses the absolute `https://api.github.com/graphql`
endpoint. POST is the GraphQL transport operation, **not** a GitHub state
change: the document is a query and requests Issues metadata only. A test
asserts the exact query/host shape; local `gh` still inherits its credential.
The response and diagnostics share one **combined** 64 KiB cap per call, with
at most 10 pages per pass and one shared 60-second deadline across both passes.
Timeout, a failed API call, malformed response, cursor cycle, duplicate issue number,
unexpected creation ordering, or a page cap before termination returns
`UNVERIFIED` (exit 3). The second pass must see the same ordered in-window
numbers and page grouping as the first. An empty result requires two
successful terminal responses; no evidence is never an empty backlog.

In **summary mode**, `TWO_CONSISTENT_VISIBLE_READS_NOT_ATOMIC` (exit 0) means only that two reads
returned the same visible list under this credential. Page-number/connection
pagination during mutations is not an atomic GitHub snapshot: transfers,
deletions or change-and-reversal between passes may escape detection. This
does **not** prove all historical issues were visible at the declared `as_of`,
nor include PR review requests, Project items or direct requests. **Capture
mode** emits a private JSON artifact accepted by `adapt-issues-capture.py`;
the adapter deliberately emits `coverage: partial`, and
`check-intake-sources.py` returns `UNVERIFIED` for it. A future provenance
design must corroborate source/API evidence and reconcile stable issue IDs to
opaque case IDs. Do not use the HMAC or counts as a verified intake
denominator or as authorization for a remote write.
