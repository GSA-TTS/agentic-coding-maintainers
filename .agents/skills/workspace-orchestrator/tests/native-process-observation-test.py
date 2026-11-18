"""Offline refusals by default; --qualify runs actual lifecycle cases in a guest.

Qualification is opt-in and reports unavailable capabilities explicitly. Never
run these tests on the maintainer host; no test hooks enter production code.
"""

import base64
import copy
import ctypes
import errno
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load("native_probe_test", BIN / "native-process-observation.py")
observer = load("native_observer_test", BIN / "runtime-observation.py")
CONTEXT = {"boot_id": "01234567-89ab-cdef-0123-456789abcdef", "pid_namespace_inode": "4026531836"}
IDENTITY = {"schema_version": 1, "backend": "linux-procfs", **CONTEXT, "start_ticks": "12345"}
REQUEST = {"version": 1, "pid": 42, "caller_tgid": 24, "caller_tid": 25, "expected_context": CONTEXT}


def reply(status="alive"):
    return {"version": 1, "pid": 42, "caller_tgid": 24, "caller_tid": 25, "status": status,
            "context": None if status == "unknown" else CONTEXT,
            "identity": IDENTITY if status == "alive" else None}


def stat_bytes(comm=b"normal", ticks=b"12345"):
    fields = [b"S"] + [b"0"] * 49
    fields[19] = ticks
    return b"42 (" + comm + b") " + b" ".join(fields) + b"\n"


