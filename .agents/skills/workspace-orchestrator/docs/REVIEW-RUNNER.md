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

Artifacts are `transcript.jsonl`, `session-export.json`, `stderr.txt`, and
`receipt.json`. They may contain source and review text and must stay private.
Receipts bind runtime binary, declared model/agent, input bytes, stream bytes,
exit code, timing and observed session. They report candidate readiness and
execution credit as false. Controller collection must verify source/assignment
bindings and copy evidence outside the worker before relying on it. Files in a
worker-writable directory are staging, not immutable accepted evidence.

The adapter signals its guest-local process group on exit/timeout. That does not
prove detached descendants are gone; externally owned sandbox removal remains
the cleanup boundary. Startup, termination and credentials require the actual
runtime contract, not just the `--isolated-guest` declaration.

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
