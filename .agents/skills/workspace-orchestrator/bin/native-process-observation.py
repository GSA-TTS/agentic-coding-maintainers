"""One-shot Linux procfs observer. Fixed sources, no environment fault hooks.

Only the measured aarch64 LP64 glibc 2.36 / CPython 3.12.16 / Linux 6.12.113
profile is admitted. This additive foundation does not enable native claims.
"""

import ctypes as c
import errno
import json
import os
import platform
import re
import stat
import sys


class Unknown(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Unknown(message)


def decimal(raw, positive=False):
    require(type(raw) is bytes and len(raw) <= 20
            and re.fullmatch(rb"0|[1-9][0-9]*", raw) is not None, "decimal syntax")
    require((1 if positive else 0) <= int(raw) < 2**64, "decimal range")
    return raw.decode("ascii")


def boot_id(raw):
    require(re.fullmatch(rb"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\n", raw), "boot UUID")
    return raw[:-1].decode("ascii")


def namespace(raw, kind):
    match = re.fullmatch(kind.encode("ascii") + rb":\[([0-9]+)\]", raw)
    require(match is not None, "namespace syntax")
    return decimal(match[1], positive=True)


def start_ticks(raw, pid):
    require(len(raw) <= 16384 and raw.startswith(str(pid).encode() + b" (")
            and raw.endswith(b"\n"), "stat framing")
    end = raw.rfind(b")")
    require(end >= len(str(pid)) + 2 and raw[end + 1:end + 2] == b" ", "stat comm delimiter")
    fields = raw[end + 2:-1].split()
    # Qualified kernel emits 52 fields. comm can contain arbitrary bytes; only
    # the final ')' delimits it. Never decode or persist comm.
    require(len(fields) == 50 and fields[0] in tuple(bytes([x]) for x in b"RSDZTtXxKWPI"), "stat fields")
    return decimal(fields[19])


def status_view(raw, pid, tgid):
    lines = raw.splitlines()
    for label, expected in ((b"NSpid:", [str(pid).encode()]),
                            (b"Pid:", [str(pid).encode()]), (b"Tgid:", [str(tgid).encode()])):
        require([line.split()[1:] for line in lines if line.startswith(label)] == [expected], "PID view")


def zero_offsets(raw):
    require(sorted(line.split() for line in raw.splitlines()) == [
        [b"boottime", b"0", b"0"], [b"monotonic", b"0", b"0"]], "time offsets")


class StatFS(c.Structure):
    _fields_ = [(name, kind) for name, kind in (
        ("f_type", c.c_long), ("f_bsize", c.c_long), ("f_blocks", c.c_ulong),
        ("f_bfree", c.c_ulong), ("f_bavail", c.c_ulong), ("f_files", c.c_ulong),
        ("f_ffree", c.c_ulong), ("f_fsid", c.c_int * 2), ("f_namelen", c.c_long),
        ("f_frsize", c.c_long), ("f_flags", c.c_long), ("f_spare", c.c_long * 4))]


class OpenHow(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ("flags", "mode", "resolve")]


def profile():
    # Measured independently against installed C headers in PR 187. No runtime
    # compiler, guessed buffer, find_library, or weaker syscall fallback.
    require(platform.system() == "Linux" and platform.machine() == "aarch64"
            and platform.release() == "6.12.113" and platform.python_implementation() == "CPython"
            and platform.python_version() == "3.12.16" and sys.byteorder == "little"
            and c.sizeof(c.c_void_p) == c.sizeof(c.c_long) == 8 and c.sizeof(c.c_int) == 4,
            "unqualified profile")
    require(c.sizeof(StatFS) == 120 and c.alignment(StatFS) == 8
            and [(getattr(StatFS, name).offset, c.sizeof(kind), c.alignment(kind))
                 for name, kind in StatFS._fields_] == [
                     (0, 8, 8), (8, 8, 8), (16, 8, 8), (24, 8, 8), (32, 8, 8),
                     (40, 8, 8), (48, 8, 8), (56, 8, 4), (64, 8, 8), (72, 8, 8),
                     (80, 8, 8), (88, 32, 8)]
            and c.sizeof(OpenHow) == 24 and c.alignment(OpenHow) == 8
            and [getattr(OpenHow, name).offset for name, _ in OpenHow._fields_] == [0, 8, 16], "ABI layout")
    require((os.O_PATH, os.O_NOFOLLOW, os.O_CLOEXEC, os.O_DIRECTORY) == (
        0o10000000, 0o100000, 0o2000000, 0o40000), "ABI constants")
    libc = c.CDLL(None, use_errno=True)
    libc.gnu_get_libc_version.argtypes, libc.gnu_get_libc_version.restype = [], c.c_char_p
    require(libc.gnu_get_libc_version() == b"2.36", "unqualified loaded libc")
    libc.fstatfs.argtypes, libc.fstatfs.restype = [c.c_int, c.POINTER(StatFS)], c.c_int
    libc.syscall.argtypes = [c.c_long, c.c_int, c.c_char_p, c.POINTER(OpenHow), c.c_size_t]
    libc.syscall.restype = c.c_long
    libc.readlinkat.argtypes = [c.c_int, c.c_char_p, c.c_void_p, c.c_size_t]
    libc.readlinkat.restype = c.c_ssize_t
    return libc


class Proc:
    """A held fixed proc root and bounded identity-source descriptor inventory."""

    def __init__(self, libc):
        self.libc = libc
        self.sources = {}
        self.root = os.open("/proc", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            self.filesystem(self.root)
            self.root_identity = self.association(self.root)
        except BaseException:
            os.close(self.root)
            raise

    def close(self):
        for fd, _ in self.sources.values():
            os.close(fd)
        os.close(self.root)

    def filesystem(self, fd):
        value = StatFS()
        require(self.libc.fstatfs(fd, c.byref(value)) == 0, "fstatfs failed")
        require(value.f_type == 0x9FA0, "not procfs")

    def open(self, path, flags, directory=None):
        how = OpenHow(flags | os.O_CLOEXEC | os.O_NOFOLLOW, 0, 8 | 4 | 1)
        c.set_errno(0)
        fd = self.libc.syscall(437, self.root if directory is None else directory,
                              path.encode("ascii"), c.byref(how), c.sizeof(how))
        if fd < 0:
            error = c.get_errno()
            raise OSError(error, "constrained proc open refused")
        return fd

    @staticmethod
    def read_fd(fd, limit):
        output = bytearray()
        for _ in range(64):
            chunk = os.read(fd, min(4096, limit + 1 - len(output)))
            require(len(output) + len(chunk) <= limit, "proc byte limit")
            if not chunk:
                return bytes(output)
            output.extend(chunk)
        raise Unknown("proc read call limit")

    def association(self, fd):
        info = self.open(f"{os.getpid()}/fdinfo/{fd}", os.O_RDONLY)
        try:
            self.filesystem(info)
            raw = self.read_fd(info, 4096)
        finally:
            os.close(info)
        values = [line.split()[1:] for line in raw.splitlines() if line.startswith(b"mnt_id:")]
        require(len(values) == 1 and len(values[0]) == 1, "mount ID shape")
        mount = decimal(values[0][0], positive=True)
        value = os.fstat(fd)
        return value.st_dev, value.st_ino, value.st_mode, mount

    def source(self, path, flags, directory=None):
        require(path not in self.sources and len(self.sources) < 48, "source inventory")
        relative = path if directory is None else path.split("/", 1)[1]
        fd = self.open(relative, flags, directory)
        return self.retain(path, fd)

    def retain(self, path, fd):
        try:
            self.filesystem(fd)
            association = self.association(fd)
            self.sources[path] = fd, association
            return fd
        except BaseException:
            os.close(fd)
            raise

    def read(self, path, limit=65536, directory=None):
        fd = self.source(path, os.O_RDONLY, directory)
        require(stat.S_ISREG(os.fstat(fd).st_mode), "source not regular")
        return self.read_fd(fd, limit)

    def link(self, path, directory=None):
        fd = self.source(path, os.O_PATH, directory)
        require(stat.S_ISLNK(os.fstat(fd).st_mode), "source not link")
        buffer = c.create_string_buffer(128)
        size = self.libc.readlinkat(fd, b"", buffer, len(buffer))
        require(0 < size < len(buffer), "bounded readlinkat")
        return buffer.raw[:size]

    def context(self, request):
        pid = os.getpid()
        require(os.getppid() == request["caller_tgid"], "caller is not parent")
        require(self.link("self") == str(pid).encode()
                and self.link("thread-self") == f"{pid}/task/{pid}".encode(), "helper PID view")
        helper = str(pid)
        caller = f'{request["caller_tgid"]}/task/{request["caller_tid"]}'
        helper_ticks = start_ticks(self.read(f"{helper}/stat", 16384), pid)
        caller_ticks = start_ticks(self.read(f"{caller}/stat", 16384), request["caller_tid"])
        status_view(self.read(f"{helper}/status"), pid, pid)
        status_view(self.read(f"{caller}/status"), request["caller_tid"], request["caller_tgid"])
        namespaces = []
        for base in (helper, caller):
            ns = {name: namespace(self.link(f"{base}/ns/{name}"), kind) for name, kind in (
                ("pid", "pid"), ("pid_for_children", "pid"), ("time", "time"), ("time_for_children", "time"))}
            require(ns["pid"] == ns["pid_for_children"] and ns["time"] == ns["time_for_children"],
                    "child namespace transition")
            namespaces.append(ns)
        require(namespaces[0] == namespaces[1], "caller/helper namespaces")
        # Linux v6.12 fs/proc/base.c exposes timens_offsets in tgid_base_stuff,
        # not tid_base_stuff. proc_timens_show_offsets() reads the selected
        # task's time_for_children namespace (kernel/time/namespace.c). The
        # equality above proves helper current == helper child == caller-thread
        # current == caller-thread child, so helper offsets qualify that shared
        # namespace without assuming the process leader represents the caller.
        # This proof and the offsets are repeated in the second complete sample.
        zero_offsets(self.read(f"{helper}/timens_offsets", 256))
        context = {"boot_id": boot_id(self.read("sys/kernel/random/boot_id", 64)),
                   "pid_namespace_inode": namespaces[0]["pid"]}
        require(request["expected_context"] is None or request["expected_context"] == context,
                "recorded context mismatch")
        # Whole-root policy: accept genuine procfs rooted at '/', mounted at
        # '/proc', including an equivalent whole-root bind. Inner binds cannot
        # cross the constrained resolver. This does not authenticate a mount admin.
        mountinfo = self.read(f"{helper}/mountinfo", 131072)
        matches = [line.split() for line in mountinfo.splitlines()
                   if line.split()[:1] == [self.root_identity[3].encode()]]
        require(len(matches) == 1, "root mount inventory")
        fields = matches[0]
        require(len(fields) >= 10 and fields[3:5] == [b"/", b"/proc"] and b"-" in fields,
                "root mount policy")
        separator = fields.index(b"-")
        require(separator >= 6 and len(fields) == separator + 4 and fields[separator + 1] == b"proc",
                "root mount filesystem")
        return context, (namespaces[0], helper_ticks, caller_ticks)

    def target(self, pid):
        base = str(pid)
        if base not in self.sources:
            self.source(base, os.O_RDONLY | os.O_DIRECTORY)
        directory = self.sources[base][0]
        ticks = start_ticks(self.read(f"{base}/stat", 16384, directory), pid)
        inode = namespace(self.link(f"{base}/ns/pid", directory), "pid")
        status_view(self.read(f"{base}/status", directory=directory), pid, pid)
        return ticks, inode

    def same_sources(self, other):
        require(self.root_identity == other.root_identity and self.sources.keys() == other.sources.keys(),
                "root/source replacement")
        for path, (_, identity) in self.sources.items():
            require(identity == other.sources[path][1], "source association changed")
            require(self.association(self.sources[path][0]) == identity
                    and other.association(other.sources[path][0]) == identity, "held source changed")
        # Re-read held fd mount IDs, not just cached associations.
        require(self.association(self.root) == self.root_identity
                and other.association(other.root) == other.root_identity, "root mount changed")
        fresh = Proc(self.libc)
        try:
            require(fresh.root_identity == self.root_identity, "final root replacement")
            for path, (_, identity) in self.sources.items():
                flags = (os.O_PATH if stat.S_ISLNK(identity[2]) else os.O_RDONLY
                         | (os.O_DIRECTORY if stat.S_ISDIR(identity[2]) else 0))
                fresh.source(path, flags)
                require(fresh.sources[path][1] == identity, "final source replacement")
        finally:
            fresh.close()


def missing(proc, pid):
    try:
        fd = proc.open(str(pid), os.O_RDONLY | os.O_DIRECTORY)
    except OSError as error:
        if error.errno == errno.ENOENT:
            return True
        raise
    proc.retain(str(pid), fd)  # Child-file/association ENOENT must not mean absent.
    return False


def no_process(pid):
    try:
        os.kill(pid, 0)
    except OSError as error:
        if error.errno == errno.ESRCH:
            return True
        raise
    return False


def observe(request, libc):
    first = Proc(libc)
    try:
        before, namespaces = first.context(request)  # Always before target lookup.
        pid = request["pid"]
        # Only an initial missing directory can enter the absence protocol.
        absent = missing(first, pid)
        if absent:
            require(no_process(pid), "missing but signal-visible target")
            sample = None
        else:
            sample = first.target(pid)  # Disappearance here is unknown, never absent.
            require(sample[1] == before["pid_namespace_inode"], "target namespace")
        second = Proc(libc)
        try:
            if absent:
                require(missing(second, pid) and no_process(pid), "absence changed")
            else:
                require(second.target(pid) == sample, "target identity changed")
            after, final_namespaces = second.context(request)
            require(before == after and namespaces == final_namespaces, "context changed")
            first.same_sources(second)
            identity = None if absent else {"schema_version": 1, "backend": "linux-procfs",
                                           **before, "start_ticks": sample[0]}
            return {"version": 1, "pid": pid, "caller_tgid": request["caller_tgid"],
                    "caller_tid": request["caller_tid"], "status": "absent" if absent else "alive",
                    "identity": identity, "context": before}
        finally:
            second.close()
    finally:
        first.close()


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate request key")
        result[key] = value
    return result


def request_value(raw):
    require(len(raw) <= 4096 and raw.isascii(), "request size/encoding")
    value = json.loads(raw, object_pairs_hook=pairs)
    require(type(value) is dict and set(value) == {
        "version", "pid", "caller_tgid", "caller_tid", "expected_context"}, "request shape")
    require(type(value["version"]) is int and value["version"] == 1, "request version")
    for key in ("pid", "caller_tgid", "caller_tid"):
        require(type(value[key]) is int and 0 < value[key] < 2**31, "request PID")
    context = value["expected_context"]
    if context is not None:
        require(type(context) is dict and set(context) == {"boot_id", "pid_namespace_inode"}, "request context")
        require(type(context["boot_id"]) is str and type(context["pid_namespace_inode"]) is str, "context types")
        boot_id(context["boot_id"].encode("ascii") + b"\n")
        decimal(context["pid_namespace_inode"].encode("ascii"), positive=True)
    return value


def main():
    request = None
    try:
        require(len(sys.argv) == 2, "request arguments")
        request = request_value(sys.argv[1])
        result = observe(request, profile())
    except (Unknown, OSError, ValueError, AttributeError, RecursionError):
        if request is None:
            return 3
        result = {"version": 1, "pid": request["pid"], "caller_tgid": request["caller_tgid"],
                  "caller_tid": request["caller_tid"], "status": "unknown", "identity": None, "context": None}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
