# Offline Issues capture-to-registry adapter

`scripts/adapt-issues-capture.py` converts **two private, full-terminal captured
passes** of the same GraphQL Issues query to one private `github_issues` source
entry in the registry format checked by `check-intake-sources.py`. The captures
must be collected separately; the current `observe-github-issues.py` emits
only a summary and **cannot** supply the raw per-page cursor evidence this
adapter needs. This adapter performs no network request.

```bash
python3 -I -B scripts/adapt-issues-capture.py \
  --capture /absolute/private/issues-capture.json \
  --output /absolute/private/issues-source-registry.json \
  --key-file /absolute/private/report.key \
  --repository owner/repo \
  --window-start 2026-10-01T00:00:00Z \
  --as-of 2026-10-26T00:00:00Z
python3 -I -B scripts/check-intake-sources.py \
  --registry /absolute/private/issues-source-registry.json \
  --required-source issue-feed:github_issues
```

All three files must live under current-user-owned private directories; inputs
may be owner-only `0400` or `0600`, and the output is created mode `0600`.
The destination **must not exist**. An interrupted exclusive
write may leave an incomplete destination: inspect it before retrying. Inputs
are bounded at 64 KiB; captured passes have at most 10 pages and 2,000 issue
nodes. The capture JSON has exactly `schema_version: 1`, `repository`,
`window_start`, `as_of`, `query_type: graphql_issues_created_asc`, and two
passes with `captured_at` and `pages`. Every page has `cursor_in`,
`cursor_out`, `has_next`, and `issues` containing only `number` and
`created_at`. Both passes must start at a null cursor, reach a genuine terminal
page (`has_next: false`, `cursor_out: null`), and agree on complete ordered
`(number, created_at)` evidence and cursor structure. Pass timestamps must be
strictly increasing, but do not prove independent capture. A scan that stopped
at the `as_of` boundary while GitHub
still supplied a next cursor is **not** a full-terminal capture and is
UNVERIFIED here. Changed, missing, malformed or capped pages never create a
complete source entry.

The adapter HMAC-pseudonymizes issue IDs and cursor tokens using the private
report key before writing the registry. Neither the captured GitHub cursors
nor raw issue numbers are returned on stdout. The resulting source always has
`coverage: partial`, even when the supplied full-terminal passes agree: the
original API responses and request-to-response provenance are not independently
bound. The downstream registry validator returns `UNVERIFIED`, never a complete
source verdict, for this artifact. The required source pair is supplied separately at
validation time; a caller may still omit an entire source, so this must not be
used alone as the global intake denominator. Direct requests, PR review
requests, and Project items remain separate required sources.
