# Native process primitive qualification (first slice)

This opt-in experiment supports [ADR 0002](decisions/0002-native-process-identity.md).
It is not a backend implementation, deployment approval, or native task claim gate.
`PRIMITIVES_VERIFIED` means only the checks below passed in the reported guest.
`backend_qualified` is always false. Default repository checks do not run this
experiment and cannot establish native qualification.

## Prerequisites and exact commands

Use the operator-approved, credential-free, independently isolated Linux guest.
A worktree alone is not isolation. Review both fixture files before executing.
The initial ABI profile is **Linux / aarch64 / little-endian / LP64 / loaded
glibc 2.36**; the intended validation tuple is **Linux 6.12.113 / CPython
3.12.16 / aarch64 / glibc 2.36**. Kernel and Python versions are reported, not
silently generalized into qualified backend support. Other ABI profiles refuse
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

Exit 0 with `SELF_TEST_PASSED` covers only report-shape/duplicate-key/ABI-offset
and syscall-error refusals, plus actual fixed subprocess nonzero-exit, output-cap
and timeout propagation. It performs no C compilation or proc qualification.
Exit 0 with `PRIMITIVES_VERIFIED` covers the actual guest checks. Unsupported
platform/libc or `ENOSYS` yields `UNQUALIFIED`, exit 3. Missing capabilities, compiler or
primitive errors and mismatches yield `FAILED`, exit 1; these never pass or
fall back to weaker opens. Invalid CLI use follows argparse's exit 2.

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

No complete two-sample backend, caller-thread namespace association, descriptor
mount-ID recheck, target lifecycle or absence protocol is implemented here.
Still required: new/ancestor PID namespace cases including numeric coincidence;
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
