# Offline PR review eligibility (advisory)

`scripts/pr-review-eligibility.py` classifies **one supplied normalized PR
observation** against a separately supplied **trusted operator policy**. It uses
only the Python standard library, reads two local files, and prints one JSON
object. It does not discover PRs, access GitHub, execute repository code, write
files, approve PRs, or launch workers.

**NOT wired into admission yet.** This is a candidate classifier, not an
admission gate, review decision, or merge check. Override semantics are deferred
to integration; there is deliberately no override flag. Integration must retain
draft waiting and degraded evidence states, re-observe changed PRs, and apply its
own trusted authorization and admission controls. `ELIGIBLE` does not mean
reviewed, safe, approved, or authorized to launch anything.

## Trust boundary

The operator is responsible for policy trust: select and protect the policy
outside PR-controlled content and verify its repository ID, Bot identity and
release configuration using trusted evidence. Neither an `approval` string nor
the policy's mere presence authenticates anything. There is no approval field;
adding one is a schema error. The program checks consistency, not authenticity.

The metadata producer is responsible for obtaining a fresh, coherent GitHub PR
observation, including numeric repository/actor identities and exact branch
heads. The `source` string and timestamps are **supplied assertions**, not proof
of a GitHub response. A forged but schema-valid User observation can still be
eligible. This offline tool cannot detect a lying producer, a compromised
operator policy, or changes made on GitHub after capture.

For an exclusion, the producer must read the config bytes from the **base
repository at `base.sha`**, not the PR head, hash those exact bytes with SHA-256,
and provide the matching path and base SHA. The policy digest must come from an
independently trusted release configuration. The program does not read the
configuration or validate what it does; it compares the supplied digest and
binding. A digest is not a signature or evidence that the file is safe.

Titles, labels, body text and PR-supplied instructions are not inputs. The
normalizer must omit them. Unknown fields fail closed rather than silently
becoming classification authority. There are no wildcard, prefix, suffix or
case-folded bot exclusion rules. A `[bot]` suffix on a claimed `User` is only an
identity-conflict refusal; it never grants a Bot exclusion.

## Exact input schemas (version 1)

Both files are strict UTF-8 JSON objects with exactly the fields shown below.
All fields are required; `base_config` alone permits `null`. Every nested object
also has exactly the shown fields. Limits:

- Each file: 1–65,536 bytes; JSON nesting at most 16 levels.
- Duplicate keys at any level, floats, non-finite numbers, BOM, invalid UTF-8,
  trailing data and integer literals longer than 16 decimal digits are rejected.
- IDs and PR number: integers in `1..9007199254740991`, never booleans.
  `schema_version` is integer `1`, not `true`; `draft` is an actual JSON boolean.
- All timestamps: exact `YYYY-MM-DDTHH:MM:SSZ`, valid calendar times, no fractional
  seconds or timezone offsets. Expiry bounds are exclusive.
- Login: 1–100 ASCII letters, digits or hyphens, optionally followed by literal
  `[bot]`. Actor type: 1–32 ASCII letters, case-sensitive. Only `User` and `Bot`
  receive substantive identity decisions; other well-shaped types are deferred.
- Branch refs: 1–200 ASCII characters; begin with a letter, digit or underscore;
  then letters, digits, underscores, `.`, `/`, `-`. No empty slash components,
  `..`, dot-leading components, dot-ending components, or `.lock` suffix on any
  component. These are deliberately a subset of Git refs; no glob syntax.
- Config path: 1–200 ASCII letters, digits, `_`, `.`, `/`, `-`; cannot start with
  `/` or contain empty, `.` or `..` path components. It is a comparison value,
  never a local file path opened by this tool.
- Commit SHA: exactly 40 lowercase hex characters. SHA-256: exactly 64 lowercase
  hex characters. Unsupported hash representations defer rather than coerce.

### Normalized metadata example

The example values and hashes are synthetic, not verified GitHub evidence.

