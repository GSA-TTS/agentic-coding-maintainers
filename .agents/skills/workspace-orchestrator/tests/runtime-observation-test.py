#!/usr/bin/env python3
"""Bounded process observation and its coordination-core compatibility facade."""

import importlib.util
import inspect
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


observation = load("runtime_observation_fixture", BIN / "runtime-observation.py")
core = load("runtime_observation_core_fixture", BIN / "orchestrator-state.py")
CHILD = [sys.executable, "-I", "-B", "-c", "import time; time.sleep(60)"]


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class RealObservationTests(unittest.TestCase):
    def start_child(self):
        child = subprocess.Popen(CHILD, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (child.kill(), child.wait()) if child.poll() is None else None)
        return child

    def test_live_child_then_absent_after_reaping(self):
        child = self.start_child()
        status, start = observation.process_identity(child.pid)
        self.assertEqual(status, "alive")
        self.assertTrue(start)
        self.assertEqual(observation.process_identity(child.pid), (status, start))
        self.assertEqual(core.process_identity(child.pid), (status, start))
        child.kill()
        child.wait()
        self.assertEqual(observation.process_identity(child.pid), ("absent", None))
        self.assertEqual(core.process_identity(child.pid), ("absent", None))

    def test_explicit_environment_is_forwarded_to_a_real_probe(self):
        child = self.start_child()
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
        status, start = observation.process_identity(child.pid, environment=env)
        self.assertEqual((status, bool(start)), ("alive", True))
        self.assertEqual(core.process_identity(child.pid, environment=env), (status, start))

    def test_an_observation_is_about_one_pid_not_its_descendants(self):
        # A live child says nothing about a grandchild; descendant termination
        # needs separate evidence that this module does not and must not supply.
        code = ("import subprocess,sys;"
                "g=subprocess.Popen([sys.executable,'-I','-B','-c','import time;time.sleep(60)']);"
                "print(g.pid,flush=True);g.wait()")
        parent = subprocess.Popen([sys.executable, "-I", "-B", "-c", code], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, text=True)
        grandchild = int(parent.stdout.readline())

        def cleanup():
            parent.kill()
            parent.wait()
            parent.stdout.close()
            try:
                os.kill(grandchild, 9)
            except ProcessLookupError:
                pass
        self.addCleanup(cleanup)
        parent.kill()
        parent.wait()
        self.assertEqual(observation.process_identity(parent.pid), ("absent", None))
        self.assertEqual(observation.process_identity(grandchild)[0], "alive")


class BoundedProbeTests(unittest.TestCase):
    def probe(self, result=None, **kwargs):
        patch = (mock.patch.object(observation.subprocess, "run", return_value=result)
                 if kwargs.get("side_effect") is None else
                 mock.patch.object(observation.subprocess, "run", side_effect=kwargs["side_effect"]))
        with patch as run:
            value = observation.process_identity(4242, **{k: v for k, v in kwargs.items() if k == "environment"})
        return value, run

    def test_exact_bounded_invocation(self):
        env = {"PATH": "/x"}
        value, run = self.probe(completed(0, "Mon Nov  9 10:00:00 2026\n"), environment=env)
        self.assertEqual(value, ("alive", "Mon Nov  9 10:00:00 2026"))
        run.assert_called_once_with(["ps", "-p", "4242", "-o", "lstart="], check=False,
                                    capture_output=True, text=True, timeout=3, env=env)
        _, run = self.probe(completed(1))
        self.assertIsNone(run.call_args.kwargs["env"])

    def test_current_status_mapping(self):
        cases = (
            (completed(1, "", ""), ("absent", None)),
            (completed(1, "", " \n"), ("absent", None)),
            (completed(0, "", ""), ("absent", None)),
            (completed(0, "  \n\t", ""), ("absent", None)),
            (completed(0, "  Mon Nov  9 10:00:00 2026  \n", ""), ("alive", "Mon Nov  9 10:00:00 2026")),
            (completed(0, "unparsed garbage\n", ""), ("alive", "unparsed garbage")),
            (completed(0, "one\ntwo\n", ""), ("alive", "one\ntwo")),
            (completed(0, "Mon Nov  9 10:00:00 2026\n", "warning"), ("alive", "Mon Nov  9 10:00:00 2026")),
            (completed(1, "Mon Nov  9 10:00:00 2026\n", ""), ("alive", "Mon Nov  9 10:00:00 2026")),
            (completed(1, "", "ps: error"), ("unknown", None)),
            (completed(1, "Mon Nov  9 10:00:00 2026\n", "ps: error"), ("unknown", None)),
            (completed(2, "", ""), ("unknown", None)),
            (completed(2, "Mon Nov  9 10:00:00 2026\n", ""), ("unknown", None)),
            (completed(-9, "", ""), ("unknown", None)),
            (completed(127, "", ""), ("unknown", None)),
        )
        for result, expected in cases:
            with self.subTest(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr):
                self.assertEqual(self.probe(result)[0], expected)

    def test_timeout_and_launch_errors_are_unknown(self):
        for error in (subprocess.TimeoutExpired(["ps"], 3), subprocess.SubprocessError("x"),
                      FileNotFoundError("ps"), PermissionError("ps"), OSError("x")):
            with self.subTest(error=type(error).__name__):
                self.assertEqual(self.probe(side_effect=error)[0], ("unknown", None))

    def test_unexpected_exceptions_are_not_swallowed(self):
        with self.assertRaises(ValueError):
            self.probe(side_effect=ValueError("not an observation failure"))