class ParserTests(unittest.TestCase):
    def test_profile_admits_only_complete_measured_tuples(self):
        admitted = {("6.12.113", "3.12.16", b"2.36"), ("6.8.0-147-generic", "3.12.3", b"2.39")}
        tuples = list(itertools.product(("6.12.113", "6.8.0-147-generic"),
                                        ("3.12.16", "3.12.3"), (b"2.36", b"2.39")))
        tuples.extend((("unknown", "3.12.3", b"2.39"), ("6.12.113", "3.12.16", b"2.40")))
        for kernel, python, glibc in tuples:
            lib = mock.Mock()
            lib.gnu_get_libc_version.return_value = glibc
            with self.subTest(kernel=kernel, python=python, glibc=glibc), \
                    mock.patch.object(probe.platform, "system", return_value="Linux"), \
                    mock.patch.object(probe.platform, "machine", return_value="aarch64"), \
                    mock.patch.object(probe.platform, "python_implementation", return_value="CPython"), \
                    mock.patch.object(probe.platform, "release", return_value=kernel), \
                    mock.patch.object(probe.platform, "python_version", return_value=python), \
                    mock.patch.object(probe.sys, "byteorder", "little"), \
                    mock.patch.object(probe.os, "O_PATH", 0o10000000, create=True), \
                    mock.patch.object(probe.os, "O_NOFOLLOW", 0o100000), \
                    mock.patch.object(probe.os, "O_CLOEXEC", 0o2000000), \
                    mock.patch.object(probe.os, "O_DIRECTORY", 0o40000), \
                    mock.patch.object(probe.c, "CDLL", return_value=lib):
                if (kernel, python, glibc) in admitted:
                    self.assertIs(probe.profile(), lib)
                else:
                    with self.assertRaisesRegex(probe.Unknown, "unqualified kernel/interpreter/libc tuple"):
                        probe.profile()

    def test_comm_is_bytes_and_final_parenthesis_delimits(self):
        for comm in (b"ordinary", b"a b)(c\n\xff", b")))))", b"(nested)"):
            self.assertEqual(probe.start_ticks(stat_bytes(comm), 42), "12345")
        for raw in (stat_bytes()[:-1], stat_bytes().replace(b"42 (", b"43 ("),
                    stat_bytes() + b"extra", b"42 (x) S 1\n", stat_bytes(b"x" * 17000)):
            with self.assertRaises(probe.Unknown):
                probe.start_ticks(raw, 42)

    def test_exact_identity_and_numeric_bounds(self):
        self.assertTrue(observer.valid_native_identity(IDENTITY))
        for key, value in (("schema_version", True), ("schema_version", 2), ("backend", "ps"),
                           ("extra", None), ("boot_id", CONTEXT["boot_id"].upper()),
                           ("pid_namespace_inode", "0"), ("start_ticks", 1), ("start_ticks", "01"),
                           ("start_ticks", str(2**64)), ("start_ticks", "-1")):
            self.assertFalse(observer.valid_native_identity({**IDENTITY, key: value}))
        for value in (b"01", b"-1", b"+1", b"18446744073709551616", b"1.0"):
            with self.assertRaises(probe.Unknown):
                probe.start_ticks(stat_bytes(ticks=value), 42)

    def test_namespace_view_and_offsets(self):
        probe.status_view(b"Pid:\t25\nTgid:\t24\nNSpid:\t25\n", 25, 24)
        for raw in (b"Pid:\t25\nTgid:\t24\nNSpid:\t25 25\n", b"NSpid:\t25\n",
                    b"Pid:\t25\nTgid:\t25\nNSpid:\t25\n"):
            with self.assertRaises(probe.Unknown):
                probe.status_view(raw, 25, 24)
        for raw in (b"pid:[0]", b"pid:[01]", b"time:[3]", b"pid:[3]\n"):
            with self.assertRaises(probe.Unknown):
                probe.namespace(raw, "pid")
        probe.zero_offsets(b"monotonic 0 0\nboottime 0 0\n")
        for value in (b"1 0", b"-1 0", b"0 1", b"0 000"):
            with self.assertRaises(probe.Unknown):
                probe.zero_offsets(b"monotonic 0 0\nboottime " + value + b"\n")

    def test_wire_request_and_response_are_exact(self):
        self.assertEqual(probe.request_value(json.dumps(REQUEST)), REQUEST)
        for status in ("alive", "absent", "unknown"):
            self.assertEqual(observer._reply(json.dumps(reply(status)).encode(), REQUEST),
                             (status, IDENTITY if status == "alive" else None))
        for key, value in (("version", True), ("pid", 43), ("caller_tid", 24), ("caller_tgid", True),
                           ("extra", 1), ("identity", None), ("context", None), ("status", [])):
            with self.assertRaises(observer.NativeUnknown):
                observer._reply(json.dumps({**reply(), key: value}).encode(), REQUEST)
        for raw in (b'{"version":1,' + json.dumps(reply()).encode()[1:],
                    json.dumps(reply()).encode() + b"x", b" " * 4097):
            with self.assertRaises((observer.NativeUnknown, ValueError)):
                observer._reply(raw, REQUEST)
        for raw in ('{"version":1,' + json.dumps(REQUEST)[1:], json.dumps(REQUEST) + "x",
                    json.dumps({**REQUEST, "caller_tid": True}), " " * 4097):
            with self.assertRaises((probe.Unknown, ValueError)):
                probe.request_value(raw)
        wrong = {**REQUEST, "expected_context": {**CONTEXT, "pid_namespace_inode": "4"}}
        for status in ("alive", "absent"):
            with self.assertRaises(observer.NativeUnknown):
                observer._reply(json.dumps(reply(status)).encode(), wrong)
        for raw in (json.dumps({**reply("absent"), "identity": IDENTITY}),
                    json.dumps({**reply("unknown"), "context": CONTEXT})):
            with self.assertRaises(observer.NativeUnknown):
                observer._reply(raw.encode(), REQUEST)

    def test_native_never_falls_back_and_record_selects_backend(self):
        with mock.patch.object(observer, "process_identity", return_value=("alive", "one\ntwo")) as legacy:
            self.assertEqual(observer.observe_worker_process({"pid": 42, "process_start": "arbitrary"},
                             environment={"PATH": "/x"}), ("alive", "one\ntwo"))
            legacy.assert_called_once_with(42, environment={"PATH": "/x"})
            legacy.reset_mock()
            with mock.patch.object(observer, "_native_observation", return_value=("unknown", None)) as native:
                self.assertEqual(observer.observe_worker_process({"pid": 42, "process_identity": IDENTITY}),
                                 ("unknown", None))
                native.assert_called_once_with(42, CONTEXT)
            legacy.assert_not_called()
        for worker in ({"pid": 42}, {"pid": True, "process_identity": IDENTITY},
                       {"pid": 42, "process_identity": IDENTITY, "process_start": "x"}):
            self.assertEqual(observer.observe_worker_process(worker), ("unknown", None))

    def test_bounded_reads_and_syscall_errors(self):
        with mock.patch.object(probe.os, "read", return_value=b"x") as read:
            with self.assertRaisesRegex(probe.Unknown, "call limit"):
                probe.Proc.read_fd(0, 65536)
            self.assertEqual(read.call_count, 64)
        with mock.patch.object(probe.os, "read", return_value=b"x" * 65):
            with self.assertRaisesRegex(probe.Unknown, "byte limit"):
                probe.Proc.read_fd(0, 64)
        proc = object.__new__(probe.Proc)
        proc.root, proc.libc = 9, mock.Mock()
        proc.libc.syscall.return_value = -1
        for error in (errno.ENOSYS, errno.EPERM, errno.EXDEV):
            with mock.patch.object(probe.c, "get_errno", return_value=error):
                with self.assertRaises(OSError) as caught:
                    proc.open("42/stat", 0)
                self.assertEqual(caught.exception.errno, error)
        self.assertEqual(proc.libc.syscall.call_count, 3)


