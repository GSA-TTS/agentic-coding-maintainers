# One-PR review-request event observation

`scripts/observe-review-requests.py` makes two bounded, GET-only reads of the
Issues **event history for one explicitly selected PR**. It includes both
`review_requested` and `review_request_removed` events made in the fixed
`[window_start, as_of)` interval. These are historical events, unlike the
current pending-reviewer list, which loses a reviewer after review submission.
An initial bounded Pulls API GET verifies that the supplied number is a PR in
the requested base repository; the Issues events URL alone also accepts
ordinary issue numbers. If that identity cannot be measured, the scan refuses.

```bash
python3 -I -B scripts/observe-review-requests.py \
  --repository owner/repo --pr 7 \
  --window-start 2026-10-01T00:00:00Z \
  --as-of 2026-10-26T00:00:00Z \
  --key-file /absolute/private/report.key
```

The report includes the count of in-window events, page count and a keyed
fingerprint of event ID, type, time and validated reviewer/team target for
that PR. Both reads must agree on those fields. It prints no requester,
requested user/team, PR title/body, or raw event ID. Team requests remain
**team** requests; this tool does not infer individual team members. The key
file must be current-user-private in a `0700` directory, 32–128 bytes and
never committed.

The adapter pins the public GitHub API URL and uses `GET` only. It refuses
GitHub host or proxy overrides rather than silently routing an authenticated
request elsewhere. Pages and diagnostics have one combined 64 KiB bound, with
at most ten pages and one shared 60-second deadline for two scans. It follows
only same-endpoint `Link: rel="next"` URLs to the consecutive page, rejects
ambiguous or malformed pagination and conflicting event IDs, and refuses API
errors, limits or changed reads with `UNVERIFIED` (exit 3). It retains no raw
HTTP response, and it makes no GitHub write.

`TWO_CONSISTENT_VISIBLE_READS_NOT_ATOMIC` means only that those two event reads
matched for this one PR under the current credential. A repo-wide review
request intake denominator needs a **separately enumerated PR cohort that
includes older and closed PRs**: a request made this week on a PR created last
month is missed by a PR-created-this-week filter. Visibility of secret teams
and events can vary with credential access; equal reads do not create an
atomic historical snapshot or prove complete repository-wide intake. This
tool does not yet write a registry source entry; the other intake categories
and direct requests remain separate work under issue #29.
