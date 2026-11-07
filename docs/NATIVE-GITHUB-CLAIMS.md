# Proposed public GitHub claim codec and read-only observer

Issue #117's codec slice defines a shared comment format and offline reconciliation;
the separate GET-only observer below adds bounded live comment traversal.
These are a proposal, not a live ownership or admission protocol. Neither reads
coordinator metadata, verifies assignments, or grants authority. Only the live
observer looks up the authenticated current-user identity.
The codec commands use no network, subprocesses, or file writes; stdout is the result.
Only GitHub.com issue comments are supported. No GitLab quick actions are supported.

## Prepare for explicit public review

Run in an independently justified isolated environment:

```sh
python3 -I -B scripts/native-claim.py prepare \
  --repo acme/widgets --issue 117 \
  --claim-id 0123456789abcdef0123456789abcdef \
  --operation-id fedcba9876543210fedcba9876543210 \
  --actor octocat --branch feat/native-claim \
  --task-ref issue:116 --scope implementation
```

The identifiers above are fixture examples. The caller supplies unrelated random
public claim and operation IDs as exactly 32 lowercase hexadecimal characters;
never reuse a private session, worker, lease, or journal identifier. The codec
does not generate IDs or verify their randomness or provenance. `--actor` must
be an independently verified public login supplied by the operator. Syntax
validation does not verify that login or the invoking account.

Every value-bearing CLI option may occur only once, including `--comments` and
both known-comment receipt options. Repetitions are refused with
`UNVERIFIED` / `DUPLICATE_ARGUMENT` (exit 3), even when values are identical or
the separate-value and `--option=value` forms are mixed. There is no last-value
override; rejection occurs during parsing, before capture reads. Error output
does not echo argument values.

The output is deterministic compact JSON containing the comment text, its SHA-256
over exact UTF-8 bytes (including the final newline), `status: PREPARED`,
`public_review: REQUIRED`, and `mutation_authorized: false`. No timestamp, private
identifier, PID, worker data, or filesystem path is included. Operator review of
the exact public text is required before any separately authorized publication.
Preparation itself does not record that review or authorize posting.

### Proposed v1 wire format

The body has exactly this fixed summary, a blank line, one HTML-comment marker,
and a final newline:

```text
Public coordination claim proposal (v1).
Operator review of every public field is required before posting.
This comment does not grant admission or mutation authority.

<!-- native-claim:v1 {"action":"claim","actor":"octocat","branch":"feat/native-claim","claim_id":"0123456789abcdef0123456789abcdef","issue":117,"operation_id":"fedcba9876543210fedcba9876543210","repo":"acme/widgets","scope":"implementation","task_ref":"issue:116","version":1} -->
```

Marker JSON is ASCII, key-sorted and compact, with exactly the displayed keys.
`version` is integer 1 and the only action is `claim`; release, expiry, takeover,
and other lifecycle actions are future work. Repository and actor are bounded
ASCII identifiers; actor supports ordinary public logins, not bot bracket names.
Issue and comment numbers are positive integers at most 2^63−1. `task_ref` is
`issue:N` in the same repository. `scope` is `implementation` or `review`, never
free-form prose or a private path list. Branches are 1–128 ASCII characters from
letters, digits, `/`, `_`, and `-`, starting with an alphanumeric character,
without repeated or trailing slashes. This is a deliberately narrower subset
of Git branch names. Actor and repository spelling is preserved; comparison is
exact, even though GitHub repository lookup is case-insensitive.

These whitelists reduce markup injection and accidental private-field copying;
they are **not a privacy proof**. A syntactically valid branch, repository, login,
or reference can still reveal sensitive information. Review every public field.
The codec neither derives public values from arbitrary local paths nor reads
private ownership records.

## Observe an actual REST comment capture

`reconcile` accepts a raw JSON array captured from
`GET /repos/{owner}/{repo}/issues/{issue_number}/comments`, using a raw-body media
type. The official [GitHub issue-comment REST schema][rest] includes `issue_url`.
Supply the same explicit intended metadata as for preparation:

```sh
python3 -I -B scripts/native-claim.py reconcile \
  --repo acme/widgets --issue 117 \
  --claim-id 0123456789abcdef0123456789abcdef \
  --operation-id fedcba9876543210fedcba9876543210 \
  --actor octocat --branch feat/native-claim \
  --task-ref issue:116 --scope implementation \
  --comments /physical/path/comments.json
```

This command only reads the supplied file. It does not fetch or certify the
capture. Each observed record must have a unique positive integer `id`,
`user.login`, raw string `body`, and the exact
`https://api.github.com/repos/owner/name/issues/N` identity. Common REST fields
such as timestamps, reactions, URLs, user details, and unknown fields are allowed
but never echoed or used as authority. Missing/null authors or raw bodies are
refused; text/HTML-only media representations are insufficient. Every record is
identity-checked, including ordinary discussion comments.

