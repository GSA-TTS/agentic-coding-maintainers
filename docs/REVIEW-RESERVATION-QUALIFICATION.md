# Review reservation and offline configuration observations

AI-assisted qualification, 2026-11-04; base dcfbb636834fd4cd32359ba3850bdd2cc9d69f0a.

## Implemented boundary

The foreground controller can reserve an existing prepared reviewer admission
against one explicit destination, retain its exact handoff, and cancel it before
consumption. A different operation or output directory cannot reserve that same
admission again. No consume or launch operation is exposed. Results and frozen
exports always say launch_authorized:false and launch_gate:BLOCKED_PROFILE.

This is not proof of at-most-once inference: the later trusted launcher must
durably consume a reservation before spawning and prevent alternate-path retry.
The current code supplies the immutable identity, cancellation and lifecycle
guards that implementation will require. Opaque destination metadata does not
prove a container exists or identify its actual runtime configuration.

## Independent review and tests

Parallel architecture and security analysis identified the reservation and
effective-configuration boundaries. Parallel fixed-revision reviews found missing
reserve-pointer validation, missing-artifact reconciliation, malformed-epoch
mutation, and a direct execution-reconciliation guard bypass. These were fixed
and re-reviewed at a03e192b8c03965ffc1b5c09ae5afcc2baecf3d0. The subsequent
absent-history import optimization was independently reviewed at
0d0c08997225f596e99dea1f96f5da8d4c3d3a70; no further findings were identified.

Five reservation tests passed, comprising four workflow fixtures and one
structural/import sentinel with public-CLI and direct-API coverage in isolated guests,
covering exact replay, alternate-destination refusal, frozen export, pause,
dead-worker cancellation, retention loss, mutation guards and cancellation
capacity. The full Python3.12 Docker repository suite subsequently passed,
including the original76 foreground cases and all other suites. Live model and
generic runtime compatibility probes were not substituted for these tests.

Two earlier full local runs exceeded900 seconds. Profiling one original heavy
fixture consecutively yielded41.930s on base,33.214s before the fast path, and
35.044s after it; this does not demonstrate a wall-time regression or improvement.
The measured import reduction removes40 compilations/114 module executions for
that comparison. The successful complete local diagnostic used a1200-second
wrapper; the repository's ten-minute hosted job remains unchanged. Hosted
performance and pass/fail must be assessed separately.

The final suite tested code `0d0c08997225f596e99dea1f96f5da8d4c3d3a70`
using the cached Python3.12 Bookworm image
`sha256:a5bab0ff300f91231c2e68bf73a8a8d60762ac39ce1c50eaf6803e4c38a9062b`.
The disposable guest installed rsync, ShellCheck and jq, copied the source into
guest scratch, initialized fixture Git metadata, then executed as UID1000:

```sh
HOME=/work/home TMPDIR=/work/tmp make -C /work/candidate check
```

The command tool's wrapper timeout was1200 seconds, not the CI job timeout.
Observed output excerpts (exit0):

```text
review-reservation-test.py: Ran 5 tests in 72.862s — OK
foreground-delivery-test.py: Ran 76 tests in 509.034s — OK
import-sync tests: PASS
OpenCode runtime probes: SKIP (set OPENCODE_V1 and OPENCODE_V2)
python syntax: PASS (75 files)
json syntax: PASS (12 files)
shellcheck: PASS
repository checks: PASS
```

## Pinned runtime discovery experiment

An operator-authorized, network-off Docker guest ran the existing OpenCode
Linux ARM64 binary. Observed version2.0.32 and SHA-256:
`4199ae2d2c96ad2a140d32cabe6a1d9280b4cd1d9d8ed533a5431f54c422693c`.
It used fresh HOME/XDG directories, no credentials, no plugins or MCP fixtures,
and no provider network. All invocations were bounded and used `run --standalone`
with `invalid-provider/invalid-model`.

| Fixture | Selected XDG agent | Project-only agent |
|---|---|---|
| Empty home/config/project | Agent not found | Agent not found |
| XDG config containing selected agent | provider.no-route | Agent not found |
| Same XDG config plus competing project agent | provider.no-route | provider.no-route |

`provider.no-route` establishes that the agent was discovered before the invalid
model failed, not that a review ran or permissions were enforced. CLI help
describes `debug config` as listing configuration sources; it exposes no
standalone flag there. That inspection command was not invoked against an
existing managed service. No effective merged configuration API or precedence
guarantee was inferred.

Each discovery case used an empty environment except PATH and freshly created
HOME/XDG directories, with Docker network disabled. The selected fixture placed
a harmless `agents.qualification-only` entry in
`XDG_CONFIG_HOME/opencode/opencode.json`; the competing fixture additionally
placed `agents.project-only` in the working directory's `opencode.json`.
Both agents denied all tool permissions. Invocation pattern:

```sh
opencode run --standalone --agent qualification-only \
  --model invalid-provider/invalid-model --format json 'No provider is available.'
# Repeat with --agent project-only in each independent fixture.
```

Every invocation had a20-second subprocess timeout and returned exit1. Empty
cases emitted `Agent not found: "qualification-only"` / `"project-only"`.
Selected and competing agents found by discovery emitted
`{"type":"provider.no-route","message":"Model unavailable: invalid-provider/invalid-model"}`.
The full fixture and sanitized observation record are retained in the consumer
workspace's private `reviews/runtime-profile-20261104/` evidence directory.
Those outputs establish only discovery; there was no successful model call.

The experiment demonstrates that private HOME/XDG selection alone does not
exclude project configuration. Profile digest matching remains file identity,
not exclusive profile enforcement. Qualify the exact runtime's discovery and
permission behavior in an independently provisioned guest before enabling a
materialized-review launcher. No provider credentials, runtime override, remote
approval, service or controller promotion was activated by this experiment.
