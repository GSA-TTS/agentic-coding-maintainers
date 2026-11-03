# CI runtime RCA and measured test-only optimization

AI-assisted investigation, 2026-11-03. Baseline:
`426e3ec5733cfb2243fe80272511ebeba9037b78` (merged PR102).

## Why CI approached ten minutes again

Prior changes improved repeated compilation and diagnostic tracing in foreground
CLI child processes. They did not eliminate fixture setup, fresh module execution,
Git commands, or repeated retained-history validation. The suite and exercised
history grew between PR101 and PR102. A faster component did not guarantee the
whole job would remain below its limit.

Read-only GitHub step observations:

| Hosted run | Job elapsed | `make check` step | Result |
|---|---:|---:|---|
| [PR101 optimized run41642915251](https://github.com/GSA-TTS/agentic-coding-maintainers/actions/runs/41642915251) | 8m36s | 8m09s | Pass |
| [PR102 optimized run41674331499](https://github.com/GSA-TTS/agentic-coding-maintainers/actions/runs/41674331499) | 9m54s | 9m33s | Pass |
| [This optimization run41708829200](https://github.com/GSA-TTS/agentic-coding-maintainers/actions/runs/41708829200) | 7m48s | 7m08s | Pass |

The increase is in the test/check step, not package installation or secret
scanning. The job totals are not a controlled interpreter benchmark: code and
workload changed, and runner variation is unmeasured. The earlier Python3.12
versus3.11 observations also crossed images/builds/architectures and cannot
attribute a causal slowdown to an interpreter version.

The first hosted run of this change passed all checks with 2m12s of headroom,
versus six seconds for PR102: 2m06s less total elapsed time (21.2%). The test/check
step decreased 2m25s (25.3%). Four additional regressions ran. This is one observed
comparison, not a controlled multi-run estimate: main also advanced its pinned
setup-python action and runner load was not measured. The profiled unchanged
command counts and compilation drop independently support the targeted cause.

## Measured remaining bottleneck

The existing diagnostic launcher caches only compiled installed source within
each foreground CLI child, comparing freshly read bytes on every load. Heavy
receipt-limit and reconciliation tests additionally load installed modules in
the parent process. Parent compilation remained outside that optimization.

Separate profiles of the same cases before/after extending coverage:

| Case | Parent compile calls | Parent compile self time |
|---|---:|---:|
| Pending repair receipt limit | 3,685 → 16 | 16.529s → 0.055s |
| Last-slot reconciliation | 5,320 → 13 | 26.228s → 0.052s |

Public CLI/Git/process command counts were identical in each comparison. The
first case retained21 foreground,6 state,2 review-evidence,1 review-collect,
17 Git and1 process-identity command; the second retained20 foreground,10 state,
5 review-evidence,1 review-collect,29 Git and2 process-identity commands. Deep-copy
call counts were also unchanged. No linecache activity appeared in these measured
parent/foreground-child profiles; other CLI internals remain unprofiled.

## Narrow change

Each foreground test fixture now enters the existing bounded
`compiled_installed_sources()` context with unittest cleanup management. It
covers direct parent helper calls through fixture teardown, then restores the
loader. Each subsequent test starts with an empty cache. The normal child CLI
behavior is unchanged.

Only byte-identical compiled code is reused, bounded to32 path/optimization
entries and1MB per source. Imports still read actual source bytes and execute
fresh module globals. No task records, Git facts, file metadata, policy hashes,
validation outcomes, or module instances are cached. Same-length/same-mtime source
edits and deletion still invalidate/fail through the normal path.

The regression proves fresh module state and loader restoration after successful
test completion, test assertion failure, and setup failure. Existing cache-edit,
deletion, scope, optimization-option, bounds and cleanup tests remain. The exact
72 baseline test IDs and execution multiplicities are preserved; one regression
is added. No runtime code, assertions, timeout, CI permissions or test-mode
bypass changes are made.

## Timing method and results

Pinned Python3.12 Bookworm Docker image
`sha256:a5bab0ff300f91231c2e68bf73a8a8d60762ac39ce1c50eaf6803e4c38a9062b`
reported Python3.12.16. Network-off, non-root, two CPUs/2GiB, read-only source,
isolated writable fixture copies. Timing and profiling were separate. Three
samples per case alternated cases within each before/after batch; batches were
sequential, not randomized pairs. Continuous host contention was not measured.

| Case | Before samples (s) | After samples (s) | Median change |
|---|---|---|---:|
| Pending receipt limit | 24.940,29.115,25.298 | 9.664,10.744,9.409 | −61.8% |
| Last-slot reconciliation | 37.126,38.780,35.835 | 11.946,13.359,12.758 | −65.6% |
| Historical replay control | 10.790,9.936,9.675 | 10.283,10.921,9.974 | +3.5%; no gain established |

Single-sample full foreground runs: baseline72 tests in596.252s, optimized73
tests in466.512s (~130s less). Baseline was verbose and optimized used normal
reporting, so this is supporting evidence, not a controlled hosted prediction.
The initial full `make check` attempt stopped at missing rsync after the foreground
and prior suites passed; it is not a whole-suite pass. A subsequent complete
run with required test tools completed the full repository suite, with 73
foreground tests passing in465.743s and every remaining suite/check passing.
That diagnostic run allowed a longer local wrapper to finish all validation;
the repository's hosted ten-minute job timeout is unchanged. After independent
review identified zero-test timing as a benchmark defect, exact single-case
selection and three lightweight regressions were added. The final full isolated
suite passed with 76 foreground tests in481.002s and all remaining checks passing.
The hosted result above supplies separate evidence of improved CI headroom.

To reproduce on an approved isolated copy, use
`tests/foreground-diagnostic-benchmark.py --case METHOD` for three fresh-process
samples, or `--profile --case METHOD` for parent and foreground-child profiles.
The benchmark preserves failures and emits command counts. State/Git validators
are not replaced. Production checkout code must not be run on the host.

## Remaining costs and rejected shortcuts

- Repeated public CLI startup and full history reconstruction still cost time.
  Removing validators or caching evidence would require a separate security
  design; it is not this optimization.
- Full preparation remains independent per test; no mutable authoritative
  fixture is shared between tests.
- Static inspection identified26 inherited test executions also run separately
  by the Makefile. They are retained here. Deduplication would need an explicit
  assertion/fixture-equivalence analysis, not a test-count reduction disguised
  as speedup.
- Real timeout/lock-contention tests contribute intentional wait time and remain.
- The ten-minute hosted bound is unchanged. One green run is a measurement, not
  proof of future margin. Review future workload growth using timings rather
  than only test counts, and retain full failure-path coverage.

Private profile and inventory evidence is retained in the consumer review
workspace under the dated CI-runtime review. No host inventories, source secrets,
or raw state are included in this public report.