Captured `user.login` accepts either a normal 1–39 character ASCII login
(alphanumeric endpoints, alphanumeric/hyphen interior, no consecutive hyphens)
or that same bounded base with the exact lowercase GitHub App suffix `[bot]`.
For example, an ordinary `github-actions[bot]` comment can coexist with a valid
normal-user claim. No other brackets, suffix spelling, repeated suffix, trailing
text, whitespace, or markup is accepted. This is syntax compatibility, not App
identity verification; `user.type` is not used as authentication. Claim actors
still accept only normal-user logins. Author comparison preserves the complete
captured login: `octocat[bot]` cannot satisfy a marker naming `octocat`, and a
marker naming a bot actor is invalid. Captured authors are never echoed.

A reserved `native-claim` mention with malformed, quoted, multiple, foreign-version,
noncanonical, or edited codec content is conservatively refused. A valid marker
whose actor differs from the comment author is a conflict. This is a spoofing
boundary check on captured data, **not authentication**: even an exact same-user
match proves neither capture provenance nor operator/session authority.

| Result | Meaning | Exit |
| --- | --- | --- |
| `OBSERVED_MATCH` | Exact intended marker and author observed | 3 |
| `CONFLICT` | Other claim/payload, repeated operation ID, same claim ID with differing payload, author/marker identity mismatch, or known-body edit observed | 4 |
| `UNVERIFIED` | No match, missing known comment, invalid input, or unsafe/unavailable capture | 3 |

Observed conflicts take precedence over matches, including same-actor different
claims. Duplicate comment IDs are invalid capture data. Output contains only fixed
reason codes, observed public match IDs and counts; it does not echo capture
fields. Every reconciliation reports `remote_coverage: unmeasured` and
`mutation_authorized: false`. An empty array is not proof of an unclaimed issue.
A matching array is not proof that conflicting comments are absent. Raw arrays
cannot establish pagination, filters, freshness, authenticity, or completeness;
no caller-supplied completeness/readiness boolean is accepted.

### Optional known-body comparison

Supply both `--known-comment-id N` and `--known-body-sha256 64lowercasehex` to
compare the exact current body with an operator-retained observation. A changed
body is a conflict, even if its marker was removed entirely. An absent known ID
is `UNVERIFIED`, even when another matching comment is observed. The receipt is
caller input, not trusted history or an authorization token. Without it, an
ordinary comment that once contained a removed marker cannot be distinguished
from ordinary discussion. Even with it, deletions, other edits, and edit history
cannot be established from a partial capture. A malformed edited marker remains
an input refusal.

## Input bounds and integration boundary

### Live GET-only observation

The separate observer traverses visible issue comments using the actual REST
transport. Run it only in an independently justified isolated environment with
normal `gh` credentials for the intended GitHub.com account:

```sh
python3 -I -B scripts/observe-github-claims.py --repo acme/widgets --issue 117
```

It first reads `GET /user` to identify the authenticated account and
`GET /repos/acme/widgets` to bind the repository's numeric immutable ID and exact
name/URL. It then reads the issue identity, every comments page, and the issue
again. A pull request through an Issues endpoint is refused. Closed and locked
issues are observed with explicit flags; neither flag changes authority. With
one comments page this is five GET calls (identity lookups plus issue, comments,
issue reread). There are no mutation methods or flags, arbitrary URL option,
preparation inputs, journal integration, or automatic publication.

Requests explicitly use `gh api --hostname github.com --method GET --include`,
raw-body media and API version `2022-11-28`. `GH_HOST` is pinned to `github.com`;
inherited `GIT_*`, `GITHUB_HOST`, debugging and pager overrides are removed.
Normal authentication/configuration variables remain available. Proxy overrides
are refused. Credentials identify the current account, not a task assignment,
operator/session authority, or approval to act.

`gh` may follow HTTP redirects internally before `--include` returns the final
response. The observer rejects a final non-200 status or final `Location` header
and validates the final repository/issue identity fields and stable issue ID.
It does **not** prevent, observe, or attest intermediate redirects, credential
forwarding, or a fully secure authentication/host-routing chain. A followed
redirect ending in 200 with valid identities can be observed. Future use requiring
remote effects needs separately reviewed transport hardening that controls and
verifies redirects and credential routing before any authority is granted.

