# Proposed public GitHub claim codec and read-only observer

Issue #117's codec slice defines a shared comment format and offline reconciliation;
the separate GET-only observer below adds bounded live comment traversal.
These are a proposal, not a live ownership or admission protocol. The standalone
codec and observer do not read coordinator metadata or verify assignments.
The retained-task preparation wrapper below adds a local consistency comparison;
none grants authority. Only the live
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

## Prepare against an admitted retained task

The separate read-only wrapper composes the actual schema-3 ownership preflight
and existing codec. Run only in an independently justified isolated environment:

```sh
python3 -I -B scripts/prepare-task-claim.py \
  --authority-root /physical/workspace --invoking-root /physical/workspace \
  --task-id local-task --expected-revision 2 \
  --expected-worker-id aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --expected-session-id private-fixture-session --expected-generation 1 \
  --repo acme/widgets --branch feat/native-claim --issue 117 \
  --actor octocat --scope implementation \
  --claim-id 0123456789abcdef0123456789abcdef \
  --operation-id fedcba9876543210fedcba9876543210
```

These are illustrative fixture inputs. Every option is required, explicit, and
single-occurrence using the codec's `StoreOnce`; duplicate or malformed arguments
produce fixed sanitized reason codes without echoing their values. Public repo,
branch and issue mirror the raw stored task exactly, one for one: tracker type
must be `issue`, tracker number must equal `--issue`, and task kind must equal
the bounded `implementation` or `review` scope. `task_ref` is always `issue:N`
for that same issue, never the private task label or arbitrary domain scope.
The public actor is the user-entered expected login. This command performs no
`GET /user`, does not verify the current actor, and never derives a login from
the task's human owner label. Review that expected login independently.

`check-native-ownership.py` actually exposes `inspect(args)` taking an
argparse-style namespace, not an `ExpectedIdentity` class or public raw-task
export. The wrapper calls that API unchanged and reuses `physical_root`,
`directory`, `read_selected` and `fingerprint` for its additional metadata reads.
The preflight validates the schema-3 worker/session/generation, scope reservation,
global slot and, in `Implementing`, the implementation lane. Before preflight,
after preflight, and after codec preparation, the wrapper observes equal task
metadata, retained file fingerprints and selected physical-root identity. No
state validator is copied, no core module is modified, and no coordinator lock
or state write is taken. This remains a retained snapshot comparison, not an
atomic transaction, process-liveness check, admission decision or authentication.
A later change requires another comparison.

Public claim and operation IDs are refused if equal to known retained private
worker IDs, worker/global-slot lease tokens, scope tokens or session IDs,
including surviving transition-recovery identifiers and explicit expectations.
Known tokens are also excluded from the rendered comment. The wrapper does not
hash private IDs into public identifiers or export a task-metadata digest.
Unknown identifiers and sensitive but syntactically valid public values cannot
be detected: this is **not a privacy proof**. All public fields still require
operator review. The comment and receipt contain no private task label, session,
PID, worker ID, lease token, owner label, path or arbitrary domain scope.

| Wrapper result | Meaning | Exit |
| --- | --- | --- |
| `PREPARED_RETAINED_MATCH` | Canonical public proposal and consistent retained schema-3 evidence | 3 |
| `CONFLICT` | Preflight conflict or differing tracker/public binding | 4 |
| `UNVERIFIED` | Structural refusal, unsupported/idle/transitioning state, pending recovery, unsafe/missing record, changed metadata or private-ID reuse | 3 |

Success preserves the codec's exact comment, exact-body SHA-256 and required
public-review fields, adding only `bound_retained_snapshot: true`,
`native_session_authentication: UNVERIFIED` and
`current_actor_authentication: UNVERIFIED`. `mutation_authorized` remains false;
`remote_coverage` remains unmeasured. Failures have no comment or body hash and
report `bound_retained_snapshot: false`. Original preflight status/reason and
structural exit distinctions are preserved. Schema 2 with these required bound
expectations is refused, rather than upgraded. Exit 3 deliberately prevents
preparation success from being mistaken for authority.

### Explicit local publication intent

`prepare-task-claim.py` remains read-only. The separate explicit command
`scripts/journal-claim-intent.py` takes exactly the same required, single-occurrence
arguments shown above and records local intent. Invoke it with `python3 -I -B`
only in an independently justified isolated environment. No record flag is needed:
selecting this command explicitly selects local persistence. It calls the actual
unchanged `prepare-task-claim.py` parser and preparation API under the core
`CoordinatorLock`. It uses existing safe physical-root/private-file helpers and
strict schema-3 native binding validation, without initializing task state or
changing `task.json` or its revision.

