"""Opt-in, guest-only kernel qualification; never part of the default suite.

Run with --qualify-disposable-guest only in the separately reviewed, credential-
free guest, with guest-local root setup authority and no host shares or sockets.
The flag acknowledges that external isolation requirement; this program cannot
prove a VM boundary. Apply this sibling file to the exact candidate installation
before running it. Candidate paths are fixed, and its checksum gate is unchanged.

Execution additionally requires an independently qualified external watchdog:
cover the entire invocation in a disposable PID/mount/network boundary, enforce
the 480-second lifetime externally, and confirm descendant teardown on every exit
and timeout. The internal 20-second case/5-second cleanup/480-second run budgets
are cooperative deadlines, not universal bounds on blocking kernel operations.
Use a dedicated proof guest with verified guest-local storage; hiding a runtime
share does not establish independence of an overlay's backing layers.

Setup processes never import candidate code. Callers import only after UID/GID
1000, empty capabilities/groups, NoNewPrivs, descriptor and resource confinement.
All negative observations require an alive baseline and an independent injection
witness. Missing facilities are UNQUALIFIED; violated expectations and cleanup
failures are FAILED. Even a passing matrix leaves backend_qualified false.

Root-replacement cases instrument verified helper bytes only at Proc construction
boundaries; their evidence is distinct from unmodified public-launch controls.
The fixture intentionally is not a command runner.
"""

import array
import base64
import ctypes as c
import errno
import importlib.util
import json
import os
from pathlib import Path
import platform
import resource
import select
import signal
import socket
import struct
import sys
import threading
import time


BIN = Path(__file__).resolve().parents[1] / "bin"
CASE_SECONDS, CLEANUP_SECONDS, TOTAL_SECONDS = 20, 5, 480
PACKET_LIMIT, OUTPUT_LIMIT = 16384, 262144
NEWNS, NEWPID, NEWNET, NEWTIME = 0x20000, 0x20000000, 0x40000000, 0x80
OFFSETS = {
    "time-zero": (0, 0, 0, 0),
    "time-boot-positive": (0, 0, 60, 0),
    "time-boot-negative": (0, 0, -1, 0),
    "time-boot-fractional": (0, 0, 0, 1),
    "time-monotonic": (1, 0, 0, 0),
    "time-divergence": (0, 0, 60, 0),
}
CASES = ("fresh-pid", "bind-stat", "bind-boot", "bind-ns", "bind-target",
         "ancestor-proc", "pid-divergence", *OFFSETS, "seccomp-eperm", "seccomp-enosys")
ROOT_CASES = ("root-barrier-control", "root-between-samples", "root-final-recheck")

# Test-only fixed bootstrap. Source bytes come from the production checksum gate,
# not another import/path read. Only __init__ is wrapped; all observations,
# qualification, errors and wire serialization remain the verified implementation.
ROOT_BOOTSTRAP = """
import base64,json,os,socket,sys
source=base64.b64decode(sys.argv[1],validate=True)
path,request,stage,address=sys.argv[2:]
stage=int(stage)
assert stage in (2,3)
sys.argv=[path,request]
scope={'__name__':'qualification_instrumented_helper','__file__':path,'__package__':None,'__spec__':None}
exec(compile(source,path,'exec'),scope)
original=scope['Proc'].__init__
count=0
def instrumented(self,libc):
    global count
    count+=1
    if count==stage:
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET) as channel:
                channel.settimeout(2)
                channel.connect('\\0'+address)
                raw=json.dumps({'stage':stage,'pid':os.getpid()}).encode()
                assert channel.send(raw)==len(raw)
                assert channel.recv(16)==b'resume'
        except (OSError,AssertionError) as error:
            # Escape main's production OSError-to-unknown mapping. A failed
            # qualification barrier must exit nonzero, never prove refusal.
            raise RuntimeError('qualification barrier failed') from error
    original(self,libc)
scope['Proc'].__init__=instrumented
raise SystemExit(scope['main']())
"""


def root_address(case, coordinator):
    expect(case in ROOT_CASES, "fixed root case")
    return f"native-root-{coordinator}-{case}"


def instrumented_root(observer, pid, stage, address):
    path, source = observer._trusted_helper()
    encoded = base64.b64encode(source).decode("ascii")
    request = {"version": 1, "pid": pid, "caller_tgid": os.getpid(),
               "caller_tid": threading.get_native_id(), "expected_context": None}
    raw = observer._collect([sys.executable, "-I", "-B", "-c", ROOT_BOOTSTRAP, encoded,
                             str(path), json.dumps(request, separators=(",", ":")), str(stage), address])
    return observer._reply(raw, request)


class Unqualified(Exception):
    pass


class Failed(Exception):
    pass


def need(value, reason):
    if not value:
        raise Unqualified(reason)


def expect(value, reason):
    if not value:
        raise Failed(reason)


def read(path, limit=131072):
    with open(path, "rb") as stream:
        raw = stream.read(limit + 1)
    need(len(raw) <= limit, "kernel witness byte limit")
    return raw


def status():
    return {line.split(b":", 1)[0].decode(): line.split(b":", 1)[1].split()
            for line in read("/proc/self/status").splitlines() if b":" in line}


def ns(name):
    return os.readlink("/proc/self/ns/" + name)