All calls share a 60-second deadline and a 512 KiB combined stdout/stderr budget.
Timeout/overflow kills the subprocess group, including pipe-holding children,
with bounded reaping. At most ten pages of 100 comments and 1,000 total comments
are accepted. Final HTTP metadata must report 200 with no `Location` header;
duplicate HTTP headers/JSON fields and malformed bodies are refused. Every Link relation,
including non-followed `first`, `prev` and `last`, must reference exactly the
named GitHub.com comments endpoint or its canonical numeric path
`/repositories/{verified_repository_id}/issues/{requested_issue_number}/comments`,
with only `per_page=100` and a bounded page. The numeric ID comes exclusively
from the verified repository GET response; foreign repository/issue paths are refused.
`next` must be the consecutive page. Foreign/trailing/ambiguous links and an
advertised later last page without a successor are refused. A full terminal
page is valid when Link has no successor. The observer constructs its own next
request on the fixed named endpoint rather than executing a returned URI, even
when the validated Link uses the numeric path.

Every comment, including ordinary discussion and bots, contributes to the count
and is checked for unique ID, exact issue URL, valid author/body/timestamps and
strict creation-time/ID order. Claim parsing and canonical rendering reuse
`native-claim.py`; reserved malformed, mixed or future-version markers refuse the
observation. Claims with foreign issue metadata, author mismatch, repeated
operation IDs, differing payloads for one claim ID, or multiple distinct claims
report conflict. The current-user boolean requires the marker actor, comment
author login **and immutable author ID** to match the authenticated account;
it grants no task authority. Removed markers and unobserved edit history cannot
be recovered by this utility.

| Observer result | Meaning | Exit |
| --- | --- | --- |
| `OBSERVED` | Valid visible traversal and consistent issue anchors, including zero claims/comments | 0 |
| `CONFLICT` | Valid traversal with recognized claim conflicts | 4 |
| `UNVERIFIED` | Identity, HTTP, pagination, codec, bounds or anchor/count validation failed | 3 |

`remote_coverage: complete_pagination` is emitted only after Link exhaustion and
an issue reread with identical ID, number, updated timestamp, comment count,
state and lock flag; that count must equal observed unique comment IDs.
This is measured visible traversal, **not an atomic snapshot**. Equal anchors
can miss concurrent comment edits or compensating changes, permission changes,
deleted history or invisible comments. An empty stable traversal does not prove
global absence or authorize taking an issue. Every report says
`atomic_snapshot: false`, `mutation_authorized: false`, and
`absence_authorizing: false`. Exit 0 is observation success, not remote-effect
readiness.

Stdout is compact JSON containing only fixed status/reason codes, numeric
repository/issue/comment IDs, counts, flags and recognized-claim summaries
(exact-body SHA-256 and author/current-actor booleans). It emits no logins,
repository names, branch/task/scope/claim/operation metadata, arbitrary comment
bodies, unknown REST fields or raw subprocess diagnostics. Errors are sanitized
JSON on stdout. There is no capture-file writer. IDs and hashes can still be
correlatable: treat reports according to the source repository's sensitivity.
The raw bodies exist only in bounded process memory for validation; these
summaries cannot be passed to the raw-array codec as a capture or reconstructed
into public claim text.

The existing offline `reconcile` raw-array contract is unchanged and still reports
`remote_coverage: unmeasured`. The observer does not upgrade a separately supplied
file, attest a retained capture, or feed claim preparation. Future integration
needs a separately reviewed provenance/privacy and authorization contract.

### Offline capture bounds

Capture input is strict UTF-8 JSON, at most 1,000,000 bytes, 2,000 comments and
32 levels of nested values. Strings (including bodies) are at most 65,536 UTF-8
bytes. Duplicate JSON keys, nonfinite constants, invalid Unicode and unsafe
relevant-field types are refused. A physical absolute path is required: symlinks
in any component, hardlinked/nonregular files, and changed file stat/path identity
during the bounded read are refused. These checks do not authenticate the file or
turn the host workspace into a sandbox.

Future work may connect this format to the existing coordinator intent journal,
with a separately reviewed trusted capture adapter retaining actual raw HTTP
pagination and identity/provenance evidence. Public preparation must remain
separate from private journal identifiers. This slice adds no outbox, mirror
state, custom capture envelope, mutation adapter, or new admission state.

The offline fixture suites are `tests/native-claim-test.py` and
`tests/observe-github-claims-test.py`, included in `make test`
and therefore `make check`. Execute fixtures and repository checks only in an
independently justified isolated environment. Representative REST fixtures use
fictitious public values and never make GitHub requests. Observer fixtures provide
a deterministic fake `gh` executable that validates exact GET arguments and
sanitized environment before supplying adversarial HTTP responses.

[rest]: https://docs.github.com/en/rest/issues/comments#list-issue-comments