Persistence reuses `.orchestrator/monitor/history.sqlite3`, never a second outbox.
Schema 3 adds only `claim_intents` alongside the existing observation tables and
`binding_acks`. Only `record_claim_intent` performs the transactional 1 → 2 → 3
upgrade, with individual DDL statements inside `BEGIN IMMEDIATE`; it never uses
`executescript` for migration. Monitor read/write opens accept version 3 but do
not upgrade existing stores automatically. Binding acknowledgment's existing
version-1-only upgrade preserves version 3. Local intents neither enter poll
events nor change observation generations, coverage or candidate projections.
Candidate binding refuses a version-2 or version-3 journal acknowledgment when
the authoritative task receipt is absent, before any tentative task write. A
restored prebinding task cannot acquire authority by retrying the same or a
different binding operation after an unrelated local intent migrates the store.

The exact immutable private request is:

```text
schema_version: integer 1
action: "claim-publication"
operation_id: public lowercase hex32 (unique throughout this store)
store_id: private existing journal incarnation
claim: exact existing native-claim v1 object
comment: exact codec-rendered public UTF-8 body, including final newline
comment_sha256: SHA-256 of those exact body bytes
binding:
  task_id, created_at: retained task identity/incarnation
  task_sha256: SHA-256 of canonical complete retained task JSON
  revision, generation, session_id: exact cooperative fences
  worker: complete retained schema-3 worker snapshot
```

There are no assignment phases, dispatcher, terminal replay operation, remote
acknowledgment, public-review receipt or readiness field. Task authority remains
in the existing task record; journal presence never grants authority or readiness.
Ownership checks are static retained consistency, not process authentication or
an authenticated current GitHub actor. The private task fingerprint and journal
incarnation are never emitted as public receipts.

Every retained intent is validated before observation or intent use: exact
fields/types/version/action, canonical JSON without duplicate keys or nonfinite
constants, exact public wire body/digest, private binding, request digest and store
identity. The table permits at most 1,000 permanent entries, with a 16,384-byte
canonical request ceiling and the existing 64,000,000-byte database ceiling.
Unknown historical intent types or malformed rows refuse the whole store; they
are never skipped or treated as narrative transitions. No silent pruning occurs.

Lock order is coordinator then SQLite; the intent path never holds SQLite while
acquiring coordinator. Existing monitor paths acquire no coordinator lock while
holding a SQLite write transaction. Intent writes hold coordinator through fresh
preparation, full retained task comparison, transaction commit and durability
barriers. Fresh checks run again inside the SQLite transaction and before output.
The store must remain current-user private, physical, regular, single-linked and
bounded, including SQLite sidecars. The selected database inode is checked around
open/validation and commit/replay sync. Noncooperating filesystem writers are not
authenticated or isolated by these cooperative locks.

| Intent result | Meaning | Exit |
| --- | --- | --- |
| `INTENT_RECORDED` | Exact pending local request committed and durability barriers completed | 0 |
| `REPLAYED_PENDING` | Exact identical retained request and unchanged current task; durability barriers completed again | 0 |
| `CONFLICT` | Changed expected fences, reused operation with different request, lock contention or full intent capacity | 4 |
| `UNVERIFIED` | Unsafe/unsupported history, unavailable SQLite, changed reads or unknown commit/sync outcome | 3 |

Success output contains only fixed status/reason codes, public `operation_id`,
`comment_sha256`, `mutation_authorized: false` and `remote_effects_enabled: false`.
It contains no body, private IDs, paths or task fingerprint. Failure omits operation
and digest. Exit 0 certifies local recording only, never remote-effect readiness.

An exact operation/body alone is insufficient for replay: current task metadata,
revision, worker, generation and session must still match. An updated task with
unchanged revision still conflicts with its retained full-task fingerprint.
An interrupted pre-commit transaction rolls back migration and row together.
A committed row followed by failed acknowledgment/fsync may remain as observed
pending intent; the command reports `UNVERIFIED`, never ready or published. Exact
fresh retry verifies the retained request, fsyncs the selected no-follow database
descriptor and its directories, then acknowledges pending intent. Failed append/
insert can be retried from the complete explicit inputs after a fresh match.
Corrupt or ambiguous history requires operator inspection, not invented recovery.

