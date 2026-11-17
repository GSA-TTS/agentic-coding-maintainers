#!/usr/bin/env python3
"""Opt-in guest primitive experiment, never a production qualification gate."""

import argparse
import copy
import ctypes as c
import errno
import json
import os
from pathlib import Path
import platform
import re
import selectors
import stat
import subprocess
import sys
import tempfile
import time


class Refusal(Exception):
    pass


class UnsupportedProfile(Refusal):
    pass


def require(condition, message):
    if not condition:
        raise Refusal(message)


class StatFS(c.Structure):
    _fields_ = [(name, kind) for name, kind in (
        ("f_type", c.c_long), ("f_bsize", c.c_long), ("f_blocks", c.c_ulong),
        ("f_bfree", c.c_ulong), ("f_bavail", c.c_ulong), ("f_files", c.c_ulong),
        ("f_ffree", c.c_ulong), ("f_fsid", c.c_int * 2), ("f_namelen", c.c_long),
        ("f_frsize", c.c_long), ("f_flags", c.c_long), ("f_spare", c.c_long * 4))]


class OpenHow(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ("flags", "mode", "resolve")]


def layout(kind):
    return {"size": c.sizeof(kind), "alignment": c.alignment(kind), "fields": {
        name: [getattr(kind, name).offset, c.sizeof(field), c.alignment(field)]
        for name, field in kind._fields_}}


def expected_abi():
    return {"statfs": layout(StatFS), "open_how": layout(OpenHow), "constants": {
        "long": 8, "pointer": 8, "int": 4, "syscall": 437, "beneath": 8,
        "no_symlinks": 4, "no_xdev": 1, "o_path": 0o10000000,
        "o_nofollow": 0o100000, "o_cloexec": 0o2000000,
        "o_directory": 0o40000, "proc_magic": 0x9FA0}}


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def validate_report(raw):
    report = json.loads(raw, object_pairs_hook=pairs)
    expected = expected_abi()
    require(type(report) is dict and set(report) == set(expected) | {
        "values", "bad_fstatfs", "openat2"}, "witness envelope mismatch")
    for key, value in expected.items():
        # Canonical JSON comparison also refuses bool-for-int substitutions.
        require(json.dumps(report[key], sort_keys=True) == json.dumps(value, sort_keys=True),
                f"C/Python ABI mismatch: {key}")
    require(type(report["values"]) is dict and set(report["values"]) == {
        name for name, _ in StatFS._fields_}, "fstatfs result shape mismatch")
    for name, value in report["values"].items():
        count = {"f_fsid": 2, "f_spare": 4}.get(name)
        require((type(value) is list and len(value) == count
                 and all(type(item) is int for item in value)) if count
                else type(value) is int, "fstatfs result type mismatch")
    for key in ("bad_fstatfs", "openat2"):
        require(type(report[key]) is list and len(report[key]) == 2
                and all(type(item) is int for item in report[key]), "errno shape mismatch")
    require(report["bad_fstatfs"] == [-1, errno.EBADF], "C errno mismatch")
    if report["openat2"] == [-1, errno.ENOSYS]:
        raise UnsupportedProfile("openat2 unavailable")
    require(report["openat2"] == [0, 0], "C openat2 refused")
    return report


def run(command, timeout=3):
    """Fixed internal commands only; cap output during collection, not afterward."""
    with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}) as child:
        try:
            output = bytearray()
            deadline = time.monotonic() + timeout
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    require(remaining > 0, "external command timeout")
                    for key, _ in selector.select(remaining):
                        chunk = os.read(key.fd, 4096)
                        require(len(output) + len(chunk) <= 16384, "external output limit")
                        if not chunk:
                            selector.unregister(key.fd)
                        output.extend(chunk)
            returncode = child.wait(timeout=max(0.001, deadline - time.monotonic()))
            require(returncode == 0, f"external command failed: exit={returncode}")
            return bytes(output)
        except subprocess.TimeoutExpired as error:
            raise Refusal("external command timeout") from error
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()


