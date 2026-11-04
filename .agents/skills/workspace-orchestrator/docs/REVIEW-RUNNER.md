# Bounded OpenCode review adapter

`run.sh review-run` invokes one installed OpenCode v2 CLI inside an externally
qualified worker guest. It is **not an isolation boundary** or an acq provisioner.
The controller supplies read-only installed policy, source and runtime binary;
the guest receives only its allowed provider credential, never GitHub or
controller-state credentials. The worker cannot promote its own receipts.

```bash
python3 -I -B /installed/review-run.py --isolated-guest \
  --binary /runtime/opencode --binary-sha256 EXPECTED_SHA256 \
  --cwd /home/node/review --source /candidate/source.py \
  --model usai/gpt-6-astra --agent bounded-reviewer \
  --environment-file /private/reviewer-environment.json \
  --output /home/node/review/attempt-1 --timeout 300
```

The default timeout is 300 seconds, maximum 600. Up to 20 explicit regular
source files, each at most 1 MB, are hashed before and after invocation. The
combined stdout/stderr bound is 4 MB. Changed input, malformed output, missing
source-read events, provider errors, nonzero exit, multiple session identities,
or missing terminal evidence produce `UNVERIFIED` and exit 3. An existing output
directory is refused rather than overwritten. Invocation uses an argument array,
not a model-authored shell command. The named agent's step/permission limits are
installed by the controller, outside the candidate checkout.

OpenCode 2.0.32 can omit the final `step_finish` event while exiting zero with a
final response. The adapter additionally obtains the same session's export and
requires a succeeded session, a stopped final assistant message and identical
final text. Export usage supplies measured token totals. Failed exports cannot
repair an invalid stream. `REVIEW_OBSERVED` means these runtime observations
exist, not that findings are correct, all relevant context was read, or tests
passed. Read events record tool success, not proof of full-file reasoning.

Artifacts are `transcript.jsonl`, `session-export.json`, `stderr.txt`, `export-stderr.txt`, and
`receipt.json`. They may contain source and review text and must stay private.
Normal receipts bind runtime binary, declared model/agent, input bytes, stream bytes,
exit code, timing and observed session. They report candidate readiness and
execution credit as false. Controller collection must verify source/assignment
bindings and copy evidence outside the worker before relying on it. Files in a
worker-writable directory are staging, not immutable accepted evidence.

The adapter installs cleanup immediately after spawning, including failures in
selector construction, registration and stream reads. It signals the guest-local
process group with SIGKILL and waits at most **3 seconds** for the direct child
during cleanup, then closes selector and pipe resources. There is no implicit
unbounded `Popen` context-manager wait. Signal/reap/close failures are recorded
as `failure` (or `export_failure`) and prevent `REVIEW_OBSERVED`, even if the
child exited zero. A failed inference does not start an export. Python
cancellation (`KeyboardInterrupt`/`SystemExit`) performs cleanup then propagates;
it starts no further invocation and does not produce a success receipt. A cleanup
failure during cancellation is attached as an exception note. Abrupt adapter
termination (including SIGKILL/default SIGTERM) cannot guarantee this cleanup.
Detached descendants and an unreaped child after a failed bounded wait require
externally owned sandbox removal. Startup, termination and credentials require
the actual runtime contract, not just the `--isolated-guest` declaration.

## Explicit environment prerequisite

`execute(command, cwd, timeout, env=None)` keeps its four-item return tuple
`(stdout, stderr, returncode, failure)`. A supplied mapping, including `{}`, is
copied and validated before spawn and passed directly to `Popen(env=...)`.
It is never merged with inherited variables or handoff/bundle content.

The CLI's optional `--environment-file` reads an operator-prepared JSON object
once and passes the same selection to both inference and same-session export.
The absolute path must have no symlink or `..` components. Starting at `/`,
each ancestor is opened descriptor-relative with `O_DIRECTORY | O_NOFOLLOW`,
then its descriptor's ownership and permissions are checked before opening the
next component. Directories must belong to root or the current guest caller and
have no group/other write permissions, except root-owned sticky directories such
as `/tmp`. The leaf is opened relative to the pinned parent with `O_NOFOLLOW`;
it must be regular, single-link, owned by the caller, and have no group/other
permission bits (use `0600`). Unsafe paths are refused, never automatically chmodded.
An ancestor replaced by a symlink cannot redirect an already pinned descriptor;
a symlink encountered before pinning is refused. This does not isolate against
the same user rewriting files, changing permissions or replacing directory
entries with other real directories. The operator still owns guest isolation.
Keep it outside source/handoff bundles and receipts. Duplicate names, non-string
values, NULs, invalid UTF-8, more than 64 names, or more than 32 KiB of total
UTF-8 value bytes are refused. The encoded file is bounded to 256 KiB.