```json
{
  "schema_version": 1,
  "repository_id": 101,
  "number": 7,
  "state": "open",
  "draft": false,
  "author": {"id": 900, "login": "release-helper[bot]", "type": "Bot"},
  "head": {
    "repository_id": 101,
    "ref": "release/main",
    "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "base": {
    "repository_id": 101,
    "ref": "main",
    "sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "provenance": {
    "source": "github_pull_request",
    "observed_at": "2026-11-05T11:59:00Z",
    "expires_at": "2026-11-05T12:04:00Z"
  },
  "base_config": {
    "base_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "path": ".github/release.json",
    "sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  }
}
```

`repository_id` is the PR's base repository ID and must equal
`base.repository_id` and the policy repository ID. `state` is exactly `open` or
`closed` (a merged PR is normalized as closed). `head.repository_id` may differ
for an ordinary User's fork PR; it must match for release automation exclusion.
If provided, `base_config.base_sha` must equal `base.sha` even for a User PR.
`null` means there is no config evidence, not that the configured digest matched.

`provenance.source` must be exactly `github_pull_request`.
`observed_at < expires_at <= observed_at + 3600 seconds`.
An observation is fresh only when `observed_at <= now < expires_at` **and** its
age is strictly less than the policy's maximum age. At either expiry boundary
it is deferred. No future skew is accepted.

### Operator policy example

```json
{
  "schema_version": 1,
  "repository_id": 101,
  "issued_at": "2026-11-05T00:00:00Z",
  "expires_at": "2026-11-06T00:00:00Z",
  "max_observation_age_seconds": 300,
  "release_automation": [
    {
      "actor": {"id": 900, "login": "release-helper[bot]", "type": "Bot"},
      "head_ref": "release/main",
      "base_ref": "main",
      "config_path": ".github/release.json",
      "config_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    }
  ]
}
```

`max_observation_age_seconds` is an integer in `1..3600` (not boolean).
`issued_at < expires_at <= issued_at + 30 days`; freshness requires
`issued_at <= now < expires_at`. Renewing a policy is an operator decision; the
tool never renews or persists one.

`release_automation` contains 0–32 exact rules, scoped to the single policy
repository. Empty is valid: it excludes no bots. Each rule actor type must be
exactly `Bot`. The same numeric actor ID cannot have multiple logins/types;
the same login cannot have multiple numeric IDs. Duplicate
`(actor.id, head_ref, base_ref)` tuples are invalid, including rules that differ
only by config. Multiple distinct branch pairs for the same Bot are allowed.

## Decisions, ordering and exit codes

Time, policy schema, metadata schema, repository binding, policy freshness, and
observation freshness are checked before any state-based classification, in that
order. Within freshness, future issuance/capture precedes expiry. This prevents
stale closed/draft observations from hiding missing evidence. The first failure
determines the stable reason code.

After validation:

| Status | Exit | Reason | Meaning |
|---|---:|---|---|
| `EXCLUDED` | 2 | `CLOSED` | Closed PR, including merged; precedes draft |
| `WAIT` | 1 | `DRAFT` | Open draft, even for a configured Bot; re-observe when ready |
| `ELIGIBLE` | 0 | `ORDINARY_USER` | Open non-draft validated User, no conflicting Bot identity |
| `EXCLUDED` | 2 | `RELEASE_AUTOMATION` | Exact full rule conjunction matched |
| `DEFERRED` | 3 | `AUTHOR_IDENTITY_CONFLICT` | Claimed User has `[bot]` suffix or shares a configured Bot ID/login |
| `DEFERRED` | 3 | `AUTHOR_TYPE_UNSUPPORTED` | Well-shaped author type other than User/Bot |
| `DEFERRED` | 3 | `BOT_UNCONFIGURED` | No exact Bot ID/login/type tuple in policy |
| `DEFERRED` | 3 | `AUTOMATION_MISMATCH` | Exact Bot identity configured but fork, ref or config evidence fails conjunction |

