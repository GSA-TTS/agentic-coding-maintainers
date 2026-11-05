# Offline tool-dispatch qualification

This opt-in diagnostic drives the **actual pinned runtime dispatcher** with a
deterministic guest-local model stub. It complements the profile-policy API
probe; it does not enable review launching, grant credentials or prove general
agent safety. Default tests use synthetic evidence and do not run OpenCode.

```sh
python3 -I -B scripts/qualify-opencode-tools.py \
  --isolated-guest --binary /runtime/opencode \
  --expected-sha 4199ae2d2c96ad2a140d32cabe6a1d9280b4cd1d9d8ed533a5431f54c422693c \
  --output /tmp/dispatch-observation --timeout 180
python3 -I -B scripts/qualify-opencode-tools.py \
  --inspect-output /tmp/dispatch-observation
```

The independently provisioned outer guest must have external networking off and
no sensitive mounts or credentials. The diagnostic reuses the profile probe's
private user/network namespace setup before binding any listener or launching
the runtime. It preserves a nonzero UID, maps only that identity, and enables
private loopback. Namespace refusal is UNVERIFIED; no bypass mode exists.

## Runtime and cases

The measured binary is Linux ARM64 OpenCode 2.0.32 at the SHA-256 above. Fresh
HOME/XDG state configures `@ai-sdk/openai-compatible` to a synthetic Chat
Completions endpoint on private loopback. In the measured runtime this adapter
worked without fetching packages. Another binary/package layout needs its own
qualification; unavailable adapters cannot trigger downloads or remote fallback.

The stub emits valid SSE tool calls using observed runtime schemas. It receives
the runtime's subsequent tool-result message before advancing. Auxiliary title
requests and one child-session response are explicitly bounded; the stub never
executes the requested tools or fabricates their results. Evidence correlates
call ID, session, arguments, stream event, model request/result, session export,
and independently observed filesystem/session state.

| Case | Required observation |
|---|---|
| Read allowed | Exact fixture contents returned by a completed read |
| Edit allowed | Prior read, then the exact target-byte change |
| Edit denied | Same valid call, explicit `permission.rejected`, unchanged writable target |
| Shell allowed | Exact guest-only marker created |
| Shell denied | Same valid command, explicit `permission.rejected`, no marker |
| Subagent allowed | One child bound to its parent, completing through the stub |
| Subagent denied | Explicit `permission.rejected`, no child session or child-model request |
| Unknown tool control | Distinct `tool.execution` unavailable-tool response |
| Invalid argument control | Distinct argument-validation response for a known tool |

Resource-specific denial keeps the tool available. For edit, the measured policy
resource is repository-relative `target.txt`, despite an absolute tool argument.
The earlier absolute-resource rule did not match and the disposable edit occurred;
that observation is **not** labelled a demonstrated security bypass. The exact
shell command and subagent name `general` are the other denied resources.

Global deny-all/read-allow instead removes these tools from the advertised list;
unsolicited calls returned unavailable-tool errors. That is filtering evidence,
not permission-denial evidence, and cannot satisfy this matrix's denial cases.

## Measured result and evidence limits

The authorized MSB 0.7.11 trial, using the cached pinned development image and
OpenCode binary, completed all nine cases with no external model service. Its
inspector reported TOOL_DISPATCH_OBSERVED. Read/edit/shell/subagent controls
completed; the three deny cases returned DENIED; the negative controls returned
UNAVAILABLE and INVALID_ARGUMENTS. The evidence was exported while the guest
remained available. It includes the original requests/SSE responses, runtime
events, complete bounded session inventories/exports and fixture snapshots.

This qualifies **these exact dispatch cases**, not every tool, resource pattern,
runtime version or provider. A genuine read-only-filesystem negative control is
not included and no filesystem-enforcement claim is made for one. Final snapshots
cannot prove absence of every transient side effect. Reported provider cost/token
zeros are synthetic and not real-model billing or performance evidence.

The fixed runtime uses `run --standalone` for each fresh case. Session export and
inventory use the same isolated HOME/XDG store and are correlated to that case.
The separate profile-policy probe used an owned server; neither mode is silently
substituted for the other. The final runtime-profile and launcher-admission
integration still needs its own explicit authorization and tests.

## Bounds, publication and cleanup

At most nine cases, 12 model requests per case, 256KiB per request/stream,
17 seconds per case and an overall requested budget of at most180 seconds.
The HTTP handler bounds header/body reads; no auth headers are retained. Only
synthetic fixture state is available. Process-group cleanup uses the existing
bounded runner; an external guest lifetime remains required for escaped
descendants or uninterruptible filesystem cleanup.

Each case is retained separately. Report status alone remains UNVERIFIED.
Exclusive staged files and a READY-last manifest bind the complete evidence;
`--inspect-output` reconstructs the conversation and checks all case semantics
before returning TOOL_DISPATCH_OBSERVED. Missing, malformed, truncated, contradictory,
unexpected-effect or incomplete-cleanup evidence yields UNVERIFIED/exit3, never
a qualification pass. The inspector is read-only. Hashes prove internal content
consistency, not trustworthy provenance against coordinated rewriting.

Outputs always retain `launch_authorized: false`. There is no task admission,
inference consumption, remote write, approval or merge. The next delivery step
must bind this measured layout to trusted runtime/profile installation and the
controller's pre-spawn attempt-consumption protocol.
