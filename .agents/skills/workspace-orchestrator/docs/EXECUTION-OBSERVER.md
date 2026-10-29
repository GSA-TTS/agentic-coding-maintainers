# Foreground execution observation

This command adds controller-captured subprocess output and exact-output
assertions. It is not a general test-report parser, a sandbox provisioner, a
daemon, or whole-candidate readiness. Docker is the first transport. MSB's
reviewer pipeline remains separate until the execution transport is qualified.

## Trust boundary

Invoke `run.sh execution-observe` from an independently approved controller
installation. The definition must be operator-reviewed, outside the candidate
worktree, and supplied with its exact SHA-256. Passing a digest is not itself
approval. Candidate controller code runs only against isolated fixture state.

Provision a fresh credential-free network-off Docker guest first. The definition
binds the absolute Docker executable and hash, explicit local Unix endpoint,
full container ID, creation time, image ID, exact environment/mount inventory,
source commit IDs and file hashes, and up to twelve cases. Each case has an ID,
explicit guest argv, timeout, exact expected stdout and expected exit. Requests
cannot select arbitrary backend subcommands. Provisioning, network approval,
definition review and stopping/removing the exact guest remain operator duties.

Inspection requires numeric non-root user, dropped capabilities,
no-new-privileges, read-only root, bounded memory/CPU/PIDs, network none and only
declared read-only candidate bind mounts. Scratch tmpfs is limited to `/tmp` and
`/work`. The host CLI receives a minimal environment and empty private Docker
configuration, with explicit endpoint selection. This does not certify a trusted
Docker daemon or prohibit all same-user interference. Effective guest config is
inspected, not inferred solely from launch flags.

## Invocation and evidence

```bash
run.sh execution-observe TASK --operation-id attempt-1 \
  --expected-revision 5 --definition /approved/definition.json \
  --definition-sha256 FULL_SHA256
```

The task must already be admitted and own its worker slot. Task JSON records a
durable `DISPATCHING` intent before the backend exec can occur. The controller
then checks current identity under its short dispatch lock, spawns the Docker
CLI and records the **actual child PID** and observed start identity. An absent
fast-exiting child is reported as absent, never replaced with the controller PID.
Guest PID is not claimed. A crash between spawn and recording can lose the child
identity, but cannot authorize a duplicate launch: the intent remains unsettled.

Stdout/stderr are captured concurrently with a one-MB combined bound and a
maximum 60-second timeout per case. Nonzero Docker CLI exits, including signals,
are UNVERIFIED because guest failure and transport failure are not independently
distinguished. Only zero-exit contracts are admitted in this slice. Observed
output mismatches after exit zero fail the assertion. Empty or
success-like output cannot pass a nonempty exact-output oracle. Assertions are
defined on the controller; candidate-reported test counts confer no credit.
Correct expected output is a black-box result, not proof of internal correctness
or adequate tests. Bind meaningful positive and negative cases independently.

The controller retains content-addressed output and definition bytes before task
references. Completed capture reports each case, transport outcome, and source
applicability. It still says `candidate_ready: false`. A transport timeout or
host-client termination does not prove guest processes stopped.

## Reconciliation and replay

Stop the exact container externally, then repeat the original invocation with
`--reconcile-stopped`. The command verifies the original container ID and creation
time with `Running: false`. It does not itself send a kill or remove command.
Only that observed stop releases the execution fence. A missing container is
UNVERIFIED; stop/reconcile before removal. A captured result becomes SETTLED;
an interrupted launch becomes UNKNOWN_STOPPED, never invented success. Stop
observation and capture can arrive in either order without corrupting phase.
Missing streams yield EVIDENCE_LOST_STOPPED and unverified oracle evidence while
retaining independently observed termination. Missing original definition or
container identity cannot be repaired by guessing.

Exit status is consistently 3 while unsettled; after exact stop it is 0 for a
settled PASS, 1 for FAIL and 3 for UNVERIFIED. Reconciliation never converts an
oracle failure into exit-code success. Current source applicability checks the
actual checkout HEAD as well as task and source hashes at settlement.

Identical retry returns the original observation without dispatch. Changed
operation reuse is refused. Every new case checks current source/owner, and
settlement recalculates applicability. The coordinator refuses lifecycle changes
and capacity release while execution stop is unverified, including recovery from
a vanished worker. A fresh operation requires a fresh container; namespace reuse
is refused across recorded tasks. This is conservative at-most-once dispatch
per local intent, not exactly-once distributed execution.

Retained stream bytes and assertions are revalidated before historical replay.
Historical PASS is not a current-head assessment. Corruption or missing evidence
is UNVERIFIED. The current implementation leaves manual operator stop and
reconciliation as explicit steps; it does not automatically retry ambiguous
execution or add a second task lifecycle authority.
