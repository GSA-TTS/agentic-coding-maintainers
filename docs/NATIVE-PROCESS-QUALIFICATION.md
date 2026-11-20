# Native process primitive qualification (first slice)

## Observer candidate and bounded lifecycle integration

The sibling `native-process-observation.py` now implements a candidate backend;
`runtime-observation.py` adds `native_process_identity(pid)` and the record-directed
`observe_worker_process(worker, *, environment=None)`. The bounded native
lifecycle/manual integration now selects these entry points for explicit native
task inputs, including fresh identity observation before native claim and
implementation-lane acquisition. See [bounded dual-format integration](NATIVE-OWNERSHIP.md#bounded-dual-format-integration-issue-182)
for the supported formats, caller defaults, consumer fences and recovery limits.

Native creation remains default off: `create` still emits schema 2, and no
supported converter or new native-creation CLI exists. This integration does not
qualify or activate a deployed native backend. The primitive experiment below
retains its original meaning. **Neither its result nor ordinary unit tests
establish full backend qualification.**

The candidate admits two complete kernel/interpreter/loaded-libc tuples, both
Linux / aarch64 / little-endian LP64 / CPython:

| Guest | Kernel | CPython | Loaded glibc |
|---|---|---|---|
| Bookworm | 6.12.113 | 3.12.16 | 2.36 |
| Noble | 6.8.0-147-generic | 3.12.3 | 2.39 |

Cross-combinations refuse. ABI declarations and flags use the independent
installed-header measurements from PR #187, based at
`d051a72c8295334b11bca85f5488c51995c45dc4`, and the 2026-11-18 Noble primitive
run. Both measured the same 120-byte/alignment-8 `statfs`, all field offsets,
24-byte `open_how`, resolver constants, actual fstatfs and syscall/errno behavior.
The Noble run reported `SELF_TEST_PASSED` and `PRIMITIVES_VERIFIED`, each with
`backend_qualified: false`. Its primitive Python source SHA-256 was
`25f54387b16a2974f465fe095e174102c4b6d3f469666f914085055b0b61ab1d`; independent
C witness source was `eb10c61c9650b5cb8a603684e9c3fdd30b3831d8928e5355b0597d2315d65145`.
These are primitive measurements, not full-backend results. Runtime never
compiles a witness or falls back to weaker opens. Other profiles return `unknown`.

### Fixed wire and source contract

The parent executes an immutable snapshot of its checksum-verified installed
sibling through its absolute interpreter with `-I -B -c`, a fixed trusted
bootstrap and a fixed PATH/locale environment. The bootstrap decodes the verified
source bytes from a base64 data argument, preserves the sibling path as `__file__`
and its compile filename, and presents one ASCII JSON request in `sys.argv[1]`.
It never reopens the helper pathname. The trusted installation includes
`CANONICAL-SHA256SUMS`; this detects
mixed or substituted helper bytes, not a hostile owner rewriting the installation.
Both inventory and helper are opened once with
`O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC`, checked as regular files before reads, and read
with 64 KiB byte caps and finite call budgets. FIFO substitution therefore refuses
before any read; regular-file I/O can still encounter uninterruptible kernel waits.
Controller manifests also bind the new helper. Retained exact seven- and
eight-module manifests remain readable but cannot equal the current nine-module
installation; new execution uses the existing new-generation/new-plan route.

Request (4096-byte maximum), exact fields:

```text
version: 1
pid: positive signed-32-bit integer
caller_tgid: positive signed-32-bit integer
caller_tid: positive signed-32-bit integer
expected_context: null | {boot_id, pid_namespace_inode}
```

Response (4096-byte maximum including any stderr), exact fields:

```text
version: 1
pid, caller_tgid, caller_tid: exact request bindings
status: alive | absent | unknown
context: null | {boot_id, pid_namespace_inode}
identity: null | exact ADR 0002 five-field identity
```

`alive` requires qualified context equal to the identity's boot/namespace;
`absent` requires qualified context and null identity; `unknown` requires both
null. Both ends enforce any expected recorded context. Duplicate keys, extra
fields, coercions, boolean integer substitutions, malformed/trailing JSON data,
nonzero exits and nonempty stderr refuse. Native failures never run `ps`.

The helper holds fixed `/proc` and target/source descriptors, uses
`openat2(BENEATH|NO_SYMLINKS|NO_XDEV)`, and reads kernel links through
`O_PATH|O_NOFOLLOW` plus empty-path `readlinkat`. Byte and read-call limits apply
to every proc read. It checks actual helper and caller thread stat/status,
single-entry `NSpid`, `Pid`/`Tgid`, parent TGID, PID namespaces and current/child
time namespaces twice, with exactly zero monotonic/boottime offsets. Target
`Tgid` must equal requested PID. Two complete samples and a final fresh `/proc`
resolution compare mount ID/device/inode/type for root, target and sources while
descriptors remain held. Caller/helper lifetime ticks are also compared.

Offsets are read from the helper's process-level `timens_offsets` **after**
proving helper current/child time namespaces equal the actual caller thread's
current/child time namespaces. Linux v6.12 [`fs/proc/base.c`](https://github.com/torvalds/linux/blob/v6.12/fs/proc/base.c)
includes this file in `tgid_base_stuff`, not `tid_base_stuff`;
[`proc_timens_show_offsets`](https://github.com/torvalds/linux/blob/v6.12/kernel/time/namespace.c)
reads the selected task's `time_for_children` namespace. Thus the helper's offsets
qualify the proven shared namespace without assuming the caller's leader has
the same thread-local context. Both equality and zero offsets are checked in
each complete sample. The actual-guest regression includes leader and nonleader
callers observing both a child and their own process PID.

Whole-root policy accepts genuine procfs with filesystem root `/` and mountpoint
`/proc`, including an equivalent whole-root bind. Inner bind crossings refuse.
This cannot authenticate a privileged mount administrator or rule out every
transient replacement between observations. Zero-offset noninitial time
namespaces can satisfy the profile; arbitrary nonzero time offsets cannot.

Only initial target-directory `ENOENT`, then `kill(pid, 0)` returning `ESRCH`,
then repeated fresh-root missing lookup/`ESRCH` and stable context can return
absence. An opened target that disappears returns unknown. Zombies cannot be
absent before reaping; unavailable zombie namespace evidence may yield unknown.

Collection has a three-second deadline and a separate one-second kill/reap
cleanup deadline. Spawn and uninterruptible kernel operations have no universal
wall-clock guarantee. Cleanup failure yields unknown; the caller retains cleanup
responsibility for the unreaped direct helper (ordinary Popen bookkeeping retains
it), rather than treating the deadline as proof of termination.

### Required candidate checks in the isolated guest

After regenerating the canonical checksum inventory for the reviewed candidate:

```sh
python3 -I -B .agents/skills/workspace-orchestrator/tests/native-process-observation-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/native-process-observation-test.py --qualify
python3 -I -B .agents/skills/workspace-orchestrator/tests/runtime-observation-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/execution-plan-test.py
make check
pre-commit run --all-files
```

Ordinary native fixtures cover strict parsing/wire refusal, mocked source/context
races and absence sequencing, actual bounded subprocess flooding/stall/exit
cleanup, and copied-helper integrity. Additional security regressions replace
the helper pathname after verification and before launch, requiring the original
verified snapshot to execute while the replacement payload does not. Separate
watchdog subprocesses substitute FIFOs for both inventory and helper and require
unknown without payload execution. Cleanup cases include SIGSTOP, both closed
output pipes with a live child, stderr flooding, partial replies, launch failure,
final-wait deadline expiry, and mocked cleanup timeout. The latter explicitly
leaves reaping unresolved and verifies unknown rather than claiming termination.
`--qualify` requires the exact profile and
tests actual repeated live identity, adversarial comm bytes, copied installation,
zombie/reaped lifecycle and recorded boot mismatch. Unsupported profile returns
`UNQUALIFIED`, exit 3; successful lifecycle assertions report
`LIFECYCLE_VERIFIED`, with `backend_qualified: false`. This is a bounded case result.
Namespace/mount capabilities and adversarial actual-guest cases remain separate
unqualified gates, never implicit passing skips. Record command exits and exact
candidate revision with the guest results before changing any qualification claim.

### Opt-in privileged namespace matrix

The repository-owned `native-process-namespace-qualification.py` fixture is
integrated from the corrected, separately reviewed namespace qualification task.
It is deliberately outside default test execution. In the approved disposable,
credential-free guest, with guest-local storage and independently qualified
external watchdog/descendant teardown, invoke:

```sh
python3 -I -B .agents/skills/workspace-orchestrator/tests/native-process-namespace-qualification.py --qualify-disposable-guest
```

Guest-local root is setup authority only: candidate imports happen after dropping
to UID/GID 1000, clearing groups and capabilities, setting NoNewPrivs, closing
privileged descriptors and limiting resources. Cases cover fresh/ancestor PID
views, nonleader caller, recorded reaped absence, same-proc bind overlays of stat,
boot, namespace directory and target directory, PID-child divergence, zero and
positive/negative/fractional time offsets, current/child time divergence, and
seccomp EPERM/ENOSYS. Negative cases require an alive baseline and independent
injection witness; ancestor targets use retained pidfd-derived numeric mappings.

The external watchdog must cover the complete 480-second invocation and confirm
descendant teardown on every exit/timeout; internal deadlines are cooperative.
Missing facilities yield `UNQUALIFIED`, expectation/cleanup failures `FAILED`.
The root cases now use a test-only bootstrap over the immutable helper bytes
returned by the production checksum gate. It wraps only `Proc.__init__` to pause
before the second or third construction, leaving profile, observations, errors
and wire serialization intact. Evidence is labeled **instrumented exact-source
helper qualification**, distinct from the unmodified public-launch baseline and
stable whole-root-bind controls. There is no production fault switch or inventory
bypass. An abstract socket in the private network namespace carries only bounded
readiness/resume packets, with SO_PEERCRED, helper parent/PID view, capabilities,
NoNewPrivs and namespace witnesses checked by the privileged coordinator. No
privileged descriptor reaches candidate execution.

The coordinator self-binds `/proc` only at the requested barrier, independently
proving genuine procfs, equal device/inode, changed fresh mount ID, unchanged
held-root association, root `/` at `/proc`, and successful fresh constrained
target traversal before release. No-change controls at both placements require
alive; replacements before sample two or the final fresh-root check require
unknown. Fresh uninstrumented observations require the baseline identity while
the stable whole-root bind is present and after its witnessed removal.

For the fixed three-case subset under the same guest/watchdog requirements:

```sh
python3 -I -B .agents/skills/workspace-orchestrator/tests/native-process-namespace-qualification.py --qualify-root-replacement
```

Exit 0 means every selected case actually reported `VERIFIED`; exit 3 means a
case remains `UNQUALIFIED`, and exit 1 means a failure. Reports always retain
`backend_qualified: false`. Implementation alone supplies no actual-guest
root-replacement evidence; retain UNQUALIFIED until those runs are observed.

This opt-in experiment supports [ADR 0002](decisions/0002-native-process-identity.md).
It is not a backend implementation, deployment approval, or native task claim gate.
`PRIMITIVES_VERIFIED` means only the checks below passed in the reported guest.
`backend_qualified` is always false. Default repository checks do not run this
experiment and cannot establish native qualification.

## Prerequisites and exact commands

Use the operator-approved, credential-free, independently isolated Linux guest.
A worktree alone is not isolation. Review both fixture files before executing.
The original primitive ABI profile is **Linux / aarch64 / little-endian / LP64 /
loaded glibc 2.36**; the intended validation tuple is **Linux 6.12.113 / CPython
3.12.16 / aarch64 / glibc 2.36**. The primitive harness additionally admits only
the exact Noble **6.8.0-147-generic / CPython 3.12.3 / glibc 2.39** tuple above.
Its original glibc-2.36 experiment still reports arbitrary kernel/Python versions;
the production helper is stricter and admits only the two complete tuples.
Primitive results are not generalized into qualified backend support. Other ABI profiles refuse
before compilation. Require trusted guest `/usr/bin/cc` (C11 plus GNU
`__alignof__`), installed Linux/glibc development headers, `/usr/bin/ps`, Python,
and genuine fixed `/proc` with accessible `NSpid`, namespace links and
`timens_offsets`. This slice requires no namespace creation privileges.

From the reviewed checkout inside that guest:

```sh
python3 -I -B tests/native-process-qualification.py --self-test
python3 -I -B tests/native-process-qualification.py --qualify
```

There is no default mode. `--qualify` is the explicit compilation authorization
for the reviewed sibling `tests/native-process-abi.c`: `/usr/bin/cc -std=c11
-Wall -Wextra -Werror -O2 <fixed-sibling-source> -o <private-temporary-witness>`.
The temporary directory is removed afterward. There are no caller-selected code,
compiler, executable or proc-root options and no environment fault hooks. The
fixture does not import or invoke the production observer or state machinery.

Commands use no shell, a minimal PATH/locale environment, a combined 16 KiB
output cap enforced during collection, and a three-second deadline (30 seconds
for compilation). Proc reads have both byte and call limits; links have a
128-byte buffer. Timeout/error cleanup kills and waits for the direct child.
Process creation and uninterruptible kernel waits do not have universal bounded
cleanup guarantees; the harness itself is not the proposed bounded production
helper. No production timeout qualification is claimed.

Exit 0 with `SELF_TEST_PASSED` covers only report-shape/ABI-offset and syscall-error
refusals, plus otherwise-valid top-level and nested duplicate keys requiring the
exact duplicate-key refusal. A successful fixed subprocess must return exact bytes;
exit 7, output-cap and timeout cases must each produce their specific refusal.
It performs no C compilation or proc qualification.
Exit 0 with `PRIMITIVES_VERIFIED` covers the actual guest checks. Unsupported
platform/libc or `ENOSYS` yields `UNQUALIFIED`, exit 3. Missing capabilities, compiler or
primitive errors and mismatches yield `FAILED`, exit 1; these never pass or
fall back to weaker opens. Invalid CLI use follows argparse's exit 2.
Only the dedicated unsupported-profile exception produces `UNQUALIFIED`;
missing `gnu_get_libc_version` is classified at that symbol lookup. Unexpected
attribute errors elsewhere produce `FAILED`.

## Evidence produced

The C witness independently measures installed-header `statfs` and `open_how`
sizes/alignment and **every field's offset, size and alignment**. It reports
syscall number and resolver/open flags, all actual `/proc` `fstatfs` values,
`fstatfs(-1)` return/errno and a real constrained `openat2` result. Python
compares these measurements to its own ctypes declarations before invoking its
FFI operations, then compares actual filesystem results and `EBADF` behavior.

Ordinary files use `RESOLVE_NO_XDEV | RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS`.
Kernel links use the same resolver with `O_PATH | O_NOFOLLOW` and empty-path
`readlinkat`; their own symlink inode is never confused with a namespace inode.
The experiment checks canonical boot UUID, `self == getpid`, stat PID/start
ticks, exactly one matching `NSpid`, namespace-link syntax, matching current
and child time namespaces, and zero monotonic/boottime offsets. Fixed legacy
`ps -p <self> -o lstart=` and `kill(self, 0)` provide live primitive observations;
they do not qualify legacy compatibility or absence handling. Output omits
observed boot UUID, PID, namespace numbers and legacy start text.

Record source commit, compiler/header package versions, exact commands, exit
codes and JSON output in separately reviewed run evidence. The report contains
the actual kernel/interpreter/libc tuple and C witness measurements. Source
presence alone and synthetic self-tests are not actual-guest evidence.

## Remaining qualification gates

The primitive fixture itself does not test the candidate two-sample backend,
caller-thread association, mount-ID rechecks or absence protocol described above.
Actual adversarial qualification still requires new/ancestor PID namespace cases including numeric coincidence;
positive/negative/fractional time offsets and parent child-namespace transitions;
same-procfs bind overlays, whole-root mount policy, foreign-filesystem overlays
and deterministic replacement races; target exit/reuse, adversarial comm bytes,
exec stability, zombie/reap and hidden/permission-refused targets; seccomp and
unavailable syscall cases; bounded helper flooding/stalls/reaping and copied
installation integrity; independent backend/legacy integration review. The
resolver flags being accepted does not prove these adversarial cases passed.
x86_64, other libc/ABIs and all production native claims remain unqualified.

## Provenance and primary sources

New repository-owned fixtures, informed by the 2026-11-17 backend research and
merged ADR 0002 at task baseline `15718c2`; no external implementation copied.
The independent witness uses the guest's installed headers, not downloaded
headers or a Python-generated C declaration. These sources justify a candidate
ABI/semantics, not successful qualification:

- [glibc 2.36 statfs layout](https://github.com/bminor/glibc/blob/glibc-2.36/sysdeps/unix/sysv/linux/bits/statfs.h)
- [aarch64 sysdeps selection](https://github.com/bminor/glibc/blob/glibc-2.36/sysdeps/unix/sysv/linux/aarch64/Implies)
- [generic glibc type sizes](https://github.com/bminor/glibc/blob/glibc-2.36/sysdeps/unix/sysv/linux/generic/bits/typesizes.h)
- [Linux v6.12 open_how](https://github.com/torvalds/linux/blob/v6.12/include/uapi/linux/openat2.h)
- [generic syscall table](https://github.com/torvalds/linux/blob/v6.12/include/uapi/asm-generic/unistd.h)
- [aarch64 open flag overrides](https://github.com/torvalds/linux/blob/v6.12/arch/arm64/include/uapi/asm/fcntl.h)
- [openat2 resolution semantics](https://man7.org/linux/man-pages/man2/openat2.2.html)
- [empty-path readlinkat](https://man7.org/linux/man-pages/man2/readlink.2.html)
- [proc stat and NSpid implementation](https://github.com/torvalds/linux/blob/v6.12/fs/proc/array.c)
- [reader time-namespace conversion](https://github.com/torvalds/linux/blob/v6.12/include/linux/time_namespace.h)
- [time_for_children offsets source](https://github.com/torvalds/linux/blob/v6.12/kernel/time/namespace.c)
