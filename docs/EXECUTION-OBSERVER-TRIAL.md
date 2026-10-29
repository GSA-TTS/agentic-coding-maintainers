# Controller execution observer trial — 2026-10-29

AI-assisted continuation after PR78, with parallel independent architecture and
security analysis followed by parallel fixed-revision QA/security review.

## Implemented

A foreground controller invokes only a defined Docker inspection/exec route
against an operator-provisioned exact container ID. Definition, source and
runtime identity are bound; the controller persists dispatch intent before
execution, captures bounded output directly, records actual CLI child identity
and evaluates independent exact-output assertions. It never accepts a candidate
test-count or success marker as an oracle.

Unsettled guest execution fences coordinator lifecycle changes and capacity
release. Stop is an independently observed exact-container fact, not inferred
from client exit or elapsed time. Nonzero/negative Docker exits are unverified
because this adapter cannot independently distinguish guest exit from daemon or
transport error. Operator-reviewed definitions currently support zero-exit
contracts only.

## Real runtime trial

The operator authorized the candidate controller to run inside the existing
Ubuntu Multipass VM, against fresh Docker guests. No candidate controller ran
on the host. Alpine was already cached by digest; no image pull was needed.
Each guest used network none, a numeric non-root user, read-only root/source,
dropped capabilities, no-new-privileges, 512 MiB, one CPU and 64 PIDs. No host
credentials/controller state were mounted into candidate containers.

The approved oracle expected `6\n`. Four guest modes returned the correct bytes,
wrong bytes, the misleading string `PASS\n`, or slept past timeout. The initial
trial exposed inconsistent exit mapping on reconciliation; that result was not
treated as final qualification. After repairs, the repeated trial observed:

| Mode | Initial exit | Launches after retry | Live-guest lifecycle transition | Stop reconciliation exit |
|---|---:|---:|---|---:|
| correct output | 3 (unsettled) | 1 | refused | 0 (PASS) |
| wrong output | 3 | 1 | refused | 1 (FAIL) |
| fake PASS marker | 3 | 1 | refused | 1 (FAIL) |
| timeout | 3 | 1 | refused | 3 (UNVERIFIED) |

Each exact container was stopped, reconciled, then removed. The pilot proves
this Docker path inside the VM; it does not qualify MSB execution transport.
Previously measured MSB reviewer functionality remains separate. The controller
was tested against isolated task state and was not promoted into the host's
installed controller.

## Review-driven corrections

Parallel reviewers found stop/capture races, inconsistent replay exits, missing
artifact stop recovery, source-currentness gaps, transport-error attribution,
weak launcher/stop validation, slotless Rework admission and non-isolated IPC.
The owner repaired them and added regression cases. Re-review at
`0bd25a6b8e7b08b0a174134db30a21564949cffd` found repeated evidence-loss
reconciliation could restore success, and dependency-specific errors could
prevent stop retention. The final fix makes evidence loss sticky and handles
bounded-reader errors as lost evidence/inapplicability. These final edge repairs
were tested separately after the live four-case repeat.

## Validation and qualifications

The targeted suite passes 11 tests, covering oracle PASS/FAIL/UNVERIFIED,
inspection refusal, real child PID, timeout, lifecycle fence, retained-artifact
tampering/loss, repeated degraded reconciliation, oversized streams, stop before
capture finalization, slotless rework, public-command interruption/retry with no
redispatch, and checkout HEAD drift. Some tests combine several assertions.
Full repository checks passed before the review-driven repairs; final full
checks are required again before publication. Static Ruff/Pyright pass and
Bandit reports no substantive findings; its guest tmpfs allowlist is annotated
as non-host-path use.

No candidate-readiness, model-review authenticity, automatic patch transport,
GitHub effect, daemon, policy or merge authority is activated. Operator approval
of the external definition and trusted installed controller/runtime remain
prerequisites. Docker client identity is not guest PID attestation. A missing
original container identity cannot be reconciled by guessing. Stopping and
removing containers remain explicit operator/runtime operations in this slice.
