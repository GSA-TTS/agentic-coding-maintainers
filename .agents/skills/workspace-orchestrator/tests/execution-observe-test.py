#!/usr/bin/env python3
"""Execution oracle, backend inspection and lifecycle uncertainty tests."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SOURCE = Path(__file__).resolve().parents[1] / "bin" / "execution-observe.py"
spec = importlib.util.spec_from_file_location("execution_observe", SOURCE)
assert spec and spec.loader
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


class ExecutionTests(unittest.TestCase):
    def case(self):
        return {"id": "double", "argv": ["/usr/bin/python3", "/source/main.py", "3"],
                "expected_stdout": "6\n", "expected_exit": 0, "timeout": 5}

    def definition(self):
        return {"schema_version": 1, "docker_binary": "/usr/bin/docker", "docker_sha256": "a" * 64,
                "endpoint": "unix:///explicit.sock", "container_id": "b" * 64, "created": "date",
                "image_id": "sha256:" + "c" * 64, "environment": ["PATH=/usr/bin:/bin"],
                "mounts": [], "cases": [self.case()], "head": "d" * 40, "base": "e" * 40,
                "source_sha256": {"main.py": "f" * 64}}

    def inspected(self):
        definition = self.definition()
        return {"Id": definition["container_id"], "Created": "date", "Image": definition["image_id"],
                "Config": {"User": "1000:1000", "Env": definition["environment"]},
                "State": {"Running": True, "Paused": False, "Restarting": False}, "Mounts": [],
                "HostConfig": {"NetworkMode": "none", "Privileged": False, "ReadonlyRootfs": True,
                               "IpcMode": "private",
                               "CapAdd": None, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges"],
                               "Memory": 1_073_741_824, "NanoCpus": 1_000_000_000, "PidsLimit": 128}}

    def test_oracle_positive_and_negative_are_real_assertions(self):
        self.assertEqual(observer.evaluate(self.case(), b"6\n", b"", 0, None)["verdict"], "PASS")
        for data in (b"PASS\n", b"", b"7\n"):
            self.assertEqual(observer.evaluate(self.case(), data, b"", 0, None)["verdict"], "FAIL")
        self.assertEqual(observer.evaluate(self.case(), b"6\n", b"", 0, "timeout")["verdict"], "UNVERIFIED")
        self.assertEqual(observer.evaluate(self.case(), b"", b"transport error", 127, None)["verdict"], "UNVERIFIED")
        for code in (-9, 1, 125):
            self.assertEqual(observer.evaluate(self.case(), b"", b"transport error", code, None)["verdict"], "UNVERIFIED")

    def test_definition_rejects_missing_duplicate_unbounded_cases(self):
        observer.validate_definition(self.definition())
        for cases in ([], [self.case(), self.case()], [{**self.case(), "timeout": 0}]):
            definition = self.definition()
            definition["cases"] = cases
            with self.assertRaises(observer.Unverified):
                observer.validate_definition(definition)

    def test_inspection_rejects_route_isolation_and_identity_changes(self):
        observer.inspect_guest(self.definition(), self.inspected())
        for key, value in (("NetworkMode", "bridge"), ("Privileged", True), ("PidsLimit", 0), ("ReadonlyRootfs", False), ("IpcMode", "container:other"), ("IpcMode", None)):
            changed = self.inspected()
            changed["HostConfig"][key] = value
            with self.assertRaises(observer.Unverified):
                observer.inspect_guest(self.definition(), changed)
        changed = self.inspected()
        changed["Created"] = "replacement"
        with self.assertRaises(observer.Unverified):
            observer.inspect_guest(self.definition(), changed)

    def test_capture_observes_real_child_and_drops_secret_environment(self):
        identities = []
        out, err, code, failure = observer.capture([sys.executable, "-I", "-c", "import os; print(os.getpid()); print(os.getenv('TOKEN_SENTINEL', 'absent'))"],
                                                   {"PATH": "/usr/bin:/bin"}, 5, identities.append)
        self.assertEqual(code, 0)
        self.assertIsNone(failure)
        self.assertEqual(err, b"")
        self.assertEqual(int(out.splitlines()[0]), identities[0])
        self.assertNotEqual(identities[0], os.getpid())
        self.assertEqual(out.splitlines()[1], b"absent")

    def test_timeout_does_not_claim_guest_termination(self):
        _, _, code, failure = observer.capture([sys.executable, "-c", "import time; time.sleep(20)"],
                                                {"PATH": "/usr/bin:/bin"}, 1, lambda _: None)
        self.assertNotEqual(code, 0)
        self.assertIn("termination unknown", failure)

    def test_lifecycle_fence_preserves_uncertain_capacity(self):
        coordinator = observer.dependency("orchestrator-state")
        record = {"execution_observations": {"attempt": {"termination": "UNVERIFIED"}}}
        with self.assertRaises(coordinator.UnknownError):
            coordinator.require_execution_stopped(record)
        record["execution_observations"]["attempt"]["termination"] = "STOPPED_OBSERVED"
        with self.assertRaises(coordinator.UnknownError):
            coordinator.require_execution_stopped(record)
        record["execution_observations"]["attempt"].update(phase="UNKNOWN_STOPPED", definition=self.definition(),
            stop_observation={"container_id": "b" * 64, "created": "date", "running": False})
        coordinator.require_execution_stopped(record)

    def test_retained_stream_tampering_fails_closed(self):
        c = observer.dependency("review-collect")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / "review-artifacts"
            store.mkdir()
            definition = self.definition()
            raw = observer.canonical(definition)
            c.publish(store, raw)
            c.publish(store, b"6\n")
            c.publish(store, b"")
            result = observer.evaluate(self.case(), b"6\n", b"", 0, None)
            attempt = {"request": {"operation_id": "one", "definition_sha256": observer.digest(raw), "expected_revision": 1},
                       "definition": definition, "phase": "CAPTURED", "termination": "UNVERIFIED", "owner": "owner",
                       "head": definition["head"], "base": definition["base"], "controller_sha256": "a" * 64,
                       "cases": [result], "launchers": [{"case": "double", "pid": 123, "process_start": "start",
                           "process_status": "alive", "identity": "actual Docker CLI child, not guest PID"}],
                       "result": {"oracle_verdict": "PASS", "applicable": True, "candidate_ready": False}}
            record = {"execution_observations": {"one": attempt}}
            observer.validate_attempts(record, root, c)
            missing_launcher = copy.deepcopy(record)
            missing_launcher["execution_observations"]["one"]["launchers"] = []
            with self.assertRaises(observer.Unverified):
                observer.validate_attempts(missing_launcher, root, c)
            corrupted = copy.deepcopy(record)
            corrupted["execution_observations"]["one"]["cases"][0]["verdict"] = "FAIL"
            with self.assertRaises(observer.Unverified):
                observer.validate_attempts(corrupted, root, c)
            path = store / observer.digest(b"6\n")
            path.chmod(0o600)
            path.write_bytes(b"tampered")
            with self.assertRaises(observer.Unverified):
                observer.validate_attempts(record, root, c)
            # Missing stream cannot permanently prevent exact guest stop.
            record.update(owner="owner", state="Claimed", worker={}, leases={"global_slot": 0}, head_sha=definition["head"], base_sha=definition["base"], worktree=str(root))
            stopped = {"Id": definition["container_id"], "Created": definition["created"], "State": {"Running": False}}
            observer.reconcile_stop(record, attempt, stopped, root, c)
            self.assertEqual(attempt["phase"], "EVIDENCE_LOST_STOPPED")
            self.assertEqual(attempt["result"]["oracle_verdict"], "UNVERIFIED")
            observer.validate_attempts(record, root, c)

    def test_stop_before_finalization_and_consistent_exit_mapping(self):
        attempt = {"phase": "UNKNOWN_STOPPED", "termination": "STOPPED_OBSERVED", "definition": self.definition()}
        for output, expected in ((b"6\n", 0), (b"7\n", 1)):
            current = copy.deepcopy(attempt)
            observer.finalize(current, [observer.evaluate(self.case(), output, b"", 0, None)], True)
            self.assertEqual(current["phase"], "SETTLED")
            self.assertEqual(observer.exit_code(current), expected)
        current = copy.deepcopy(attempt)
        observer.finalize(current, [observer.evaluate(self.case(), b"", b"", -9, "timeout")], True)
        self.assertEqual(observer.exit_code(current), 3)
        current["phase"] = "CAPTURED"
        self.assertEqual(observer.exit_code(current), 3)

    def test_slotless_rework_is_not_execution_admission(self):
        self.assertFalse(observer.active_execution_owner({"state": "Rework", "worker": None, "leases": {"global_slot": None}}))
        self.assertFalse(observer.active_execution_owner({"state": "Claimed", "worker": {}, "leases": {"global_slot": None}}))
        self.assertTrue(observer.active_execution_owner({"state": "Claimed", "worker": {}, "leases": {"global_slot": 0}}))

    def test_public_command_retains_intent_across_injected_client_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "candidate"
            worktree.mkdir()
            environment = {**os.environ, "ORCHESTRATOR_TEST_MODE": "1", "ORCHESTRATOR_STATE_DIR": str(root / "state")}
            state_script = SOURCE.with_name("orchestrator-state.py")
            def state(*args):
                return subprocess.run([sys.executable, "-I", "-B", str(state_script), *args], env=environment, capture_output=True, text=True)
            self.assertEqual(state("create", "test", "--scope", "execution:fixture", "--kind", "review", "--head-sha", "d" * 40,
                                   "--base-sha", "e" * 40, "--worktree", str(worktree)).returncode, 0)
            self.assertEqual(state("claim", "test", "--owner", "owner", "--pid", str(os.getpid())).returncode, 0)
            record = json.loads(state("show", "test").stdout)
            definition = self.definition()
            definition["docker_binary"] = str(Path(sys.executable).resolve())
            definition["docker_sha256"] = observer.dependency("review-run").binary_digest(Path(sys.executable).resolve())
            raw = observer.canonical(definition)
            path = root / "definition.json"
            path.write_bytes(raw)
            argv = [str(SOURCE), "test", "--operation-id", "run", "--definition", str(path),
                    "--definition-sha256", observer.digest(raw), "--expected-revision", str(record["revision"])]
            with mock.patch.dict(os.environ, environment), mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(observer, "source_binding"), mock.patch.object(observer, "inspect_backend", return_value=self.inspected()), \
                    mock.patch.object(observer, "capture", side_effect=OSError("client spawn uncertain")) as dispatch:
                self.assertEqual(observer.main(), 3)
                retained = json.loads(state("show", "test").stdout)
                self.assertEqual(retained["execution_observations"]["run"]["phase"], "DISPATCHING")
                self.assertEqual(observer.main(), 3)
                self.assertEqual(dispatch.call_count, 1)
            self.assertEqual(state("transition", "test", "Blocked", "--reason", "unsafe capacity release").returncode, 3)
            self.assertEqual(json.loads(state("show", "test").stdout)["leases"]["global_slot"], record["leases"]["global_slot"])

    def test_source_binding_checks_actual_checkout_head(self):
        c = observer.dependency("review-collect")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "main.py").write_bytes(b"source")
            def git(*args):
                return subprocess.check_output(["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                                                "-c", "commit.gpgsign=false", *args]).decode().strip()
            git("add", ".")
            git("commit", "-qm", "first")
            definition = self.definition()
            definition["head"] = git("rev-parse", "HEAD")
            definition["source_sha256"] = {"main.py": observer.digest(b"source")}
            record = {"head_sha": definition["head"], "base_sha": definition["base"], "worktree": str(root)}
            observer.source_binding(record, definition, c)
            git("-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-qm", "same source new head")
            with self.assertRaises(observer.Unverified):
                observer.source_binding(record, definition, c)


if __name__ == "__main__":
    unittest.main()