def profile():
    observed = {"system": platform.system(), "machine": platform.machine(),
                "kernel": platform.release(), "python": platform.python_version(),
                "byteorder": sys.byteorder, "libc": "unmeasured"}
    if not (observed["system"] == "Linux" and observed["machine"] == "aarch64"
            and sys.byteorder == "little" and c.sizeof(c.c_void_p) == 8
            and c.sizeof(c.c_long) == 8 and c.sizeof(c.c_int) == 4):
        raise UnsupportedProfile("requires Linux aarch64 little-endian LP64")
    libc = c.CDLL(None, use_errno=True)
    try:
        version = libc.gnu_get_libc_version
    except AttributeError as error:
        raise UnsupportedProfile("loaded libc lacks gnu_get_libc_version") from error
    version.argtypes, version.restype = [], c.c_char_p
    observed["libc"] = version().decode("ascii")
    if observed["libc"] != "2.36":
        raise UnsupportedProfile("requires loaded glibc 2.36")
    return observed, libc


def primitives(libc, witness):
    libc.fstatfs.argtypes, libc.fstatfs.restype = [c.c_int, c.POINTER(StatFS)], c.c_int
    libc.syscall.restype = c.c_long
    libc.syscall.argtypes = [c.c_long, c.c_int, c.c_char_p, c.POINTER(OpenHow), c.c_size_t]
    libc.readlinkat.argtypes = [c.c_int, c.c_char_p, c.c_void_p, c.c_size_t]
    libc.readlinkat.restype = c.c_ssize_t
    root = os.open("/proc", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)

    def filesystem(fd):
        value = StatFS()
        c.set_errno(0)
        require(libc.fstatfs(fd, c.byref(value)) == 0, "Python fstatfs failed")
        return {name: list(getattr(value, name)) if name in ("f_fsid", "f_spare")
                else getattr(value, name) for name, _ in StatFS._fields_}

    def opened(path, flags):
        how = OpenHow(flags | os.O_CLOEXEC | os.O_NOFOLLOW, 0, 8 | 4 | 1)
        c.set_errno(0)
        fd = libc.syscall(437, root, path.encode("ascii"), c.byref(how), c.sizeof(how))
        require(fd >= 0, f"Python openat2 refused: errno={c.get_errno()}")
        return fd

    def read(path, limit=65536, link=False):
        fd = opened(path, os.O_PATH if link else os.O_RDONLY)
        try:
            if link:
                require(stat.S_ISLNK(os.fstat(fd).st_mode)
                        and filesystem(fd)["f_type"] == 0x9FA0, "link is not on procfs")
                buffer = c.create_string_buffer(128)
                size = libc.readlinkat(fd, b"", buffer, len(buffer))
                require(0 < size < len(buffer), "bounded empty-path readlinkat failed")
                return buffer.raw[:size]
            value = bytearray()
            for _ in range(32):
                chunk = os.read(fd, min(4096, limit + 1 - len(value)))
                require(len(value) + len(chunk) <= limit, "proc read size limit")
                if not chunk:
                    return bytes(value)
                value.extend(chunk)
            raise Refusal("proc read call limit")
        finally:
            os.close(fd)

    try:
        require(filesystem(root) == witness["values"], "actual C/Python fstatfs mismatch")
        require(witness["values"]["f_type"] == 0x9FA0, "not procfs")
        c.set_errno(0)
        require(libc.fstatfs(-1, c.byref(StatFS())) == -1 and c.get_errno() == errno.EBADF,
                "Python errno mismatch")
        pid = str(os.getpid())
        require(read("self", link=True) == pid.encode(), "self PID view mismatch")
        boot = read("sys/kernel/random/boot_id", 64)
        require(re.fullmatch(rb"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\n", boot), "boot UUID")
        status = read(f"{pid}/status")
        require([line.split()[1:] for line in status.splitlines() if line.startswith(b"NSpid:")]
                == [[pid.encode()]], "NSpid view mismatch")
        raw = read(f"{pid}/stat", 16384)
        require(raw.startswith(pid.encode() + b" (") and raw.endswith(b"\n"), "stat framing")
        fields = raw[raw.rfind(b")") + 2:].split()
        require(len(fields) >= 20 and re.fullmatch(rb"0|[1-9][0-9]*", fields[19])
                and int(fields[19]) < 2**64, "stat start ticks")
        ns = {name: read(f"{pid}/ns/{name}", link=True)
              for name in ("pid", "time", "time_for_children")}
        for name, value in ns.items():
            require(re.fullmatch(("pid" if name == "pid" else "time").encode()
                                 + rb":\[[1-9][0-9]*\]", value), "namespace link syntax")
        require(ns["time"] == ns["time_for_children"], "time namespace association")
        offsets = [line.split() for line in read(f"{pid}/timens_offsets", 256).splitlines()]
        require(sorted(offsets) == [[b"boottime", b"0", b"0"], [b"monotonic", b"0", b"0"]],
                "nonzero or malformed time offsets")
        os.kill(os.getpid(), 0)
        legacy = run(["/usr/bin/ps", "-p", pid, "-o", "lstart="]).strip()
        require(bool(legacy), "legacy ps live observation empty")
        return {"fstatfs": "matched", "openat2": "resolved", "namespace_links": "readlinkat",
                "boot_uuid": "canonical", "pid_view": "self+stat+NSpid",
                "time_offsets": "zero", "legacy_ps": "nonempty", "kill_zero": "live"}
    finally:
        os.close(root)


