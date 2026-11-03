#!/usr/bin/env python3
"""Observed runtime stream cases and actual subprocess resource bounds."""

import importlib.util
import base64
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "bin" / "review-run.py"
spec = importlib.util.spec_from_file_location("review_run", SOURCE)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def map_fixture(self):
        mapping = runner.source_map_module()
        manifest = {"/candidate/old.py": runner.sha256(b"before"), "/candidate/new.py": runner.sha256(b"after")}
        selections = {path: {"side": side, "path_base64": base64.b64encode(b"src/\xff.py").decode()}
                      for path, side in zip(manifest, ("before", "after"))}
        value = mapping.project("a" * 40, "b" * 40, "c" * 64, selections, manifest)
        return mapping, value, manifest

    def test_source_map_strict_inventory_and_exact_original_path_bytes(self):
        mapping, value, manifest = self.map_fixture()
        self.assertEqual(mapping.decode(mapping.h.canonical(value), manifest), value)
        self.assertEqual(base64.b64decode(value["sources"][0]["path_base64"]), b"src/\xff.py")
        for damage in ("top-extra", "nested-extra", "missing", "duplicate", "hash", "guest", "base", "path", "side"):
            changed = copy.deepcopy(value)
            if damage == "top-extra":
                changed["environment"] = {}
            elif damage == "nested-extra":
                changed["sources"][0]["command"] = "refused"
            elif damage == "missing":
                changed["sources"].pop()
            elif damage == "duplicate":
                changed["sources"].append(changed["sources"][0])
            elif damage == "hash":
                changed["sources"][0]["sha256"] = "0" * 64
            elif damage == "guest":
                changed["sources"][0]["guest_path"] = "/candidate/other.py"
            elif damage == "base":
                changed["base"] = "short"
            elif damage == "path":
                changed["sources"][0]["path_base64"] = "Li4vZXNjYXBl"
            else:
                changed["sources"][0]["side"] = "current"
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                mapping.decode(mapping.h.canonical(changed), manifest)
        with self.assertRaises(ValueError):
            mapping.decode(b'{"schema_version":1,"schema_version":1}', manifest)

    def test_runner_prompt_map_receipt_and_context_unchanged(self):
        self.run_map_case(mutate=False)

    def test_runner_changed_map_downgrades_receipt(self):
        self.run_map_case(mutate=True)

    def run_map_case(self, mutate):
        mapping, value, manifest = self.map_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            map_path, context_path = root / "source-map.json", root / "context.json"
            raw = mapping.h.canonical(value)
            map_path.write_bytes(raw)
            context_raw = b'{"acceptance_criteria":["preserve exact context"]}\n'
            context_path.write_bytes(context_raw)
            # Measure real file bytes, translating only the guest mount in this
            # unit fixture. The runner itself does no path translation.
            actual = []
            for name, data in (("old.py", b"before"), ("new.py", b"after")):
                path = root / name
                path.write_bytes(data)
                actual.append(path)
            measured = runner.source_manifest(actual)
            self.assertEqual(manifest, {"/candidate/" + p.name: measured[str(p)] for p in actual})
            argv = ["review-run", "--binary", "/trusted/opencode", "--binary-sha256", "d" * 64,
                    "--cwd", "/candidate", "--model", "fixture/model", "--isolated-guest",
                    "--context", str(context_path), "--source-map", str(map_path), "--output", str(root / "output")]
            for path in manifest:
                argv += ["--source", path]
            calls = []
            def execute(command, cwd, timeout):
                calls.append(command)
                if len(calls) == 1:
                    self.assertIn(raw.decode(), command[-1])
                    self.assertIn("untrusted JSON data", command[-1])
                    self.assertIn("before side belongs to base", command[-1])
                    events = [{"type": "tool_use", "sessionID": "ses_test", "part": {"tool": "read", "state": {
                        "status": "completed", "input": {"path": p}, "output": f"Read file {p}, lines 1-1\n1: fixture"}}}
                              for p in manifest] + self.events()[1:]
                    if mutate:
                        changed = copy.deepcopy(value)
                        changed["sources"][0]["side"] = "before" if changed["sources"][0]["side"] == "after" else "after"
                        map_path.write_bytes(mapping.h.canonical(changed))
                    return b"\n".join(json.dumps(e).encode() for e in events), b"", 0, None
                exported = {"info": {"id": "ses_test", "outcome": "succeeded", "tokens": {"input": 100, "output": 20}},
                            "messages": [{"type": "assistant", "finish": "stop", "content": [{"type": "text", "text": '{"findings":[]}'}]}]}
                return json.dumps(exported).encode(), b"", 0, None
            with mock.patch.object(sys, "argv", argv), mock.patch.object(runner, "source_manifest", return_value=manifest), \
                    mock.patch.object(runner, "binary_digest", return_value="d" * 64), \
                    mock.patch.object(runner, "execute", side_effect=execute), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(), 3 if mutate else 0)
            receipt = json.loads((root / "output/receipt.json").read_bytes())
            self.assertEqual(receipt["source_map_sha256"], runner.sha256(raw))
            self.assertEqual(receipt["context_sha256"], runner.sha256(context_raw))
            self.assertEqual(context_path.read_bytes(), context_raw)
            self.assertEqual(receipt["status"], "UNVERIFIED" if mutate else "REVIEW_OBSERVED")

    def events(self):
        return [
            {"type": "tool_use", "sessionID": "ses_test", "part": {
                "tool": "read", "state": {"status": "completed", "input": {"path": "/source/a.py"},
                                           "output": "Read file /source/a.py, lines 1-1\n1: x = 1"}}},
            {"type": "text", "sessionID": "ses_test", "part": {"text": '{"findings":[]}'}},
            {"type": "step_finish", "sessionID": "ses_test", "part": {
                "reason": "stop", "tokens": {"input": 100, "output": 20}}},
        ]

    def summary(self, events, rc=0):
        data = b"\n".join(json.dumps(item).encode() for item in events)
        return runner.summarize(data, rc, {"/source/a.py": "digest"}, Path("/source"))

    def test_positive_observation_has_no_readiness_credit(self):
        result = self.summary(self.events())
        self.assertEqual(result["status"], "REVIEW_OBSERVED")
        self.assertEqual(result["source_reads"], ["/source/a.py"])
        self.assertEqual(result["tokens"], {"input": 100, "output": 20})
        self.assertFalse(result["candidate_ready"])
        self.assertFalse(result["execution_credit"])

    def test_zero_exit_with_error_or_no_terminal_is_unknown(self):
        events = self.events()
        events.append({"type": "error", "sessionID": "ses_test", "error": {"message": "provider unavailable"}})
        self.assertEqual(self.summary(events)["status"], "UNVERIFIED")
        self.assertEqual(self.summary(self.events()[:-1])["status"], "UNVERIFIED")
        self.assertEqual(self.summary(self.events(), 1)["status"], "UNVERIFIED")

    def test_read_failure_and_wrong_file_do_not_count(self):
        for output in ("Unable to read", "Read file /source/other.py, lines 1-1\n1: unrelated"):
            events = self.events()
            events[0]["part"]["state"]["output"] = output
            self.assertEqual(self.summary(events)["status"], "UNVERIFIED")

    def test_session_substitution_and_malformed_usage(self):
        events = self.events()
        events[-1]["sessionID"] = "ses_other"
        self.assertEqual(self.summary(events)["status"], "UNVERIFIED")
        events = self.events()
        events[-1]["part"]["tokens"]["input"] = True
        self.assertEqual(self.summary(events)["status"], "UNVERIFIED")

    def test_duplicate_and_non_json_events(self):
        for data in (b'{"type":"error","type":"text"}', b"not JSON"):
            self.assertEqual(runner.summarize(data, 0, {}, Path("/"))["status"], "UNVERIFIED")

    def test_actual_process_output_and_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            data, errors, rc, failure = runner.execute([sys.executable, "-c", "print('observed')"], Path(directory), 5)
            self.assertEqual(data, b"observed\n")
            self.assertEqual(errors, b"")
            self.assertEqual(rc, 0)
            self.assertIsNone(failure)
            _, _, rc, failure = runner.execute([sys.executable, "-c", "import time; time.sleep(30)"], Path(directory), 1)
            self.assertNotEqual(rc, 0)
            self.assertEqual(failure, "runtime timeout")

    def test_export_corroborates_missing_stream_completion(self):
        events = self.events()[:-1]
        data = b"\n".join(json.dumps(item).encode() for item in events)
        exported = {"info": {"id": "ses_test", "outcome": "succeeded", "tokens": {"input": 100, "output": 20}},
                    "messages": [{"type": "assistant", "finish": "stop", "content": [{"type": "text", "text": '{"findings":[]}'}]}]}
        args = (data, 0, {"/source/a.py": "digest"}, Path("/source"))
        self.assertEqual(runner.summarize(*args, json.dumps(exported).encode())["status"], "REVIEW_OBSERVED")
        exported["info"]["id"] = "ses_other"
        self.assertEqual(runner.summarize(*args, json.dumps(exported).encode())["status"], "UNVERIFIED")

    def test_export_failure_downgrades_even_complete_stream(self):
        data = b"\n".join(json.dumps(item).encode() for item in self.events())
        for code, reason in ((1, None), (-9, "runtime timeout"), (-9, "runtime output exceeded bound")):
            result = runner.corroborate(data, 0, {"/source/a.py": "digest"}, Path("/source"), b"", code, reason)
            self.assertEqual(result["status"], "UNVERIFIED")
            self.assertEqual(result["export_returncode"], code)
            self.assertEqual(result["export_failure"], reason)

    def test_binary_hash_rejects_fifo_and_oversize(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime"
            os.mkfifo(path)
            with self.assertRaises(runner.Unverified):
                runner.binary_digest(path)
            regular = Path(directory) / "regular"
            regular.write_bytes(b"123456")
            with self.assertRaises(runner.Unverified):
                runner.binary_digest(regular, maximum=5)
            self.assertEqual(runner.binary_digest(regular), runner.sha256(b"123456"))

    def test_guest_path_does_not_resolve_controller_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "actual"
            target.mkdir()
            alias = root / "alias"
            alias.symlink_to(target, target_is_directory=True)
            self.assertEqual(runner.guest_path(str(alias / "source.py"), root), str(alias / "source.py"))
            self.assertEqual(runner.guest_path("../source.py", alias), str(root / "source.py"))
        self.assertEqual(runner.guest_path("/tmp/source.py", Path("/review")), "/tmp/source.py")

    def test_context_reader_bounds_and_refuses_replacement_types(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/"context.json"
            path.write_bytes(b"{}")
            self.assertEqual(runner.context_read(path),b"{}")
            path.write_bytes(b"x"*50001)
            with self.assertRaises(runner.Unverified): runner.context_read(path)
            fifo=root/"fifo"; os.mkfifo(fifo)
            with self.assertRaises(runner.Unverified): runner.context_read(fifo)
            link=root/"alias"; link.symlink_to(path)
            with self.assertRaises(runner.Unverified): runner.context_read(link)


if __name__ == "__main__":
    unittest.main()
