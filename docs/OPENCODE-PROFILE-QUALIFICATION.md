# OpenCode 2.0.32 profile policy qualification

This explicit diagnostic runs only inside an operator-provided, network-disabled
disposable Linux guest. Before runtime work it creates private user and network
namespaces, preserves the non-root UID/GID through single-ID maps, and enables
only the private loopback interface. If those prerequisites fail, it refuses
before generating passwords or launching runtime children. It starts its own
authenticated loopback server; it never
attaches to the host's managed service, calls a provider or dispatches an agent
tool. Multipass and a particular container runtime are not dependencies.

```sh
python3 -I -B scripts/qualify-opencode-profile.py \
  --isolated-guest --binary /runtime/opencode \
  --expected-sha 4199ae2d2c96ad2a140d32cabe6a1d9280b4cd1d9d8ed533a5431f54c422693c \
  --output /work/profile-policy --timeout 180
```

Use a fresh output directory outside any mounted repository or existing
configuration ancestry. The binary digest is operator-selected; the program
also requires the observed version string `opencode v2.0.32`. It is not an
automatic installer or a general adapter for untested runtime versions.

## Measured interfaces and source selection

The pinned binary advertises `api --server` and `serve --hostname --port`.
Its embedded web client's advertised routes were inspected before requests
were made. In a single shared guest-local server:

- `GET /api/config` returns a source array of document/directory records.
- `GET /api/agent/{id}` returns a location-bound resolved agent, including
  its ordered permission rules.
- `POST /api/session` creates a fixture session for that agent.
- `POST /api/session/{id}/permission` with a `per_…` request ID evaluates
  `read`, `edit`, `shell`, and `subagent` resources and returns allow/deny.

Server authentication uses a newly generated synthetic password, passed only
through a fresh allowlisted environment. Server stdout/stderr are discarded
because the runtime prints authentication data there. Client stdout is bounded
and parsed; raw client stderr is counted but not retained. No existing HOME,
credentials, SSH agent, proxy or provider environment is inherited.

## Qualification result, not launch authority

The probe requires all four cases, with independent private state and owned
server lifetime for each:

| Case | Required observation |
|---|---|
| Clean XDG profile | Exact selected sources and ordered resolved rules; read allowed; edit/shell/subagent denied |
| Conflicting same-name project profile | Both exact documents observed; project allow-all appended after selected rules; all four requests allowed; contamination reported |
| Missing selected profile | Exact source inventory confirms selected document absent; cannot qualify |
| Malformed selected profile | Exact source inventory confirms invalid document was not loaded; cannot qualify |

Unknown schemas, failed positive controls, unexpected sources, changed profile
bytes, timeout, unavailable server or failed cleanup yield UNVERIFIED/exit3.
Successful matrix observation yields PROFILE_POLICY_OBSERVED/exit0. The conflict
case is a **negative control**, not a permitted launch configuration.

The result explicitly retains `tool_dispatch_enforcement: UNVERIFIED` and
`launch_authorized: false`. A permission API decision is not evidence that actual
tool dispatch rejected an effect. A read-only filesystem refusal, invalid tool
arguments, model refusal or unavailable provider cannot stand in for that test.
The server mode is measured; equivalence to `run --standalone` is not claimed.

## Actual 2026-11-04 observations

The operator-authorized Docker run used a network-none, resource-bounded guest,
the existing pinned Node22 image and Linux ARM64 OpenCode2.0.32 at the digest
above. No host ports were published. The retained clean report records:

```text
status: PROFILE_POLICY_OBSERVED
clean: read=allow, edit=deny, shell=deny, subagent=deny
conflict: read=allow, edit=allow, shell=allow, subagent=allow
missing: CANNOT_QUALIFY (selected document not loaded)
malformed: CANNOT_QUALIFY (selected document not loaded)
tool_dispatch_enforcement: UNVERIFIED
launch_authorized: false
```

Earlier exploratory calls are not counted as successful qualification. Private
per-command API servers reported empty agent inventories and all-deny responses,
including the supposed positive control. Incorrect JSON query encoding failed
explicitly. An empty synthetic `.git` directory also prevented expected project
initialization and was removed from the fixture. A run with runtime scratch
under the mounted repository correctly reported source-directory contamination.
None of those outputs was treated as effective policy evidence.

After independent review, a hardened MSB0.7.11 run additionally verified that
user and network namespace identities changed, the non-root identity was
preserved, and the interface set was exactly loopback. The same four-case policy
matrix passed. Standard Docker's current outer policy refused unprivileged
namespace creation; it is not a qualified runtime for this hardened probe.
Neither the outer Docker policy nor any host namespace was modified.

The successful run generated fresh random agent markers and authenticated
requests, checked source/profile hashes before and after, and killed owned
server/client process groups. The sanitized report and its hash manifest were
copied from guest-local scratch before disposal; no raw service database or
password log is part of the evidence. This is controlled fixture qualification,
not production controller promotion or hardware/process attestation.

## Bounds and remaining work

The operator chooses a high starting port for four sequential guest-local
servers. The wall budget is at most180 seconds, individual client calls at most
8 seconds, each stream256KiB, profiles64KiB and binary512MiB. Readiness and
agent lookup retries are bounded. Cleanup and report writes have separate small
waits. Recursive scratch cleanup and filesystem report writes have no intrinsic
wall-clock bound; a hard outer sandbox lifetime remains necessary for detached descendants
or uninterruptible operations.

## Completed evidence publication

Successful observations are not authoritative from `report.json` alone. That
file retains status UNVERIFIED and a separate observation_status until the
complete READY → manifest → report hash chain validates. Stage files and final
files are exclusively created; READY is linked last. Interrupted publication
never turns a standalone report into a success, and partial output is not
automatically overwritten. Inspect completed evidence without launching a runtime:

```sh
python3 -I -B scripts/qualify-opencode-profile.py --inspect-output /work/profile-policy
```

The hardened MSB export validated before teardown and its copied report/manifest
hashes matched READY. Report SHA-256:
`48a443fba3eea14c99eaa008a78ef16861462990dc7eaa7fd9b64bf530493379`.
Manifest SHA-256:
`566f4328f7957234755e5de4e2b138c6adbcf4e204d43831120c77728b8fe989`.
Raw runtime output is not retained. Decoded response strings, generated request
paths and final serialized evidence are checked against every synthetic password
so JSON-escaped echoes cannot enter the report. This is not general secret
discovery or proof against an adversary rewriting all artifacts coherently.

Before enabling the materialized-review launcher, qualify the actual tool
dispatch boundary with allowed-read and denied-effect controls, and connect the
admission reservation to an irreversible pre-spawn consumption. The launcher
must enforce a clean, independently controlled configuration layout and reject
unexpected sources rather than assume HOME/XDG selection excludes project config.
This probe changes no permissions, credentials, services or task state outside
its explicitly created guest fixture.