class FacadeCompatibilityTests(unittest.TestCase):
    def test_signature_is_preserved(self):
        facade = inspect.signature(core.process_identity)
        self.assertEqual(facade, inspect.signature(observation.process_identity))
        self.assertEqual(list(facade.parameters), ["pid", "environment"])
        self.assertIs(facade.parameters["environment"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIsNone(facade.parameters["environment"].default)

    def test_facade_forwards_pid_environment_and_result_unchanged(self):
        env = {"PATH": "/usr/bin:/bin"}
        sentinel = ("alive", "exact text")
        with mock.patch.object(core._observation, "process_identity", return_value=sentinel) as extracted:
            self.assertIs(core.process_identity(77, environment=env), sentinel)
            extracted.assert_called_once_with(77, environment=env)
            core.process_identity(78)
            extracted.assert_called_with(78, environment=None)
        with mock.patch.object(core._observation, "process_identity", side_effect=ValueError("propagates")):
            with self.assertRaises(ValueError):
                core.process_identity(79)

    def test_probe_errors_surface_identically_through_facade(self):
        with mock.patch.object(observation.subprocess, "run", side_effect=subprocess.TimeoutExpired(["ps"], 3)):
            self.assertEqual(core.process_identity(5), ("unknown", None))
        with mock.patch.object(observation.subprocess, "run", return_value=completed(1, "", "boom")):
            self.assertEqual(core.process_identity(5), ("unknown", None))

    def test_core_callers_still_use_the_patchable_module_attribute(self):
        with mock.patch.object(core, "process_identity", return_value=("alive", "start text")) as patched:
            metadata = core.worker_metadata("task-a", "owner-a", 31337)
        patched.assert_called_once_with(31337)
        self.assertEqual((metadata["pid"], metadata["process_start"], metadata["owner"], metadata["task_id"]),
                         (31337, "start text", "owner-a", "task-a"))
        for status, start in (("absent", None), ("unknown", None), ("alive", "")):
            with self.subTest(status=status, start=start):
                with mock.patch.object(core, "process_identity", return_value=(status, start)):
                    with self.assertRaises(core.UnknownError):
                        core.worker_metadata("task-a", "owner-a", 31337)

    def test_worker_metadata_with_a_real_process(self):
        child = subprocess.Popen(CHILD, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (child.kill(), child.wait()))
        metadata = core.worker_metadata("task-a", "owner-a", child.pid)
        self.assertEqual(metadata["process_start"], core.process_identity(child.pid)[1])

    def test_copied_skill_uses_its_own_sibling_and_requires_it(self):
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "skill"
            shutil.copytree(BIN, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            module = load("runtime_observation_copied_core", copied / "orchestrator-state.py")
            self.assertEqual(Path(module._observation.__file__).resolve(),
                             (copied / "runtime-observation.py").resolve())
            self.assertEqual(module.process_identity(os.getpid())[0], "alive")
            (copied / "runtime-observation.py").unlink()
            with self.assertRaises(FileNotFoundError):
                load("runtime_observation_missing_core", copied / "orchestrator-state.py")


if __name__ == "__main__":
    unittest.main()
