#!/usr/bin/env python3
"""Observed runtime stream cases and actual subprocess resource bounds."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "bin" / "review-run.py"
spec = importlib.util.spec_from_file_location("review_run", SOURCE)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
