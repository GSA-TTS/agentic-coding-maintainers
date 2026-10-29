#!/usr/bin/env python3
"""Execution oracle, backend inspection and lifecycle uncertainty tests."""

import copy
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

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
                               "CapAdd": None, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges"],
                               "Memory": 1_073_741_824, "NanoCpus": 1_000_000_000, "PidsLimit": 128}}

    def test_oracle_positive_and_negative_are_real_assertions(self):
        self.assertEqual(observer.evaluate(self.case(), b"6\n", b"", 0, None)["verdict"], "PASS")
        for data in (b"PASS\n", b"", b"7\n"):
            self.assertEqual(observer.evaluate(self.case(), data, b"", 0, None)["verdict"], "FAIL")
        self.assertEqual(observer.evaluate(self.case(), b"6\n", b"", 0, "timeout")["verdict"], "UNVERIFIED")
        self.assertEqual(observer.evaluate(self.case(), b"", b"transport error", 127, None)["verdict"], "UNVERIFIED")

    def test_definition_rejects_missing_duplicate_unbounded_cases(self):
        observer.validate_definition(self.definition())
        for cases in ([], [self.case(), self.case()], [{**self.case(), "timeout": 0}]):
            definition = self.definition()
            definition["cases"] = cases
            with self.assertRaises(observer.Unverified):
                observer.validate_definition(definition)

    def test_inspection_rejects_route_isolation_and_identity_changes(self):
        observer.inspect_guest(self.definition(), self.inspected())
        for key, value in (("NetworkMode", "bridge"), ("Privileged", True), ("PidsLimit", 0), ("ReadonlyRootfs", False)):
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
                       "cases": [result], "launchers": [{"case": "double", "pid": 123}],
                       "result": {"oracle_verdict": "PASS", "applicable": True, "candidate_ready": False}}
            record = {"execution_observations": {"one": attempt}}
            observer.validate_attempts(record, root, c)
            corrupted = copy.deepcopy(record)
            corrupted["execution_observations"]["one"]["cases"][0]["verdict"] = "FAIL"
            with self.assertRaises(observer.Unverified):
                observer.validate_attempts(corrupted, root, c)
            path = store / observer.digest(b"6\n")
            path.chmod(0o600)
            path.write_bytes(b"tampered")
            with self.assertRaises(observer.Unverified):
                observer.validate_attempts(record, root, c)


if __name__ == "__main__":
    unittest.main()