class RaceTests(unittest.TestCase):
    def test_context_offsets_are_from_proven_shared_helper_namespace(self):
        def context_probe(mismatched=False, offsets=b"monotonic 0 0\nboottime 0 0\n"):
            proc = object.__new__(probe.Proc)
            proc.root_identity = (1, 1, 0o40555, "3")
            reads = []

            def read(path, limit=65536):
                reads.append(path)
                if path.endswith("/stat"):
                    pid = 100 if path.startswith("100/") else 25
                    return stat_bytes().replace(b"42 (", str(pid).encode() + b" (")
                if path.endswith("/status"):
                    return (b"Pid: 100\nTgid: 100\nNSpid: 100\n" if path.startswith("100/")
                            else b"Pid: 25\nTgid: 24\nNSpid: 25\n")
                if path == "100/timens_offsets":
                    return offsets
                if path == "sys/kernel/random/boot_id":
                    return CONTEXT["boot_id"].encode() + b"\n"
                if path == "100/mountinfo":
                    return b"3 1 0:1 / /proc rw - proc proc rw\n"
                raise AssertionError(f"unexpected proc read: {path}")

            def link(path):
                if path == "self":
                    return b"100"
                if path == "thread-self":
                    return b"100/task/100"
                name = path.rsplit("/", 1)[1]
                if name.startswith("pid"):
                    return b"pid:[4026531836]"
                return b"time:[5]" if mismatched and path.startswith("24/task/25/") else b"time:[4]"

            proc.read, proc.link = mock.Mock(side_effect=read), mock.Mock(side_effect=link)
            return proc, reads

        with mock.patch.object(probe.os, "getpid", return_value=100), \
                mock.patch.object(probe.os, "getppid", return_value=24):
            proc, reads = context_probe()
            self.assertEqual(proc.context(REQUEST)[0], CONTEXT)
            self.assertEqual([path for path in reads if path.endswith("timens_offsets")], ["100/timens_offsets"])
            proc.link.assert_any_call("24/task/25/ns/time")
            proc.link.assert_any_call("24/task/25/ns/time_for_children")
            proc, reads = context_probe(mismatched=True)
            with self.assertRaisesRegex(probe.Unknown, "caller/helper namespaces"):
                proc.context(REQUEST)
            self.assertFalse(any(path.endswith("timens_offsets") for path in reads))
            proc, _ = context_probe(offsets=b"monotonic 0 0\nboottime 0 1\n")
            with self.assertRaisesRegex(probe.Unknown, "time offsets"):
                proc.context(REQUEST)

    def sample(self):
        proc = mock.Mock()
        proc.context.return_value = (CONTEXT, ("namespace", "helper ticks", "caller ticks"))
        proc.target.return_value = ("12345", CONTEXT["pid_namespace_inode"])
        return proc

    def test_absence_order_and_opened_disappearance(self):
        first, second = self.sample(), self.sample()
        with mock.patch.object(probe, "Proc", side_effect=[first, second]), \
                mock.patch.object(probe, "missing", side_effect=[True, True]) as missing, \
                mock.patch.object(probe, "no_process", return_value=True):
            self.assertEqual(probe.observe(REQUEST, None)["status"], "absent")
            self.assertEqual(missing.call_count, 2)
            first.target.assert_not_called()
            first.same_sources.assert_called_once_with(second)
        first = self.sample()
        first.target.side_effect = FileNotFoundError(errno.ENOENT, "exited after open")
        with mock.patch.object(probe, "Proc", return_value=first), \
                mock.patch.object(probe, "missing", return_value=False), \
                mock.patch.object(probe, "no_process") as kill:
            with self.assertRaises(FileNotFoundError):
                probe.observe(REQUEST, None)
            kill.assert_not_called()

    def test_context_failure_precedes_absence_and_torn_sample_refuses(self):
        first = self.sample()
        first.context.side_effect = probe.Unknown("recorded context mismatch")
        with mock.patch.object(probe, "Proc", return_value=first), mock.patch.object(probe, "missing") as lookup:
            with self.assertRaises(probe.Unknown):
                probe.observe(REQUEST, None)
            lookup.assert_not_called()
        for change in ("ticks", "context", "association"):
            first, second = self.sample(), self.sample()
            if change == "ticks":
                second.target.return_value = ("12346", CONTEXT["pid_namespace_inode"])
            elif change == "context":
                second.context.return_value = ({**CONTEXT, "pid_namespace_inode": "4"}, None)
            else:
                first.same_sources.side_effect = probe.Unknown("replaced mount")
            with mock.patch.object(probe, "Proc", side_effect=[first, second]), \
                    mock.patch.object(probe, "missing", return_value=False):
                with self.assertRaises(probe.Unknown):
                    probe.observe(REQUEST, None)

    def test_only_initial_open_enoent_is_missing(self):
        proc = mock.Mock()
        proc.open.side_effect = FileNotFoundError(errno.ENOENT, "directory missing")
        self.assertTrue(probe.missing(proc, 42))
        proc.open.side_effect = None
        proc.retain.side_effect = FileNotFoundError(errno.ENOENT, "fdinfo vanished")
        with self.assertRaises(FileNotFoundError):
            probe.missing(proc, 42)
        for error in (errno.EPERM, errno.EACCES):
            with mock.patch.object(probe.os, "kill", side_effect=OSError(error, "permission")):
                with self.assertRaises(OSError):
                    probe.no_process(42)

    def test_final_association_uses_a_fresh_root_and_rejects_replacement(self):
        first = object.__new__(probe.Proc)
        first.libc, first.root = None, 10
        identity = (1, 2, 0o100444, "3")
        first.root_identity = (1, 1, 0o40555, "3")
        first.sources = {"42/stat": (11, identity)}
        first.association = mock.Mock(side_effect=lambda fd: first.root_identity if fd == 10 else identity)
        second = mock.Mock(root=20, root_identity=first.root_identity, sources={"42/stat": (21, identity)})
        second.association.side_effect = lambda fd: first.root_identity if fd == 20 else identity
        fresh = mock.Mock(root_identity=first.root_identity, sources={"42/stat": (31, identity)})
        with mock.patch.object(probe, "Proc", return_value=fresh) as constructor:
            first.same_sources(second)
            constructor.assert_called_once_with(None)
            fresh.source.assert_called_once_with("42/stat", os.O_RDONLY)
            fresh.close.assert_called_once()
        for changed in ((1, 2, 0o100444, "4"), (1, 3, 0o100444, "3")):
            fresh = mock.Mock(root_identity=first.root_identity, sources={"42/stat": (31, changed)})
            with mock.patch.object(probe, "Proc", return_value=fresh):
                with self.assertRaisesRegex(probe.Unknown, "final source replacement"):
                    first.same_sources(second)