def libc():
    lib = c.CDLL(None, use_errno=True)
    lib.unshare.argtypes, lib.unshare.restype = [c.c_int], c.c_int
    lib.mount.argtypes = [c.c_char_p, c.c_char_p, c.c_char_p, c.c_ulong, c.c_char_p]
    lib.mount.restype = c.c_int
    lib.umount2.argtypes, lib.umount2.restype = [c.c_char_p, c.c_int], c.c_int
    lib.prctl.argtypes = [c.c_int, c.c_ulong, c.c_ulong, c.c_ulong, c.c_ulong]
    lib.prctl.restype = c.c_int
    return lib


def checked(rc, reason):
    if rc != 0:
        raise Unqualified(f"{reason}: errno {c.get_errno()}")


def unshare(flags):
    checked(libc().unshare(flags), "unshare")


def private_mounts():
    checked(libc().mount(None, b"/", None, (1 << 18) | (1 << 14), None), "private propagation")
    fields = [line.split() for line in read("/proc/self/mountinfo").splitlines()]
    need(fields and all(not word.startswith((b"shared:", b"master:"))
                        for row in fields for word in row[6:row.index(b"-")]),
         "mount propagation is not private")


def proc_mount():
    checked(libc().mount(b"proc", b"/proc", b"proc", 2 | 4 | 8, None), "fresh proc mount")


def unmount(path):
    checked(libc().umount2(path.encode(), 0), "explicit unmount")


def drop(keep):
    """No privileged descriptors survive into candidate imports, including stdio."""
    for fd in range(3, 256):
        if fd not in keep:
            try:
                os.close(fd)
            except OSError:
                pass
    # Also close inherited descriptors above the new soft/hard limit.
    os.closerange(256, 1048576)
    null = os.open("/dev/null", os.O_RDWR | os.O_CLOEXEC)
    for fd in (0, 1, 2):
        os.dup2(null, fd)
    if null > 2:
        os.close(null)
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    lib = libc()
    last = int(read("/proc/sys/kernel/cap_last_cap", 32))
    need(0 <= last <= 63, "capability range")
    for cap in range(last + 1):
        checked(lib.prctl(24, cap, 0, 0, 0), "drop bounding capability")
    checked(lib.prctl(47, 4, 0, 0, 0), "clear ambient capabilities")
    os.setgroups([])
    os.setresgid(1000, 1000, 1000)
    os.setresuid(1000, 1000, 1000)

    class CapHeader(c.Structure):
        _fields_ = [("version", c.c_uint32), ("pid", c.c_int)]

    class CapData(c.Structure):
        _fields_ = [(name, c.c_uint32) for name in ("effective", "permitted", "inheritable")]

    header, data = CapHeader(0x20080522, 0), (CapData * 2)()
    lib.capset.argtypes, lib.capset.restype = [c.POINTER(CapHeader), c.POINTER(CapData)], c.c_int
    checked(lib.capset(c.byref(header), data), "clear all capability sets")
    checked(lib.prctl(38, 1, 0, 0, 0), "NoNewPrivs")
    # setresuid clears dumpability. Restore ordinary same-UID proc-link access;
    # core output remains disabled. Otherwise a permission artifact masks cases.
    checked(lib.prctl(4, 1, 0, 0, 0), "same-UID proc visibility")
    values = status()
    need(os.getresuid() == os.getresgid() == (1000, 1000, 1000) and not os.getgroups()
         and values["NoNewPrivs"] == [b"1"]
         and all(int(values[key][0], 16) == 0
                 for key in ("CapEff", "CapPrm", "CapInh", "CapAmb", "CapBnd")),
         "candidate privilege profile")
    os.environ.clear()
    os.environ.update({"PATH": "/usr/bin:/bin", "LC_ALL": "C"})


def load_candidate():
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        need(spec is not None and spec.loader is not None, "candidate module spec")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    probe = load("qualification_probe", BIN / "native-process-observation.py")
    try:
        probe.profile()
    except (probe.Unknown, AttributeError) as error:
        raise Unqualified("candidate profile unavailable") from error
    observer = load("qualification_observer", BIN / "runtime-observation.py")
    # Public observations retain the production checksum check too.
    try:
        observer._trusted_helper()
    except (observer.NativeUnknown, OSError) as error:
        raise Unqualified("candidate checksum preflight unavailable") from error
    return observer


def send(channel, value):
    raw = json.dumps(value, separators=(",", ":")).encode()
    expect(len(raw) <= PACKET_LIMIT, "control output limit")
    channel.settimeout(2)
    expect(channel.send(raw) == len(raw), "short control packet")


def receive(channel, seconds=2):
    channel.settimeout(seconds)
    raw, _, flags, _ = channel.recvmsg(PACKET_LIMIT)
    expect(raw and not flags & socket.MSG_TRUNC, "missing/oversized control packet")
    value = json.loads(raw)
    if isinstance(value, dict) and "exception" in value:
        kind = Failed if value["exception"] == "FAILED" else Unqualified
        raise kind(value["reason"])
    return value


def report_error(channel, error):
    # Only exception class/our bounded fixed messages; never dump proc or command output.
    reason = str(error)[:160] if isinstance(error, (Failed, Unqualified)) else type(error).__name__
    send(channel, {"exception": error_status(error), "reason": reason})


def error_status(error):
    if isinstance(error, Unqualified) or isinstance(error, OSError) and not isinstance(error, TimeoutError):
        return "UNQUALIFIED"
    return "FAILED"


def exited(pidfd):
    return bool(select.select([pidfd], [], [], 0)[0])


def stop(pid, pidfd, deadline):
    try:
        if not exited(pidfd):
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            except ProcessLookupError:
                pass
    finally:
        reaped = reap(pid, pidfd, deadline)
    return reaped


