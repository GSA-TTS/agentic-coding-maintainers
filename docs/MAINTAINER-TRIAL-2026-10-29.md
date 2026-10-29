# Resumed maintainer review/repair trial

AI-assisted; supersedes the runtime-blocked checkpoint for the specific pilot
described here. The broader implementation plan remains incomplete.

## Runtime qualification

The operator authorized resuming after the review checkpoint and a narrow MSB
managed-network retry. Canonical provider facts confirmed the USAi URL. Host DNS
resolved it; enabling MSB's documented, explicitly authorized DNS-rebind override
allowed the named HTTPS route. No proxy probe or alternate provider was used.
OpenCode configuration and copied-file permissions also required correction so
the non-root guest could read them. Failed attempts remain failed observations.

Runtime tuple: OpenCode 2.0.32, MSB 0.7.11, Linux ARM64 Node image
`sha256:8a34c4ab3ea2c5cd194f07e317b2a8f09461d3c8b05c4e34c8ccd56d56024c4d`.
Binary SHA-256:
`4199ae2d2c96ad2a140d32cabe6a1d9280b4cd1d9d8ed533a5431f54c422693c`.
The binary came from the existing Ubuntu VM and matched before/after transfer.
The actual inference ran on host MSB, not nested inside Multipass. Docker
separately ran repository validation.

The guest used UID 1000, restricted security, 2 CPUs, 2 GiB RAM, nproc=128,
read-only candidate mount, no published ports and only DNS plus the USAi HTTPS
hostname. The API key used MSB's protected secret binding. No GitHub credential
or controller state was mounted. The reviewer permitted source reads and denied
execution/edit/delegation. This is a measured direct-MSB pilot; it is not yet an
installed acq maintainer service.

## Real review → owner repair → re-review

Session `ses_e7b0095bcffezhOSKTSh9aMrIf` read the actual protocol, tests and
supporting source. Its exported outcome was succeeded. It identified:

1. Empty generations skipped the begin-receipt chronology constraint.
2. Generation-scoped run IDs were compared as bare IDs for finding dispositions.

The owner wrote regressions before changing the implementation. Isolated MSB
execution observed:

```text
Ran 16 tests
FAILED (failures=1, errors=1)
AssertionError: 'CLAIMS_COMPLETE' != 'UNVERIFIED'
review_evidence.Unverified: finding disposition requires a separate run
```

The implementation now orders every generation's begin receipt and compares
finding origin as `(generation, run_id)`. The same suite then observed:

```text
Ran 16 tests ... OK
```

Fresh session `ses_e7afd3154ffeA60bJCJLxC78Kw` read repaired source and tests
copied from fixed sandbox snapshot
`6afc83aa66673feaadcf0be6a9a03669baacddfc`. It statically verified both fixes and
reported no remaining defects in that scope. Earlier re-review attempts could
not read copied files and explicitly returned unverified; they confer no credit.
The reviewer did not execute the tests or independently verify the Git identity;
the controller supplied those bindings and observed execution.

## Executable adapter

Added canonical `review-run.py`, exposed through `run.sh review-run`, with
bounded binary/source reads, process/output/time limits, before/after source
hashes, source-read events and same-session export corroboration. The first
adapter attempt correctly refused success when the stream omitted final
`step_finish`, despite exit zero and review text. Session export provides a
separate runtime completion record with matching final assistant text.

Successful adapter session `ses_e7af8752affedcC7r1LBfy12mh` observed both requested
source reads and a no-actionable-findings review. Receipt measurements:

```text
status: REVIEW_OBSERVED
completion_source: same-session export and matching final text
input tokens: 12135
output tokens: 1490
elapsed seconds: 37.674479722976685
```

These are one-run token/timing observations, not cost savings or quality-rate
estimates. The provider's zero cost field is not billing evidence. The adapter's
subsequent export-failure and binary-bound hardening was independently reviewed
and tested; that final revision has not repeated the live inference trial.

## Independent validation

Fixed snapshot `71402b35300e51758b7b70f95ad224d026417c08` received independent
static review; a nested-checkout packet-store escape was found and fixed using
the actual Git checkout root, with a regression. Fixed adapter snapshot
`5e310a96d28a9fab6b1efbce19866ee3016e200d` received independent review that found
an export-failure fallback and unbounded binary read. Both were fixed and
re-reviewed at `ffccdd8b85c75a573f9354beb622a86dc7e5b8c6`, with no material
remaining findings in that scope.

Latest isolated Docker `make check` observed:

```text
review-packet-test.py: Ran 10 tests ... OK
review-evidence-test.py: Ran 16 tests ... OK
review-run-test.py: Ran 9 tests ... OK
import-sync tests: PASS
OpenCode runtime probes: SKIP (set OPENCODE_V1 and OPENCODE_V2)
operating surface: PASS (4 measured checks, 6 profiles)
python syntax: PASS (32 files)
json syntax: PASS (12 files)
shellcheck: PASS
repository checks: PASS
```

All other existing suites passed. Ruff, Pyright and Bandit passed across the
canonical orchestrator Python tools. The Docker environment used Python 3.11
and Debian ShellCheck 0.9.0, not the full pinned hosted-CI tuple. The generic
compatibility probes remained skipped; the separate real v2 trial is explicitly
reported above rather than silently converting that skip to pass.

## Remaining gates

No immutable controller promotion of runtime receipts, automatic owner patch
transport, service supervisor, durable PR monitor, GitHub effect executor,
approval/merge lane or polyrepo delivery was activated. Claim assessment still
grants neither candidate readiness nor execution/delivery credit. Native
CODEOWNER enforcement remains required. This increment is a working review
foundation and guest adapter, not completion of E00/R or M proposals.