The fixed name allowlist for both APIs is:

- `HOME`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME`,
  `XDG_RUNTIME_DIR`, `PATH`, `LANG`, `LC_ALL`, `TMPDIR`;
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `GEMINI_API_KEY`,
  `OPENROUTER_API_KEY`, `USAI_API_KEY`.

Only supply credentials for the approved provider. These names are permitted
inputs, not proof a particular runtime/provider consumes them. Loader/runtime
injection variables, arbitrary `XDG_*`, GitHub tokens, proxy settings and arbitrary
provider/configuration variables are refused. Environment-validation diagnostics
do not include supplied names or values. The environment mapping is not enumerated
in receipts; its selection is tagged `environment: "operator-supplied"`. Runtime
fields may echo nonsecret environment names/values such as HOME or PATH; these
are not redacted.

Before writing a receipt, the adapter checks its complete serialized JSON for
every **nonempty selected provider credential value**, including JSON-escaped
forms. A match anywhere (including final text, session IDs, nested fields or
declared runtime fields) replaces the entire receipt with the fixed diagnostic
`{"schema_version":1,"status":"UNVERIFIED","reason":"selected credential disclosure"}`
and exits 3. This also applies to already-degraded receipts. Normal successful
receipts retain their existing shape. Empty credentials alone are skipped;
short credentials may conservatively match unrelated receipt text. The minimal
diagnostic has no copied runtime-controlled strings (fixed diagnostic words may
coincidentally overlap a short value).

This check is not general secret detection: inherited/otherwise discovered
credentials and transformed/encoded secrets beyond JSON escaping are not covered.
Raw `transcript.jsonl`, `session-export.json`, `stderr.txt`, and
`export-stderr.txt` intentionally retain exact private evidence and can contain
credentials even when a receipt is refused. They remain mode `0600` and must not
be published; receipt refusal does not sanitize raw evidence.

Omitting the option preserves legacy inheritance and records
`environment: "inherited/unverified"`. That tag does not make credential
isolation verified. Even the explicit mode is **not a sandbox or proof of
effective configuration**: HOME/XDG/PATH and cwd can select installed files,
credentials or executables, and the runtime can discover additional config/auth.
The operator must qualify these paths and the guest independently.

**Materialized handoff launch remains BLOCKED.** `--profile` hashes supplied
bytes before/after; it neither selects nor enforces the OpenCode effective merged
configuration. Receipts explicitly label effective configuration unverified.
A launcher still needs version-qualified profile selection and authentication,
plus external durable attempt consumption before launch. This prerequisite adds
no launch, retry, admission or replay authority.

## Measured pilot boundaries

The 2026-10-29 pilot used OpenCode 2.0.32 and MSB 0.7.11 with restricted security,
UID 1000, 2 CPUs/2 GiB, nproc=128, no host ports, read-only source, and only gateway
DNS plus the USAi HTTPS hostname. The separately authorized managed-network
rebind setting enabled the provider route. Configuration and copied source
permissions must be readable by the guest reviewer; errors correctly yield no
review credit. Do not copy a developer's complete home/config into the guest.

Docker separately runs the protocol and repository tests. The manual real
review/owner-fix/re-review trial and this runnable adapter do not establish an
unattended acq workflow, task admission, live GitHub publication or merge authority.
# Source-map option

Handed-off plans pass `--source-map /review-input/source-map.json`. The installed
runner requires trusted sibling `review-source-map.py` and `review-handoff.py`.
The strict map preserves original path bytes, selected before/after sides and
base/head/packet identity separately from admitted context. Its complete source
inventory must match actual source hashes. The runner includes it as untrusted
prompt data, hashes it before/after invocation, and binds the initial digest in
`source_map_sha256`. Changed maps yield UNVERIFIED. This option is review-only.
See [source handoff](REVIEW-HANDOFF.md) for schema, layout and legacy collection
compatibility; a map is not runtime isolation or authenticity evidence.