def reap(pid, pidfd, deadline):
    while time.monotonic() < deadline:
        found, _ = os.waitpid(pid, os.WNOHANG)
        if found == pid:
            return exited(pidfd)
        select.select([pidfd], [], [], min(.02, max(0, deadline - time.monotonic())))
    return False


def stop_unadmitted(pid, deadline):
    """Only for a gated, unreaped direct child when pidfd_open itself failed."""
    reaped = False
    try:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    finally:
        while time.monotonic() < deadline:
            if os.waitpid(pid, os.WNOHANG)[0] == pid:
                reaped = True
                break
            time.sleep(.01)
        expect(reaped, "unadmitted child cleanup deadline")


def fork_held(function):
    """Child cannot proceed until its parent has a stable pidfd."""
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        pid = os.fork()
    except BaseException:
        try:
            parent.close()
        finally:
            child.close()
        raise
    if pid == 0:
        parent.close()
        try:
            need(receive(child) == "go", "child admission")
            function(child)
        except BaseException as error:
            try:
                report_error(child, error)
            except BaseException:
                pass
        finally:
            os._exit(0)
    child.close()
    try:
        pidfd = os.pidfd_open(pid)
    except BaseException:
        # This unreaped direct child cannot be reused; it has not passed its gate.
        try:
            stop_unadmitted(pid, time.monotonic() + CLEANUP_SECONDS)
        finally:
            parent.close()
        raise
    try:
        send(parent, "go")
    except BaseException:
        # Ownership has not reached the caller: clean up even if sending the
        # admission packet failed after the child acquired permission to run.
        finish((pid, pidfd, parent))
        raise
    return pid, pidfd, parent


def finish(child):
    pid, pidfd, channel = child
    try:
        try:
            expect(stop(pid, pidfd, time.monotonic() + 2), "direct child cleanup deadline")
        finally:
            try:
                os.close(pidfd)
            finally:
                channel.close()
    except BaseException as error:
        raise Failed("direct child cleanup failed") from error


class OpenHow(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ("flags", "mode", "resolve")]


class StatFS(c.Structure):
    # Independently fixed Linux aarch64 LP64 layout; candidate profile admission
    # occurs only after privilege drop inside each contained case.
    _fields_ = [("type", c.c_long), ("rest", c.c_byte * 112)]