Older readers reject version 3 and the additional table before replay. Upgrade all
consumers before sharing a version-3 store. For rollback or retention limits,
preserve/archive the entire database with its SQLite sidecars after quiescing
writers; never strip the intent table or downgrade metadata to make old readers
accept it. A newly initialized store has a new private incarnation and does not
certify continuity with an archived store.

A future separately reviewed remote integration needs explicit public-text
approval, independent current-actor/task authority and
remote identity checks, concurrency/retry rules, and independently observed
publication receipts. A retained match alone cannot supply those guarantees.

`tests/journal-claim-intent-test.py` adds actual schema-3 core CLI fixtures,
before/after observation and binding compatibility, rollback/retry boundaries,
strict history validation, full capacity, bounded SQLite contention and unsafe
filesystem/output cases. It is registered in `make test`/`make check`. Its pinned
old-reader schema-guard excerpt establishes refusal, not a complete historical
reader execution or proof that an old writable open has no filesystem/SQLite
side effects before reaching that guard. The actual binding regression exercises
`candidate_binding.bind` before and after migration by a separately created and
claimed issue-backed task. A real SQLite connection subclass simulates commit
failure at the transaction-context boundary and verifies rollback of migration
and intent, sanitized failure output and successful fresh retry.

`tests/prepare-task-claim-test.py` is included in `make test`/`make check`.
Its schema-3 positive fixtures come from the actual copied core CLI's create,
process-bound claim and transition operations in temporary guest-local storage;
adversarial fixtures check raw task/lease changes and sanitized no-effect results.
Execute that suite and repository checks only inside an independently justified
isolated environment.

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

### Correlate one pending intent with fresh visible comments

`scripts/observe-claim-intent.py` composes the existing preparation/preflight and
schema-3 journal validation APIs with the live GET-only observer. Run only in an
independently justified isolated environment:

```sh
python3 -I -B scripts/observe-claim-intent.py \
  --authority-root /physical/workspace --invoking-root /physical/workspace \
  --task-id local-task --expected-revision 2 \
  --expected-worker-id aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --expected-session-id private-fixture-session --expected-generation 1 \
  --repo acme/widgets --branch feat/native-claim --issue 117 \
  --actor octocat --scope implementation \
  --claim-id 0123456789abcdef0123456789abcdef \
  --operation-id fedcba9876543210fedcba9876543210
```

Every preparation argument is required and single-occurrence. Optional
`--store-id` adds a caller-supplied private incarnation fence: exactly 32 lowercase
hexadecimal characters, matching the validated database's actual store ID. It is
never printed. Omitting it selects the existing validated store at the explicit
authority root; it does not establish continuity with an archived incarnation.
Sixteen-character IDs, duplicate options and capture/summary-file options are
refused. No directory, task state, database, acknowledgment or assignment is
created or updated.

Before any network call, physical authority/invoking roots must agree, the actual
schema-3 preflight and preparation must match current fences, and the existing
private journal must validate in full. The fixed parameterized query selects
exactly one unique operation ID. Its validated canonical request must match the
fresh preparation's exact claim/body/digest and the complete retained task
fingerprint, incarnation, revision, worker, session and generation. A historical
intent whose task has changed is refused before GET, even when its public text
still matches. The recording CLI currently constructs its request inline; this
reader reuses its imported preparation parser/API and journal validator and
compares fields directly, rather than duplicating a request builder.

The database is opened with the existing `open_store(..., writable=False)` API;
there is no migration or intent/observation write. Recovery sidecars and a WAL
database header are refused **before** opening SQLite, avoiding read-only WAL
shared-memory creation. Unsafe paths, permissions, links, unknown rows, digests
or schemas remain failures. Quiescing/recovering a journal is a separate operator
action; this reader does not repair it.

The selected row, database/sidecar fingerprints, physical root/directory identities,
task and lease-file fingerprints are captured privately in memory before and
after the network interval. The local SQLite connection and descriptors close
before GET. No coordinator lock is acquired (its existing API creates a lock
directory), so no global lock is held over network calls. The second local read
revalidates current task/preparation and journal data; any changed or unavailable
local evidence produces `UNVERIFIED / LOCAL_SNAPSHOT_CHANGED`, including when a
remote conflict was observed. This is repeated retained consistency, not an
atomic snapshot or protection against noncooperating writers.

