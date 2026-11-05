# Bundle contract (authoritative with `bin/validate.py`)

No JSON Schema is shipped or claimed. The contract and validator describe the
implemented checks. JSON must be UTF-8, at most **1,000,000 bytes**, contain no
raw or escaped string NUL, duplicate object keys, non-JSON constants, missing
fields or unknown fields. Input must be a regular file, not a symlink (including
symlink path components); reading is bounded. Concurrent path replacement must
be prevented by the sandbox: path inspection is not host containment.

Top level has exactly `schema_version`, `active_claim_ids`, `sources` and `claims`.
`schema_version` must be integer **1**: booleans, floats and other versions are
rejected. `active_claim_ids` is a nonempty array of unique existing claim IDs,
explicitly selecting the operational view. `sources` and `claims` are nonempty
arrays of objects. All records are structurally validated, including inactive
history; only selected claims and their directly referenced sources contribute
operational reasons. Supersession links are history, not automatic selection.
There is no automatic migration or legacy fallback. Future schema evolution
requires a separately reviewed issue, contract and migration plan.
IDs are nonempty strings globally unique across both arrays. No whitespace-only
required strings are accepted. Dates use exact `YYYY-MM-DD`, real calendar dates.
Timestamp syntax is exactly UTC `YYYY-MM-DDTHH:MM:SSZ` (no offsets or fractions).

## Sources

Every source requires these fields; only `superseded_by` and `published_on` are optional:

| Field | Contract |
| --- | --- |
| `id` | Globally unique nonempty string. |
| `uri` | HTTP(S) URI with hostname, no username/password; not fetched or authenticated. |
| `publisher`, `locator` | Nonempty strings. |
| `quote`, `version` | Strings; nonempty for verified sources. |
| `artifact_sha256` | Empty string or 64 lowercase hex characters; nonempty for verified sources. Does not validate actual artifact bytes. |
| `retrieved_at` | Required UTC timestamp; date must be on/before the explicit cutoff day. |
| `reviewed_at` | Required UTC timestamp or null; nonnull for verified sources. Review date must be on/after retrieval date and on/before cutoff. |
| `review_ref` | Required string, nonempty for verified sources; approved review-notes URI or reference. Not fetched or authenticated. |
| `published_on` | Optional publication/issuance date or null; distinct from retrieval, review and effectiveness. |
| `effective_from` | Date or null for unknown start; selected unknown starts always degrade to unverified, regardless of declared status. |
| `effective_until` | Date on/after known `effective_from`, or JSON null for no declared end. |
| `review_due` | Required date on/after retrieval date and, if known, review date. |
| `status` | `verified`, `unverified`, or `superseded`. |
| `superseded_by` | Optional nonempty ID of an existing source; permitted only on superseded sources. No self-links or multi-source cycles. |

## Claims

Exactly these fields are required:

| Field | Contract |
| --- | --- |
| `id` | Globally unique nonempty string. |
| `source_ids` | Nonempty array of unique existing source IDs. |
| `rule_id` | Nonempty string identifying the scoped rule. |
| `authority_kind` | `legal`, `eo`, `policy`, `owner_style`, or `heuristic`. |
| `applicability`, `exceptions` | Nonempty strings; write an explicit reviewed absence rather than an empty exceptions field. |
| `status` | `verified`, `unverified`, or `superseded`. |

A verified source requires nonempty quote, digest, version, review reference and
a review timestamp. A verified claim referencing a nonverified source is an
incomplete operational declaration: if selected it degrades to unverified,
rather than being structurally invalid. Selected stale or unknown source
metadata also degrades the view without rewriting any status. Inactive history
can remain superseded, stale or unknown while the selected replacement is current;
malformed history still invalidates the whole bundle.

`effective_until: null` means **no declared end**, not an unknown end date.
If the end is unknown, do not declare the source verified; use unverified status
and explain uncertainty in review notes. The validator cannot distinguish an
honest no-end declaration from an incorrectly declared unknown end.

Re-review does not change `retrieved_at` for unchanged artifact bytes. Update
`reviewed_at`, `review_ref` and `review_due` with the actual review evidence.
Timestamp ordering is checked by inclusive UTC calendar date, not time of day.

## CLI verdicts

`python3 -I -B bin/validate.py BUNDLE --as-of YYYYMMDD` requires an explicit cutoff;
it never uses the wall clock. Retrieval later than the inclusive cutoff day is
malformed, including on an unverified source. No time-of-day freshness inference
is made within the cutoff day.

- **0 / `current`**: structural/current-review metadata only, **NOT legal truth**.
- **3 / `unverified`**: structurally valid but a selected claim or referenced
  source is unverified/superseded, or a referenced source is overdue, has unknown
  start, or is outside its declared inclusive effective interval.
- **4 / `invalid`**: malformed, inconsistent, inaccessible, oversized or refused
  input. Invalidity takes precedence over degraded metadata. Usage errors also
  return 4 (argparse diagnostics on stderr); `--help` returns 0, not a verdict.

Normal validation emits one JSON summary on stdout; it never modifies the bundle
or writes an evidence file. Artifact existence, authenticity, correspondence of
quote to artifact, legal correctness, reviewer identities, and rule-engine
behavior are outside this validator. The synthetic example is deliberately
unverified and uses `example.invalid`; no real authority or legal claim is made.

Each reason is an object with `kind` (`claim` or `source`), `id` and `code`.
Codes are `unverified`, `superseded`, `review_overdue`, `not_yet_effective`,
`expired`, and `unknown_effective_date`. Multiple distinct reasons may apply to
one source; each referenced source is assessed once. Results are bounded by the
bounded bundle, not external discovery. Exit 0 covers only the explicitly
selected view, not every historical record's current applicability.

For historical assessment, explicitly select the relevant claims and supply the
historical cutoff in a separate assessment bundle with that view's actual
retrieval/review metadata. No implicit historical mode, clock change, or automatic
successor traversal is provided. A bundle retrieved after the historical cutoff
is invalid for this CLI even if its text discusses earlier periods. Review-note
decisions must distinguish artifact/review cutoff from document-period legal
applicability; this validator cannot adjudicate retrospective applicability.