def constrained(path, directory=False):
    root = os.open("/proc", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        lib = libc()
        lib.syscall.argtypes = [c.c_long, c.c_int, c.c_char_p, c.POINTER(OpenHow), c.c_size_t]
        lib.syscall.restype = c.c_long
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | (os.O_DIRECTORY if directory else 0)
        how = OpenHow(flags, 0, 8 | 4 | 1)
        c.set_errno(0)
        fd = lib.syscall(437, root, path.encode(), c.byref(how), c.sizeof(how))
        if fd < 0:
            return c.get_errno()
        os.close(fd)
        return 0
    finally:
        os.close(root)


def association(fd):
    value = StatFS()
    lib = libc()
    lib.fstatfs.argtypes, lib.fstatfs.restype = [c.c_int, c.POINTER(StatFS)], c.c_int
    checked(lib.fstatfs(fd, c.byref(value)), "witness fstatfs")
    need(value.type == 0x9FA0, "witness is not procfs")
    fields = [line.split()[1:] for line in read(f"/proc/self/fdinfo/{fd}", 4096).splitlines()
              if line.startswith(b"mnt_id:")]
    need(len(fields) == 1 and len(fields[0]) == 1, "mount ID witness")
    stat = os.fstat(fd)
    return stat.st_dev, stat.st_ino, int(fields[0][0])


def seccomp(error):
    class Filter(c.Structure):
        _fields_ = [("code", c.c_ushort), ("jt", c.c_ubyte), ("jf", c.c_ubyte), ("k", c.c_uint32)]

    class Program(c.Structure):
        _fields_ = [("len", c.c_ushort), ("filter", c.POINTER(Filter))]

    # Reject another architecture; deny only aarch64 openat2 (437).
    code = (Filter * 7)(Filter(0x20, 0, 0, 4), Filter(0x15, 1, 0, 0xC00000B7),
                        Filter(0x06, 0, 0, 0x80000000), Filter(0x20, 0, 0, 0),
                        Filter(0x15, 0, 1, 437), Filter(0x06, 0, 0, 0x50000 | error),
                        Filter(0x06, 0, 0, 0x7FFF0000))
    program = Program(len(code), code)
    checked(libc().prctl(22, 2, c.addressof(program), 0, 0), "seccomp filter")


def set_offsets(offsets):
    text = f"monotonic {offsets[0]} {offsets[1]}\nboottime {offsets[2]} {offsets[3]}\n"
    with open("/proc/self/timens_offsets", "w", encoding="ascii") as stream:
        stream.write(text)


def time_witness(offsets):
    actual = sorted(line.split() for line in read("/proc/self/timens_offsets", 256).splitlines())
    expected = sorted([[b"monotonic", str(offsets[0]).encode(), str(offsets[1]).encode()],
                       [b"boottime", str(offsets[2]).encode(), str(offsets[3]).encode()]])
    need(actual == expected, "installed time offsets mismatch")
    return {"offsets": [part.decode() for line in actual for part in line],
            "current": ns("time"), "children": ns("time_for_children")}


def target(channel):
    drop({channel.fileno()})
    send(channel, "ready")
    receive(channel, CASE_SECONDS)  # Pipe-held, with an independent finite deadline.


def caller(channel, case, pid, setup=None):
    witness = {}
    retained = None
    identity = None
    coordinator = os.getppid()
    try:
        if setup == "pid-divergence":
            before = ns("pid")
            unshare(NEWPID)

            def nested(child):
                drop({child.fileno()})
                send(child, ns("pid"))
                receive(child, CASE_SECONDS)

            retained = fork_held(nested)
            entered = receive(retained[2])
            need(ns("pid") == before and before != ns("pid_for_children") == entered,
                 "PID child divergence witness")
            witness = {"current": before, "children": entered, "retained_init": True}
        elif setup == "time-divergence":
            # This child has entered the coordinator's +60 namespace. Keep the
            # eventual candidate in this process after creating its child namespace.
            current = time_witness(OFFSETS[setup])
            need(current["current"] == current["children"], "entered +60 time namespace")
            unshare(NEWTIME)
            set_offsets((0, 0, 0, 0))

            def time_child(child):
                drop({child.fileno()})
                send(child, time_witness((0, 0, 0, 0)))
                receive(child, CASE_SECONDS)

            retained = fork_held(time_child)
            entered = receive(retained[2])
            witness = time_witness((0, 0, 0, 0))
            need(witness["current"] == current["current"] != witness["children"]
                 and entered["current"] == entered["children"] == witness["children"],
                 "time child divergence witness")
            witness["current_offsets_before_unshare"] = current["offsets"]
            witness["child_entered"] = True
        elif setup in OFFSETS:
            witness = time_witness(OFFSETS[setup])
            need(witness["current"] == witness["children"], "entered time namespace")
        # The only retained handles refer to this caller's unprivileged witnesses.
        keep = {channel.fileno()}
        if retained:
            keep.update((retained[1], retained[2].fileno()))
        drop(keep)
        observer = load_candidate()
        view = {"self": os.readlink("/proc/self"), "pid": os.getpid(),
                "nspid": [int(x) for x in status()["NSpid"]], "pid_namespace": ns("pid")}
        send(channel, {"ready": True, "profile": "candidate-profile-verified", "witness": witness,
                       "view": view})
        while True:
            command = receive(channel, CASE_SECONDS)
            request_pid = pid
            if isinstance(command, dict):
                need(case == "ancestor-proc" and set(command) == {"command", "pid"}
                     and command["command"] == "ancestor" and type(command["pid"]) is int
                     and 0 < command["pid"] < 2**31, "mapped ancestor request")
                request_pid, command = command["pid"], command["command"]
            if command == "quit":
                return
            need(command in ("observe", "thread", "absent", "filter", "ancestor", "root-second", "root-third"),
                 "fixed caller command")
            evidence = {}
            if command in ("root-second", "root-third"):
                need(case in ROOT_CASES, "root instrumentation case")
                result = instrumented_root(observer, pid, 2 if command == "root-second" else 3,
                                           root_address(case, coordinator))
                send(channel, {"observation": result,
                               "witness": {"mode": "instrumented exact-source helper qualification"}})
                continue
            elif command == "filter":
                need(case in ("seccomp-eperm", "seccomp-enosys"), "filter case")
                path = f"{pid}/stat"
                need(constrained(path) == 0, "unfiltered openat2 control")
                error = errno.EPERM if case == "seccomp-eperm" else errno.ENOSYS
                seccomp(error)
                need(constrained(path) == error and read("/proc/" + path, 16384), "seccomp witness")
                evidence = {"openat2_before": 0, "openat2_after": error, "ordinary_read": True}
            elif command == "ancestor":
                values = [int(x) for x in status()["NSpid"]]
                link = int(os.readlink("/proc/self"))
                need(len(values) >= 2 and values[-1] == os.getpid() and values[0] == link,
                     "ancestor proc view witness")
                # The coordinator supplies the pidfd-derived mapping even if
                # nested and ancestor numeric PIDs happen to coincide.
                evidence = {"nspid": values, "self": link, "getpid": os.getpid(), "pid_ns": ns("pid"),
                            "request_pid": request_pid}
            elif command == "thread":
                results = []

                def observe_thread():
                    results.append((threading.get_native_id(), observer.native_process_identity(pid)))

                thread = threading.Thread(target=observe_thread, daemon=True)
                thread.start()
                thread.join(5)
                expect(not thread.is_alive() and len(results) == 1 and results[0][0] != os.getpid(),
                       "nonleader caller deadline/identity")
                send(channel, {"observation": results[0][1], "witness": {"nonleader": True}})
                continue
            if command == "absent":
                need(identity is not None, "recorded identity for absence")
                result = observer.observe_worker_process({"pid": pid, "process_identity": identity})
            else:
                result = observer.native_process_identity(request_pid)
                if result[0] == "alive":
                    need(observer.valid_native_identity(result[1]), "public identity validation")
                    identity = result[1]
            send(channel, {"observation": result, "witness": evidence})
    finally:
        if retained:
            finish(retained)


def observation(child, command="observe"):
    send(child[2], command)
    return receive(child[2], 6)  # Production collection 3s + cleanup 1s, unchanged.


def alive(child):
    need(not exited(child[1]), "target unexpectedly exited")
    os.kill(child[0], 0)


def ancestor_target(held, baseline):
    """Bind ancestor proc paths to a retained pidfd, independently of candidate code.

    Linux renders pidfd fdinfo Pid/NSpid in the namespace of the procfs mount
    used to read fdinfo. With the ancestor proc restored, those fields map the
    same retained kernel process handle into that view; no PID search is used.
    """
    alive(held)
    fields = {line.split(b":", 1)[0]: line.split(b":", 1)[1].split()
              for line in read(f"/proc/self/fdinfo/{held[1]}", 4096).splitlines() if b":" in line}
    need(b"Pid" in fields and b"NSpid" in fields, "pidfd PID mapping unavailable")
    mapping = [int(value) for value in fields[b"NSpid"]]
    need(len(mapping) == 2 and mapping[-1] == held[0] and 0 < mapping[0] < 2**31
         and fields[b"Pid"] == [str(mapping[0]).encode()],
         "pidfd ancestor mapping")
    pid = mapping[0]
    raw_status = read(f"/proc/{pid}/status")
    for key, expected in ((b"Pid:", [pid]), (b"Tgid:", [pid]), (b"NSpid:", mapping)):
        values = [line.split()[1:] for line in raw_status.splitlines() if line.startswith(key)]
        need(values == [[str(value).encode() for value in expected]], "mapped target status/Tgid")
    raw_stat = read(f"/proc/{pid}/stat", 16384)
    end = raw_stat.rfind(b")")
    need(raw_stat.startswith(str(pid).encode() + b" (") and end > 0
         and raw_stat[end + 1:end + 2] == b" " and raw_stat.endswith(b"\n"), "mapped target stat framing")
    values = raw_stat[end + 2:].split()
    need(len(values) == 50 and values[0] not in (b"Z", b"X", b"x")
         and values[19] == baseline[1]["start_ticks"].encode(), "mapped target start identity")
    namespace = os.readlink(f"/proc/{pid}/ns/pid")
    need(namespace == ns("pid") == "pid:[" + baseline[1]["pid_namespace_inode"] + "]",
         "mapped target namespace identity")
    alive(held)
    return {"request_pid": pid, "pidfd_nspid": mapping, "status_pid_tgid": pid,
            "pid_namespace": namespace, "start_ticks": values[19].decode(), "pidfd_live": True}


def root_policy(mount):
    matches = [line.split() for line in read("/proc/self/mountinfo").splitlines()
               if line.split()[:1] == [str(mount).encode()]]
    expect(len(matches) == 1 and matches[0][3:5] == [b"/", b"/proc"]
           and matches[0][matches[0].index(b"-") + 1] == b"proc", "root mount policy witness")


def root_barrier(case, active, held, baseline):
    """Privileged coordinator: kernel witnesses only, never candidate imports.

    An abstract socket in this case's private network namespace carries only a
    fixed readiness/resume exchange, no descriptors or caller-selected operation.
    The helper is already UID 1000/caps-zero and remains subject to _collect's
    unchanged deadline. SO_PEERCRED binds the ready packet to its actual process.
    """
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    old = None
    mounted = False
    stages = (2, 3) if case == "root-barrier-control" else ((2,) if case == "root-between-samples" else (3,))
    records = []
    try:
        listener.bind("\0" + root_address(case, os.getpid()))
        listener.listen(1)
        listener.settimeout(2)
        old = os.open("/proc", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        original = association(old)
        root_policy(original[2])
        for stage in stages:
            send(active[2], "root-second" if stage == 2 else "root-third")
            connection, _ = listener.accept()
            with connection:
                peer_pid, uid, gid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                expect(uid == gid == 1000 and peer_pid > 1, "barrier peer credentials")
                packet = receive(connection)
                expect(packet == {"stage": stage, "pid": peer_pid}, "barrier packet binding")
                helper_status = {line.split(b":", 1)[0]: line.split(b":", 1)[1].split()
                                 for line in read(f"/proc/{peer_pid}/status").splitlines() if b":" in line}
                expect(helper_status[b"PPid"] == [str(active[0]).encode()]
                       and helper_status[b"Tgid"] == [str(peer_pid).encode()]
                       and helper_status[b"NSpid"] == [str(peer_pid).encode()]
                       and helper_status[b"NoNewPrivs"] == [b"1"]
                       and all(int(helper_status[key][0], 16) == 0
                               for key in (b"CapEff", b"CapPrm", b"CapInh", b"CapAmb", b"CapBnd")),
                       "barrier helper privilege/parent/view witness")
                expect(os.readlink(f"/proc/{peer_pid}/ns/mnt") == ns("mnt")
                       and os.readlink(f"/proc/{peer_pid}/ns/pid") == ns("pid"), "barrier namespace witness")
                alive(held)
                if case != "root-barrier-control":
                    checked(libc().mount(b"/proc", b"/proc", None, 4096, None), "whole-root self bind")
                    mounted = True
                new = os.open("/proc", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
                try:
                    current = association(new)
                finally:
                    os.close(new)
                expect(association(old) == original and current[:2] == original[:2], "held root association witness")
                expect((current[2] == original[2]) == (case == "root-barrier-control"), "root mount ID injection witness")
                root_policy(current[2])
                expect(constrained(f"{held[0]}/stat") == 0, "fresh whole-root traversal control")
                expect(connection.send(b"resume") == 6, "barrier release")
            result = receive(active[2], 6)
            alive(held)
            expect(result["witness"] == {"mode": "instrumented exact-source helper qualification"}, "instrumentation label")
            expect(result["observation"] == (baseline if case == "root-barrier-control" else ["unknown", None]),
                   "root barrier observation")
            records.append({"stage": stage, "old_mount": original[2], "new_mount": current[2],
                            "same_device_inode": True, "genuine_procfs": True, "root_policy": True,
                            "held_root_unchanged": True, "fresh_openat2": 0,
                            "peer_uid_gid": [uid, gid], "peer_parent_verified": True,
                            "observation": result["observation"]})
        stable = observation(active)["observation"]
        expect(stable == baseline, "uninstrumented stable whole-root alive control")
        if mounted:
            expect(libc().umount2(b"/proc", 0) == 0, "witnessed root bind removal failed")
            mounted = False
            root_policy(original[2])
            ids = {int(line.split()[0]) for line in read("/proc/self/mountinfo").splitlines()}
            expect(current[2] not in ids, "root overlay not removed")
        restored = observation(active)["observation"]
        expect(restored == baseline, "root after-removal alive control")
        return {"mode": "instrumented exact-source helper qualification", "barriers": records,
                "stable_uninstrumented": stable, "after_removal": restored}, result["observation"]
    finally:
        # Failed injection/control cases are torn down with their disposable
        # namespace. Do not mask their error with a speculative mount cleanup.
        if old is not None:
            os.close(old)
        listener.close()


def run_matrix_case(case, record):
    held = fork_held(target)
    active = None
    try:
        need(receive(held[2]) == "ready", "target readiness")
        pid = held[0]
        need(os.readlink(f"/proc/{pid}/ns/pid") == ns("pid"), "target PID namespace")
        active = fork_held(lambda channel: caller(channel, case, pid))
        ready = receive(active[2])
        record["profile"] = ready["profile"]
        view = ready["view"]
        need(view["self"] == str(view["pid"]) and view["nspid"] == [view["pid"]]
             and view["pid_namespace"] == ns("pid"), "candidate fresh PID view")
        baseline = observation(active)["observation"]
        need(baseline[0] == "alive" and isinstance(baseline[1], dict), "public alive baseline unavailable")
        record["baseline"] = baseline
        alive(held)
        if case in ROOT_CASES:
            witness, result_value = root_barrier(case, active, held, baseline)
            record["injection_witness"] = witness
            result = {"observation": result_value}
        elif case == "fresh-pid":
            record["injection_witness"] = {"fresh_proc": True, "caller_view": view,
                                            "target_same_pid_namespace": True}
            result = observation(active, "thread")
            expect(result["observation"] == baseline, "nonleader alive control")
            record["nonleader_control"] = result
            finish(held)
            held = None
            result = observation(active, "absent")
            expect(result["observation"] == ["absent", None], "reaped recorded identity control")
        elif case.startswith("bind-"):
            paths = {"bind-stat": f"/proc/{pid}/stat", "bind-boot": "/proc/sys/kernel/random/boot_id",
                     "bind-ns": f"/proc/{pid}/ns", "bind-target": f"/proc/{pid}"}
            path = paths[case]
            directory = case in ("bind-ns", "bind-target")
            flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | (os.O_DIRECTORY if directory else 0)
            old = os.open(path, flags)
            try:
                original = association(old)
                need(constrained(path[6:], directory) == 0, "pre-bind constrained traversal")
                checked(libc().mount(path.encode(), path.encode(), None, 4096, None), "same-proc self bind")
                new = os.open(path, flags)
                try:
                    overlay = association(new)
                finally:
                    os.close(new)
                need(original[:2] == overlay[:2] and original[2] != overlay[2]
                     and association(old) == original and constrained(path[6:], directory) == errno.EXDEV,
                     "same-proc bind witness")
                record["injection_witness"] = {"same_device_inode": True, "genuine_procfs": True,
                                                "old_mount": original[2], "new_mount": overlay[2],
                                                "ordinary_open": True, "openat2_errno": errno.EXDEV}
                result = observation(active)
                alive(held)
                expect(result["observation"] == ["unknown", None], "inner bind must refuse")
                # This bind was installed and witnessed: removal failure is a
                # failed qualification, not an unavailable setup facility.
                expect(libc().umount2(path.encode(), 0) == 0, "witnessed bind removal failed")
                ids = {int(line.split()[0]) for line in read("/proc/self/mountinfo").splitlines()}
                expect(overlay[2] not in ids, "overlay mount not removed")
                restored = observation(active)["observation"]
                expect(restored == baseline, "after-removal alive identity control")
                record["after_removal"] = restored
            finally:
                os.close(old)
        elif case.startswith("seccomp-"):
            result = observation(active, "filter")
            record["injection_witness"] = result["witness"]
            alive(held)
            expect(result["observation"] == ["unknown", None], "seccomp must refuse")
        elif case == "ancestor-proc":
            unmount("/proc")  # Only the nested coordinator's fresh proc overlay.
            target_witness = ancestor_target(held, baseline)
            # Only the numeric PID derived from the held target is transmitted;
            # the candidate caller receives no privileged descriptor or path.
            result = observation(active, {"command": "ancestor", "pid": target_witness["request_pid"]})
            need(result["witness"]["pid_ns"] == view["pid_namespace"]
                 and result["witness"]["pid_ns"] != record["ancestor_pid_namespace"]
                 and result["witness"]["request_pid"] == target_witness["request_pid"],
                 "nested versus ancestor PID namespace")
            record["injection_witness"] = result["witness"]
            record["injection_witness"]["target_binding"] = target_witness
            need(ancestor_target(held, baseline) == target_witness, "ancestor target binding changed")
            alive(held)
            expect(result["observation"] == ["unknown", None], "ancestor proc must refuse")
            proc_mount()
            # The per-command override never changes the caller's original PID.
            restored = observation(active)["observation"]
            expect(restored == baseline, "restored matching proc alive control")
            record["after_removal"] = restored
        else:
            finish(active)
            active = None
            original_time = ns("time")
            if case in OFFSETS:
                if case == "time-boot-negative":
                    need(float(read("/proc/uptime", 128).split()[0]) > 2, "negative offset uptime")
                unshare(NEWTIME)
                set_offsets(OFFSETS[case])
            active = fork_held(lambda channel: caller(channel, case, pid, case))
            ready = receive(active[2])
            witness = ready["witness"]
            if case in OFFSETS:
                need(witness["current"] != original_time, "noninitial time namespace witness")
            record["injection_witness"] = witness
            result = observation(active)
            alive(held)
            expect(result["observation"] == (baseline if case == "time-zero" else ["unknown", None]),
                   "namespace observation mismatch")
        record["observation"] = result["observation"]
        record["status"] = "VERIFIED"
    finally:
        try:
            if active:
                finish(active)
        finally:
            if held:
                finish(held)


def fresh_view(parent_ns):
    need(os.getpid() == 1 and ns("pid") != parent_ns, "disposable PID namespace")
    need(os.readlink("/proc/self") == "1" and status()["NSpid"] == [b"1"], "fresh proc PID view")
    fd = os.open("/proc", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        mount_id = association(fd)[2]
    finally:
        os.close(fd)
    matches = [line.split() for line in read("/proc/self/mountinfo").splitlines()
               if line.split()[0] == str(mount_id).encode()]
    need(len(matches) == 1 and matches[0][3:5] == [b"/", b"/proc"]
         and matches[0][matches[0].index(b"-") + 1] == b"proc", "fresh proc root witness")


def reap_namespace():
    """Called only by verified disposable PID 1; never by the original guest."""
    try:
        os.kill(-1, signal.SIGKILL)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return True
        if pid == 0:
            time.sleep(.01)
    return False


def namespace_init(channel, case, record, original):
    verified_init = False
    try:
        need(os.getpid() == 1 and ns("pid") != original["pid"]
             and ns("mnt") != original["mnt"] and ns("net") != original["net"], "namespace isolation")
        verified_init = True
        private_mounts()
        proc_mount()
        fresh_view(original["pid"])
        if case == "ancestor-proc":
            ancestor = ns("pid")
            unshare(NEWPID)

            def nested(child):
                # Keep the disposable ancestor proc underneath a fresh baseline.
                proc_mount()
                fresh_view(ancestor)
                record["ancestor_pid_namespace"] = ancestor
                run_matrix_case(case, record)
                send(child, record)

            worker = fork_held(nested)
            try:
                record = receive(worker[2], CASE_SECONDS)
            finally:
                finish(worker)
        else:
            run_matrix_case(case, record)
    except BaseException as error:
        record["status"] = error_status(error)
        record["reason"] = str(error)[:160] if isinstance(error, (Failed, Unqualified)) else type(error).__name__
    finally:
        try:
            clean = verified_init and reap_namespace()
        except BaseException:
            clean = False
        record["cleanup"] = "reaped" if clean else "FAILED"
        if not clean:
            record["status"] = "FAILED"
        send(channel, record)


def launcher(channel, case, record, original):
    unshare(NEWNS | NEWPID | NEWNET)
    # Init is gated until the outer supervisor has received its stable pidfd.
    ready_read, ready_write = os.pipe()
    try:
        pid = os.fork()
    except BaseException:
        try:
            os.close(ready_read)
        finally:
            os.close(ready_write)
        raise
    if pid == 0:
        os.close(ready_write)
        need(select.select([ready_read], [], [], 2)[0] and os.read(ready_read, 1) == b"G", "init gate")
        os.close(ready_read)
        namespace_init(channel, case, record, original)
        os._exit(0)
    os.close(ready_read)
    try:
        pidfd = os.pidfd_open(pid)
    except BaseException:
        try:
            os.close(ready_write)
        finally:
            stop_unadmitted(pid, time.monotonic() + 2)
        raise Unqualified("namespace-init pidfd unavailable; gated child reaped")
    reaped = False
    try:
        channel.sendmsg([b"init"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [pidfd]))])
        need(receive(channel) == "retained", "outer pidfd receipt")
        os.write(ready_write, b"G")
        os.close(ready_write)
        ready_write = None
        deadline = time.monotonic() + CASE_SECONDS + CLEANUP_SECONDS
        while time.monotonic() < deadline:
            if os.waitpid(pid, os.WNOHANG)[0] == pid:
                reaped = True
                return
            time.sleep(.01)
    finally:
        try:
            try:
                if ready_write is not None:
                    os.close(ready_write)
            finally:
                if not reaped:
                    expect(stop(pid, pidfd, time.monotonic() + 2), "launcher init reap deadline")
        finally:
            os.close(pidfd)


def record_for(case):
    return {"case": case, "profile": None, "baseline": None, "injection_witness": None,
            "observation": None, "cleanup": "not-started", "status": "UNQUALIFIED", "backend_qualified": False}


def outer_case(case, total_deadline):
    record = record_for(case)
    deadline = min(time.monotonic() + CASE_SECONDS, total_deadline - CLEANUP_SECONDS)
    original = {name: ns(name) for name in ("mnt", "pid", "net")}
    worker = fork_held(lambda channel: launcher(channel, case, record, original))
    initfd = None
    try:
        channel = worker[2]
        channel.settimeout(2)
        raw, ancillary, flags, _ = channel.recvmsg(PACKET_LIMIT, socket.CMSG_SPACE(4))
        if raw != b"init":
            value = json.loads(raw)
            kind = Failed if value.get("exception") == "FAILED" else Unqualified
            raise kind(value.get("reason", "namespace launcher unavailable"))
        need(not flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) and len(ancillary) == 1,
             "namespace-init pidfd transfer")
        level, kind, data = ancillary[0]
        need(level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS and len(data) == 4, "pidfd shape")
        initfd = array.array("i", data)[0]
        os.set_inheritable(initfd, False)
        send(channel, "retained")
        remaining = deadline - time.monotonic()
        expect(remaining > 0, "case deadline")
        record = receive(channel, remaining)
        expect(time.monotonic() <= deadline, "case deadline")
    except BaseException as error:
        record["status"] = error_status(error)
        record["reason"] = str(error)[:160] if isinstance(error, (Failed, Unqualified)) else type(error).__name__
    finally:
        cleanup = min(time.monotonic() + CLEANUP_SECONDS, total_deadline)
        clean = True
        try:
            if initfd is not None:
                try:
                    if not exited(initfd):
                        try:
                            signal.pidfd_send_signal(initfd, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    clean = bool(select.select([initfd], [], [], max(0, cleanup - time.monotonic()))[0])
                finally:
                    os.close(initfd)
        except BaseException:
            clean = False
        finally:
            # Give the launcher time to reap PID 1 before reaping the launcher.
            # A cleanup error must not skip the remaining owned child/handles.
            launcher_reaped = False
            try:
                launcher_reaped = reap(worker[0], worker[1], cleanup - .5)
            except BaseException:
                clean = False
            finally:
                try:
                    if not launcher_reaped:
                        stop(worker[0], worker[1], cleanup)
                except BaseException:
                    clean = False
                finally:
                    try:
                        os.close(worker[1])
                    except BaseException:
                        clean = False
                    finally:
                        try:
                            worker[2].close()
                        except BaseException:
                            clean = False
            clean = launcher_reaped and clean
        record["outer_cleanup"] = "init-exited-launcher-reaped" if clean and initfd is not None else "FAILED"
        if not clean or initfd is None:
            record["status"] = "FAILED" if not clean else "UNQUALIFIED"
    return record


def main():
    # Set before every output path, including failed admission. This only avoids
    # pipe backpressure; the required external watchdog covers blocking I/O too.
    try:
        os.set_blocking(sys.stdout.fileno(), False)
    except (OSError, ValueError):
        return 1
    if sys.argv[1:] not in (["--qualify-disposable-guest"], ["--qualify-root-replacement"]):
        try:
            os.write(sys.stdout.fileno(), b"Guest-only opt-in: --qualify-disposable-guest or --qualify-root-replacement; no default execution.\n")
        except OSError:
            return 1
        return 3
    started = time.monotonic()
    total_deadline = started + TOTAL_SECONDS
    try:
        need(sys.flags.isolated and sys.dont_write_bytecode, "invoke Python with -I -B")
        need(platform.system() == "Linux" and platform.machine() == "aarch64"
             and os.geteuid() == 0 and os.path.isabs(sys.executable), "guest setup profile")
        need(sys.byteorder == "little" and c.sizeof(c.c_long) == c.sizeof(c.c_void_p) == 8
             and c.sizeof(StatFS) == 120, "setup witness ABI")
        need(hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"), "stable pidfd support")
        # Only the explicitly acknowledged guest may supply local setup authority.
        # Reject common host-share filesystems, without pretending this proves isolation.
        filesystems = [row.split(b" - ", 1)[1].split()[0]
                       for row in read("/proc/self/mountinfo").splitlines()]
        need(not set(filesystems) & {b"9p", b"virtiofs", b"nfs", b"nfs4", b"cifs", b"fuse.sshfs"},
             "host-share filesystem present")

        # No candidate imports here. Each already-contained caller admits this
        # interpreter via probe.profile() after dropping privilege, before baseline.
    except BaseException as error:
        record = record_for("preflight")
        record["status"] = error_status(error)
        record["reason"] = str(error)[:160] if isinstance(error, (Failed, Unqualified)) else type(error).__name__
        try:
            emit(record)
        except (OSError, Failed):
            return 1
        return 1 if record["status"] == "FAILED" else 3
    records = []
    size = 0
    selected = ROOT_CASES if sys.argv[1:] == ["--qualify-root-replacement"] else (*CASES, *ROOT_CASES)
    for case in selected:
        if time.monotonic() + CASE_SECONDS + CLEANUP_SECONDS > total_deadline:
            record = record_for(case)
            record["reason"] = "total run budget exhausted"
        else:
            try:
                record = outer_case(case, total_deadline)
            except BaseException as error:
                # A failure before handles reach outer_case still stops admission;
                # external supervision must confirm teardown before another run.
                record = record_for(case)
                record["status"] = "FAILED"
                record["outer_cleanup"] = "FAILED"
                record["reason"] = "case supervisor failure: " + type(error).__name__
        try:
            size = emit(record, size)
        except (OSError, Failed):
            return 1
        records.append(record)
        if record.get("outer_cleanup") == "FAILED":
            break  # Never start another case after unverified namespace teardown.
    if any(item["status"] == "FAILED" for item in records):
        return 1
    return 0 if len(records) == len(selected) and all(item["status"] == "VERIFIED" for item in records) else 3


def emit(record, size=0):
    encoded = (json.dumps(record, sort_keys=True) + "\n").encode()
    expect(len(encoded) <= PACKET_LIMIT and size + len(encoded) <= OUTPUT_LIMIT, "evidence output limit")
    expect(os.write(sys.stdout.fileno(), encoded) == len(encoded), "short evidence output")
    return size + len(encoded)


if __name__ == "__main__":
    sys.exit(main())