The internal observer receives only the just-validated expected body in memory.
It compares the bounded raw comment's exact bytes/SHA-256 and full canonical
marker, including claim/operation IDs and expected actor, during the fresh actual
traversal. A visible match additionally requires author login and immutable ID to
match the authenticated `GET /user` account. A same-login imposter ID, another
author, competing claim or duplicate operation cannot become a match. A valid
canonical claim with a changed payload, including the same operation ID, is a
conflict. Every malformed/noncanonical body remains `UNVERIFIED`: prose mentions,
quoted or partial markers, an operation ID outside the payload, and edits to the
fixed human summary cannot establish attribution to the expected operation.
Only the existing strict codec parses claims; there is no permissive attribution
parser or substring-based conflict inference. Malformed captures/pages and
incomplete traversal also remain unverified. Standalone observer summaries and
caller-supplied files cannot be
upgraded into an intent observation. Transport retains the existing shared
60-second network deadline, 512 KiB combined-output budget and ten-page bound;
one-page observation requires five GET calls. Local pre/post reads are outside
that network deadline and SQLite retains its existing two-second busy timeout.

| Intent observation | Meaning | Exit |
| --- | --- | --- |
| `VISIBLE_MATCH` | One exact pending body from the authenticated current actor, no observed competing claims, unchanged retained local evidence | 3 |
| `UNVERIFIED / NO_MATCH_OBSERVED` | Valid fresh visible traversal without an exact claim; absence is not authorizing | 3 |
| `CONFLICT` | Pre-network task/request/store mismatch, or observed valid canonical competing/different-payload/actor-mismatched claim | 4 |
| `UNVERIFIED` | Malformed/noncanonical comment body, invalid/unavailable inputs or storage, stale/inactive task structure, transport failure, or changed local evidence | 3 |

Output contains fixed statuses, numeric repository/issue/comment IDs, counts and
flags, and only for a visible match its exact public-body digest. No body, login,
public claim/operation metadata, private store/task/worker/session identifiers,
task fingerprint, filesystem path or raw exception text is emitted.
`current_task_authority` and `remote_operation_completion` always remain
`UNVERIFIED`; `mutation_authorized`, `absence_authorizing` and `atomic_snapshot`
remain false. `complete_pagination` has only the measured visible meaning above.

A fresh visible match can help correlate an exact pending request after a
hypothetical independently authorized publication or interrupted acknowledgment.
It is not a publication receipt, proof of who performed a write, remote operation
completion, admission, public-text approval, session authentication or authority
to retry a write. The reader persists no remote outcome. Removed markers, deleted
history, invisible comments and concurrent edits missed by equal issue anchors
remain limitations. This integration supplies no live qualification evidence.

`tests/observe-claim-intent-test.py` contains 17 test methods using actual schema-3
task create/claim/transition and intent-recording CLIs with temporary guest-local
storage and deterministic fake `gh` responses. Three additional internal-matcher
methods in `tests/observe-github-claims-test.py` cover exact body/current-ID matching
and conflict precedence, including malformed-body non-attribution. Fixtures
exercise exit distinctions, stale-before-GET
refusal, private output, unchanged storage, malformed pagination, timeout, issue
changes and task/lease/journal changes across GET. These are offline fixtures,
not genuine GitHub observations or proof of hostile-filesystem isolation. Both
suites are registered in `make test`/`make check`; run them only in an independently
justified isolated environment.

### Offline capture bounds

Capture input is strict UTF-8 JSON, at most 1,000,000 bytes, 2,000 comments and
32 levels of nested values. Strings (including bodies) are at most 65,536 UTF-8
bytes. Duplicate JSON keys, nonfinite constants, invalid Unicode and unsafe
relevant-field types are refused. A physical absolute path is required: symlinks
in any component, hardlinked/nonregular files, and changed file stat/path identity
during the bounded read are refused. These checks do not authenticate the file or
turn the host workspace into a sandbox.

Future remote-effect work needs separately reviewed publication approval,
identity/provenance and concurrency guarantees beyond the read-only intent
correlation above. Public preparation must remain
separate from private journal identifiers. Local persistence adds no mirror
state, custom capture envelope, mutation adapter, or new admission state.

The offline fixture suites are `tests/native-claim-test.py` and
`tests/observe-github-claims-test.py`, included in `make test`
and therefore `make check`. Execute fixtures and repository checks only in an
independently justified isolated environment. Representative REST fixtures use
fictitious public values and never make GitHub requests. Observer fixtures provide
a deterministic fake `gh` executable that validates exact GET arguments and
sanitized environment before supplying adversarial HTTP responses.

[rest]: https://docs.github.com/en/rest/issues/comments#list-issue-comments