class ParentTests(unittest.TestCase):
    def test_launch_binds_calling_thread_and_ignores_environment(self):
        captured = []

        def collect(command):
            captured.append(command)
            request = json.loads(command[-1])
            self.assertEqual(request, REQUEST)
            return json.dumps(reply()).encode()

        with mock.patch.object(observer.sys, "platform", "linux"), \
                mock.patch.object(observer, "_trusted_helper", return_value=(BIN / "native-process-observation.py", b"snapshot")), \
                mock.patch.object(observer.os, "getpid", return_value=24), \
                mock.patch.object(observer.threading, "get_native_id", return_value=25), \
                mock.patch.object(observer, "_collect", side_effect=collect), \
                mock.patch.object(observer, "process_identity") as legacy:
            self.assertEqual(observer.observe_worker_process({"pid": 42, "process_identity": IDENTITY},
                             environment={"PYTHONPATH": "/untrusted", "PATH": "/untrusted"}), ("alive", IDENTITY))
            self.assertEqual(captured[0][:-1], [sys.executable, "-I", "-B", "-c", observer._NATIVE_BOOTSTRAP,
                                              base64.b64encode(b"snapshot").decode(), str(BIN / "native-process-observation.py")])
            legacy.assert_not_called()

    def test_actual_collection_failure_modes_and_cleanup(self):
        children = []
        original = subprocess.Popen

        def spawn(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child

        with mock.patch.object(observer.subprocess, "Popen", side_effect=spawn):
            self.assertEqual(observer._collect([sys.executable, "-I", "-B", "-c", "print('ok')"]), b"ok\n")
            for code, message in (("print('x'*10000)", "output limit"),
                                  ("import sys;sys.stderr.write('x'*10000)", "output limit"),
                                  ("import sys;sys.stderr.write('bad')", "exit/stderr"),
                                  ("raise SystemExit(7)", "exit/stderr"),
                                  ("import os,signal;os.kill(os.getpid(),signal.SIGSTOP)", "deadline"),
                                  ("import time;time.sleep(60)", "deadline")):
                start = time.monotonic()
                with self.assertRaisesRegex(observer.NativeUnknown, message):
                    observer._collect([sys.executable, "-I", "-B", "-c", code])
                self.assertLess(time.monotonic() - start, 5)
                self.assertIsNotNone(children[-1].poll(), "direct helper was not reaped")
            with self.assertRaises(subprocess.TimeoutExpired):
                observer._collect([sys.executable, "-I", "-B", "-c",
                                   "import os,time;os.close(1);os.close(2);time.sleep(60)"])
            self.assertIsNotNone(children[-1].poll(), "closed-pipe child was not reaped")

    def test_final_wait_deadline_and_cleanup_timeout_map_to_unknown(self):
        # Deterministic clock/child doubles place expiry exactly at final wait,
        # and separately demonstrate bounded cleanup without claiming reaping.
        for cleanup_timeout in (False, True):
            child = mock.Mock()
            child.poll.return_value = None if cleanup_timeout else 0
            child.wait.side_effect = subprocess.TimeoutExpired("helper", 1) if cleanup_timeout else None
            child.wait.return_value = 0
            selector = mock.MagicMock()
            selector.__enter__.return_value.get_map.return_value = {}
            with mock.patch.object(observer.sys, "platform", "linux"), \
                    mock.patch.object(observer, "_trusted_helper", return_value=(BIN / "native-process-observation.py", b"pass")), \
                    mock.patch.object(observer.subprocess, "Popen", return_value=child), \
                    mock.patch.object(observer.selectors, "DefaultSelector", return_value=selector), \
                    mock.patch.object(observer.time, "monotonic", side_effect=[0, 2, 4]):
                self.assertEqual(observer.native_process_identity(42), ("unknown", None))
            child.stdout.close.assert_called_once()
            child.stderr.close.assert_called_once()
            if cleanup_timeout:
                self.assertEqual(child.wait.call_args_list, [mock.call(timeout=1), mock.call(timeout=1)])
                child.kill.assert_called_once()
                self.assertIsNone(child.poll(), "fixture must leave cleanup unresolved")
            else:
                child.wait.assert_called_once_with(timeout=1)

    def test_partial_reply_and_launch_failure_are_unknown(self):
        original = observer._collect
        with mock.patch.object(observer.sys, "platform", "linux"), \
                mock.patch.object(observer, "_trusted_helper", return_value=(BIN / "native-process-observation.py", b"pass")):
            with mock.patch.object(observer.subprocess, "Popen", side_effect=OSError("launch failed")):
                self.assertEqual(observer.native_process_identity(42), ("unknown", None))
            with mock.patch.object(observer, "_collect", side_effect=lambda command: original(
                    [sys.executable, "-I", "-B", "-c", "print('{\"version\":1,')"])):
                self.assertEqual(observer.native_process_identity(42), ("unknown", None))

    def test_verified_snapshot_executes_despite_post_verification_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory)
            (skill / "bin").mkdir()
            copied_path = skill / "bin/runtime-observation.py"
            shutil.copyfile(BIN / "runtime-observation.py", copied_path)
            copied = load("snapshot_race_test", copied_path)
            helper = skill / "bin/native-process-observation.py"
            marker = skill / "substituted-executed"
            # Trusted synthetic fixture proves execution of verified bytes,
            # __file__/argv preservation, direct parent and calling-thread wire.
            source = ("import json,os,sys\n"
                      "r=json.loads(sys.argv[1])\n"
                      "assert __file__ == sys.argv[0]\n"
                      "assert os.getppid() == r['caller_tgid']\n"
                      "assert r['caller_tid'] > 0\n"
                      f"i={IDENTITY!r}\n"
                      f"c={CONTEXT!r}\n"
                      "print(json.dumps({**{k:r[k] for k in ('version','pid','caller_tgid','caller_tid')},"
                      "'status':'alive','context':c,'identity':i}))\n").encode()
            helper.write_bytes(source)
            (skill / "CANONICAL-SHA256SUMS").write_text(
                hashlib.sha256(source).hexdigest() + "  ./bin/native-process-observation.py\n")
            original = copied._collect

            def replace_then_launch(command):
                helper.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise SystemExit(9)\n")
                return original(command)

            with mock.patch.object(copied.sys, "platform", "linux"), \
                    mock.patch.object(copied, "_collect", side_effect=replace_then_launch):
                self.assertEqual(copied.native_process_identity(42), ("alive", IDENTITY))
            self.assertFalse(marker.exists(), "unverified replacement executed")
            with self.assertRaises(copied.NativeUnknown):
                copied._trusted_helper()

    def test_fifo_substitution_refuses_under_external_watchdog(self):
        for which in ("helper", "manifest"):
            with self.subTest(which=which), tempfile.TemporaryDirectory() as directory:
                skill = Path(directory)
                (skill / "bin").mkdir()
                copied = skill / "bin/runtime-observation.py"
                shutil.copyfile(BIN / "runtime-observation.py", copied)
                helper = skill / "bin/native-process-observation.py"
                manifest = skill / "CANONICAL-SHA256SUMS"
                marker = skill / "executed"
                source = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n".encode()
                helper.write_bytes(source)
                manifest.write_text(hashlib.sha256(source).hexdigest() + "  ./bin/native-process-observation.py\n")
                target = helper if which == "helper" else manifest
                target.unlink()
                os.mkfifo(target)
                code = ("import importlib.util,sys;"
                        f"s=importlib.util.spec_from_file_location('fifo_test',{str(copied)!r});"
                        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                        "sys.platform='linux';"
                        "assert m.native_process_identity(42)==('unknown',None);print('FIFO_REFUSED')")
                result = subprocess.run([sys.executable, "-I", "-B", "-c", code],
                                        capture_output=True, check=True, timeout=5)
                self.assertEqual(result.stdout, b"FIFO_REFUSED\n")
                self.assertEqual(result.stderr, b"")
                self.assertFalse(marker.exists())

    def test_copied_installation_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "skill"
            shutil.copytree(BIN.parent, skill, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            copied = load("native_copied_test", skill / "bin/runtime-observation.py")
            helper = skill / "bin/native-process-observation.py"
            original = helper.read_bytes()
            self.assertEqual(copied._trusted_helper(), (helper, original))
            helper.write_bytes(original + b"\n# changed\n")
            with self.assertRaises(copied.NativeUnknown):
                copied._trusted_helper()
            helper.unlink()
            with self.assertRaises(OSError):
                copied._trusted_helper()


def qualify():
    """Actual guest lifecycle, comm and copied-installation assertions."""
    try:
        probe.profile()
    except (probe.Unknown, AttributeError) as error:
        print(json.dumps({"status": "UNQUALIFIED", "backend_qualified": False, "reason": str(error)}))
        return 3
    # Child is held unreaped with waitid(WNOWAIT), not Popen.poll/wait.
    ready_read, ready_write = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(ready_read)
        libc = ctypes.CDLL(None)
        if libc.prctl(15, ctypes.c_char_p(b"a ) (\n\xff"), 0, 0, 0) != 0:
            os._exit(1)
        os.write(ready_write, b"R")
        os.close(ready_write)
        time.sleep(60)
        os._exit(0)
    os.close(ready_write)
    reaped = False
    try:
        import select
        assert select.select([ready_read], [], [], 3)[0], "comm setup deadline"
        assert os.read(ready_read, 1) == b"R", "comm setup failed"
        os.close(ready_read)
        ready_read = None
        status, identity = observer.native_process_identity(pid)
        assert status == "alive" and observer.valid_native_identity(identity), (status, identity)
        assert observer.native_process_identity(pid) == (status, identity)
        own = observer.native_process_identity(os.getpid())
        assert own[0] == "alive" and observer.valid_native_identity(own[1]), own
        thread_results = []

        def from_thread():
            thread_results.append((threading.get_native_id(), observer.native_process_identity(pid),
                                   observer.native_process_identity(os.getpid())))

        thread = threading.Thread(target=from_thread, daemon=True)
        thread.start()
        thread.join(timeout=10)
        assert not thread.is_alive() and len(thread_results) == 1, "nonleader caller deadline"
        tid, child_observation, own_observation = thread_results[0]
        assert tid != os.getpid(), "nonleader caller fixture"
        assert child_observation == (status, identity), child_observation
        assert own_observation == own, own_observation
        worker = {"pid": pid, "process_identity": identity}
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "skill"
            shutil.copytree(BIN.parent, skill, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            copied = load("native_live_copy", skill / "bin/runtime-observation.py")
            assert copied.observe_worker_process(worker) == (status, identity)
        os.kill(pid, signal.SIGKILL)
        os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT)
        assert observer.observe_worker_process(worker)[0] in ("alive", "unknown"), "zombie became absent"
        os.waitpid(pid, 0)
        reaped = True
        assert observer.observe_worker_process(worker) == ("absent", None)
        wrong = copy.deepcopy(worker)
        wrong["process_identity"]["boot_id"] = "00000000-0000-0000-0000-000000000000"
        assert observer.observe_worker_process(wrong) == ("unknown", None)
    finally:
        if ready_read is not None:
            os.close(ready_read)
        if not reaped:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
    print(json.dumps({"status": "LIFECYCLE_VERIFIED", "backend_qualified": False,
                      "cases": ["live", "repeat", "comm-bytes", "caller-self", "nonleader-caller",
                                "copied-helper", "zombie", "reaped", "wrong-boot"],
                      "namespace_mount_cases": "UNQUALIFIED: separate privileged guest qualification required"}))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--qualify"]:
        sys.exit(qualify())
    unittest.main()