def self_test():
    good = {**expected_abi(), "values": {name: [0] * count if count else 0
            for name, count in ((name, {"f_fsid": 2, "f_spare": 4}.get(name, 0))
                                for name, _ in StatFS._fields_)},
            "bad_fstatfs": [-1, errno.EBADF], "openat2": [0, 0]}
    encoded = json.dumps(good)
    validate_report(encoded)
    duplicates = ('{"openat2": [0, 0], ' + encoded[1:],
                  encoded.replace('"constants": {', '"constants": {"syscall": 437, ', 1))
    for raw in duplicates:
        require(json.loads(raw) == good, "invalid duplicate-key control")
        try:
            validate_report(raw)
        except Refusal as error:
            require(type(error) is Refusal and str(error) == "duplicate JSON key",
                    "self-test wrong duplicate-key refusal")
        else:
            raise Refusal("self-test accepted duplicate JSON key")
    bad = copy.deepcopy(good)
    bad["statfs"]["fields"]["f_flags"][0] += 1
    for raw in (json.dumps(bad), '{}', '{',
                json.dumps({**good, "openat2": [-1, errno.ENOSYS]}),
                json.dumps({**good, "openat2": [False, 0]}),
                json.dumps({**good, "bad_fstatfs": [-1, errno.EPERM]})):
        try:
            validate_report(raw)
        except (Refusal, ValueError):
            continue
        raise Refusal("self-test accepted bad witness")
    require(run([sys.executable, "-I", "-B", "-c", "print('control')"]) == b"control\n",
            "self-test successful command output mismatch")
    for code, deadline, expected in (
            ("raise SystemExit(7)", 3, "external command failed: exit=7"),
            ("print('x' * 20000)", 3, "external output limit"),
            ("import time; time.sleep(10)", 0.2, "external command timeout")):
        try:
            run([sys.executable, "-I", "-B", "-c", code], deadline)
        except Refusal as error:
            require(type(error) is Refusal and str(error) == expected,
                    f"self-test wrong external refusal: expected {expected}, got {error}")
        else:
            raise Refusal("self-test accepted external failure")
    return {"status": "SELF_TEST_PASSED", "backend_qualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--qualify", action="store_true", help="compile reviewed sibling C in isolated guest")
    mode.add_argument("--self-test", action="store_true", help="synthetic refusals and bounded subprocess checks")
    args = parser.parse_args()
    try:
        if args.self_test:
            result = self_test()
        else:
            observed, libc = profile()  # Refuse the host before creating files or compiling.
            with tempfile.TemporaryDirectory(prefix="native-abi-") as directory:
                binary = str(Path(directory) / "witness")
                run(["/usr/bin/cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                     str(Path(__file__).resolve().with_name("native-process-abi.c")), "-o", binary], 30)
                witness = validate_report(run([binary]))
                result = {"status": "PRIMITIVES_VERIFIED", "backend_qualified": False,
                          "profile": observed, "abi": witness, "checks": primitives(libc, witness)}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Refusal, OSError, ValueError, AttributeError, subprocess.SubprocessError) as error:
        unsupported = isinstance(error, UnsupportedProfile)
        print(json.dumps({"status": "UNQUALIFIED" if unsupported else "FAILED",
                          "backend_qualified": False, "reason": str(error)}))
        return 3 if unsupported else 1


if __name__ == "__main__":
    sys.exit(main())
