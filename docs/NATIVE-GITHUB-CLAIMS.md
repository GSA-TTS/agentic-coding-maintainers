# Proposed public GitHub claim codec

Issue #117's first slice defines a shared comment format and an offline observer.
It is a proposal, not a live ownership or admission protocol. It does not read
coordinator metadata, verify assignments/current-user identity, or grant authority.
The commands use no network, subprocesses, or file writes; stdout is the result.
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

Capture input is strict UTF-8 JSON, at most 1,000,000 bytes, 2,000 comments and
32 levels of nested values. Strings (including bodies) are at most 65,536 UTF-8
bytes. Duplicate JSON keys, nonfinite constants, invalid Unicode and unsafe
relevant-field types are refused. A physical absolute path is required: symlinks
in any component, hardlinked/nonregular files, and changed file stat/path identity
during the bounded read are refused. These checks do not authenticate the file or
turn the host workspace into a sandbox.

Future work should connect this format to the existing coordinator intent journal,
with a separately reviewed trusted capture adapter retaining actual raw HTTP
pagination and identity/provenance evidence. Public preparation must remain
separate from private journal identifiers. This slice adds no outbox, mirror
state, custom capture envelope, mutation adapter, or new admission state.

The offline fixture suite is `tests/native-claim-test.py`, included in `make test`
and therefore `make check`. Execute fixtures and repository checks only in an
independently justified isolated environment. Representative REST fixtures use
fictitious public values and never make GitHub requests.

[rest]: https://docs.github.com/en/rest/issues/comments#list-issue-comments