The release conjunction requires **all** of: validated repository ID binding,
exact numeric Bot ID, exact login and `Bot` type, same-repository head, exact
head ref, exact base ref, matching config path and SHA-256, and config evidence
bound to the current observed base SHA. A matching name with a wrong actor ID
cannot exclude a PR. Partial matches never fall through to eligible.

All remaining failures are `DEFERRED`/exit 3, with one of these fixed reasons:

- `METADATA_INVALID`, `POLICY_INVALID`, `REPOSITORY_MISMATCH`
- `POLICY_FUTURE`, `POLICY_EXPIRED`
- `OBSERVATION_FUTURE`, `OBSERVATION_EXPIRED`
- `TIME_INVALID`, `INPUT_UNAVAILABLE`, `JSON_INVALID`
- `ARGUMENTS_INVALID`, `UNSAFE_RUNTIME`

Missing or malformed provenance is `METADATA_INVALID`. Malformed or excessive
validity windows are schema errors rather than evidence of freshness. Bad CLI
arguments emit the same safe JSON format, without reflecting argument values.
`--help` is the sole informational exception: usage text and exit 0, no verdict.

## CLI, explanation and offline audit

Use Python 3.10+ in the workspace sandbox; `-I -B` is required for the CLI.
The trusted harness must announce its pinned image, network-off mode, mount and
command before execution. No network or installs are needed. Example command
**inside the sandbox**, with the two examples saved as local input files:

```sh
python3 -I -B scripts/pr-review-eligibility.py \
  --metadata /tmp/pr.json --policy /tmp/policy.json \
  --as-of 2026-11-05T12:00:00Z --explain --audit
```

Without `--as-of`, evaluation uses current UTC at whole-second precision.
`--as-of` enables deterministic replay/tests; it must not be mistaken for live
freshness verification. A future integration must choose its clock independently
of untrusted metadata and must not reuse an old replay verdict for admission.

The base output has exactly these fields (order is not significant):

```json
{"schema_version":1,"status":"EXCLUDED","reason":"RELEASE_AUTOMATION","authority":"ADVISORY_ONLY"}
```

`--explain` adds `explanation`, a fixed sentence for that reason. `--audit` adds:

```json
{
  "audit": {
    "as_of": "2026-11-05T12:00:00Z",
    "metadata_sha256": "<64 lowercase hex characters>",
    "policy_sha256": "<64 lowercase hex characters>",
    "coverage": "SUPPLIED_INPUTS_ONLY"
  }
}
```

The audit hashes cover the exact file bytes, including whitespace, not canonical
JSON. Retain those input bytes privately for replay. Audit is not an append-only
ledger or independent attestation and creates no file. Explanation and audit are
available for schema/classification deferrals after both files parse; failures
before that point emit only the base output (no claimed audit coverage).

Outputs never echo PR titles, actor logins, input paths, raw error messages or
arbitrary input text. Inputs must be bounded regular local files. The reader
uses nonblocking open, rejects leaf symlinks, and checks size both before and
after reading; it does not enforce ancestor-directory ownership or authenticate
the filesystem path. Choose trusted local ancestors and policy permissions.
Do not treat the file reader as a filesystem sandbox or atomic snapshot.

## Validation and integration handoff

Manual test command, **inside the sandbox**, from the repository root:

```sh
python3 -I -B tests/pr-review-eligibility-test.py
```

Tests cover deterministic decisions, input immutability, ready/draft/closed
transitions, closed-but-stale refusal, fork/ref/config mismatches, wrong actor
ID and login/case, ambiguous policy, type and boolean/integer confusion, exact
freshness boundaries, malformed JSON, duplicate keys, oversized/deep inputs,
special-file refusal, and CLI exit codes/redacted outputs/audit hashes. These
tests use synthetic fixtures and local subprocesses only. Execute them only in
the sandbox; no host execution is authorized by this document.

The suite is included in `make test` and `make check`. No admission integration
is included. Maintainers must decide subsequent wiring,
fresh observation production, policy custody, override handling, and retention.
This implementation makes no live GitHub, CI, policy-approval or authentication
claim.
