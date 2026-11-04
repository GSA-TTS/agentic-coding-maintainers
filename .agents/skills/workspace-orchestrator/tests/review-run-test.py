#!/usr/bin/env python3
"""Observed runtime stream cases and actual subprocess resource bounds."""

import importlib.util
import base64
import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import time
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
            def execute(command, cwd, timeout, env=None):
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
            self.assertEqual(receipt["environment"], "inherited/unverified")

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

    def test_actual_output_overflow(self):
        with mock.patch.object(runner, "MAX_TRANSCRIPT", 1024):
            data, errors, rc, failure = runner.execute(
                [sys.executable, "-c", "import os,time; os.write(2,b'x'*2048); time.sleep(30)"], Path.cwd(), 5, {})
        self.assertEqual(data, b"")
        self.assertEqual(len(errors), 1024)
        self.assertNotEqual(rc, 0)
        self.assertEqual(failure, "runtime output exceeded bound")

    def assert_reaped(self, child):
        self.assertIsNotNone(child.returncode)
        self.assertTrue(child.stdout.closed)
        self.assertTrue(child.stderr.closed)
        with self.assertRaises(ChildProcessError):
            os.waitpid(child.pid, os.WNOHANG)

    def test_post_spawn_failures_reap_real_child(self):
        popen, read = subprocess.Popen, os.read
        selector_factory = runner.selectors.DefaultSelector
        for stage in ("constructor", "first-register", "second-register", "read", "decode"):
            children = []
            def spawn(*args, **kwargs):
                child = popen(*args, **kwargs)
                children.append(child)
                return child
            def failing_read(fd, size):
                if children and fd in (children[0].stdout.fileno(), children[0].stderr.fileno()):
                    if stage == "decode":
                        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "fixture")
                    raise OSError("fixture read failure")
                return read(fd, size)
            selector = selector_factory()
            try:
                with contextlib.ExitStack() as stack, self.subTest(stage=stage):
                    stack.enter_context(mock.patch.object(runner.subprocess, "Popen", side_effect=spawn))
                    if stage == "constructor":
                        stack.enter_context(mock.patch.object(runner.selectors, "DefaultSelector", side_effect=OSError("fixture")))
                    else:
                        stack.enter_context(mock.patch.object(runner.selectors, "DefaultSelector", return_value=selector))
                    if "register" in stage:
                        register = selector.register
                        count = 0
                        def failing_register(*args):
                            nonlocal count
                            count += 1
                            if count == (1 if stage == "first-register" else 2):
                                raise OSError("fixture registration failure")
                            return register(*args)
                        stack.enter_context(mock.patch.object(selector, "register", side_effect=failing_register))
                    if stage in ("read", "decode"):
                        stack.enter_context(mock.patch.object(runner.os, "read", side_effect=failing_read))
                    _, _, rc, failure = runner.execute(
                        [sys.executable, "-c", "import os,time; os.write(1,b'ready'); time.sleep(30)"], Path.cwd(), 5, {})
                    self.assertNotEqual(rc, 0)
                    self.assertEqual(failure, "runtime stream operation failed")
                    self.assertEqual(len(children), 1)
                    self.assert_reaped(children[0])
            finally:
                selector.close()

    def test_cleanup_failure_is_bounded_and_reported(self):
        for broken in ("signal", "reap", "selector-close"):
            with self.subTest(broken=broken):
                child = mock.Mock(pid=12345, returncode=0)
                child.wait.side_effect = [0, subprocess.TimeoutExpired("stub", runner.REAP_TIMEOUT)] if broken == "reap" else [0, 0]
                selector = mock.Mock()
                selector.get_map.return_value = {}
                if broken == "selector-close":
                    selector.close.side_effect = OSError("fixture")
                with mock.patch.object(runner.subprocess, "Popen", return_value=child), \
                        mock.patch.object(runner.selectors, "DefaultSelector", return_value=selector), \
                        mock.patch.object(runner.os, "killpg", side_effect=PermissionError("fixture") if broken == "signal" else None):
                    started = time.monotonic()
                    _, _, rc, failure = runner.execute(["stub"], Path.cwd(), 5, {})
                self.assertLess(time.monotonic() - started, 1)
                self.assertEqual(rc, 0)  # even a successful child must not hide cleanup failure
                self.assertIn("runtime cleanup failed", failure)
                self.assertEqual(child.wait.call_count, 2)
                self.assertEqual(child.wait.call_args, mock.call(timeout=runner.REAP_TIMEOUT))
                self.assertTrue(all(call.kwargs["timeout"] > 0 for call in child.wait.call_args_list))
                child.stdout.close.assert_called_once()
                child.stderr.close.assert_called_once()

    def test_cancellation_with_reap_failure_retains_failure_note(self):
        child = mock.Mock(pid=12345, returncode=None)
        child.wait.side_effect = subprocess.TimeoutExpired("stub", runner.REAP_TIMEOUT)
        with mock.patch.object(runner.subprocess, "Popen", return_value=child), \
                mock.patch.object(runner.selectors, "DefaultSelector", side_effect=SystemExit(7)), \
                mock.patch.object(runner.os, "killpg"), self.assertRaises(SystemExit) as raised:
            runner.execute(["stub"], Path.cwd(), 5, {})
        self.assertEqual(raised.exception.code, 7)
        self.assertIn("runtime cleanup failed: child reap", raised.exception.__notes__)
        child.wait.assert_called_once_with(timeout=runner.REAP_TIMEOUT)
        child.stdout.close.assert_called_once()
        child.stderr.close.assert_called_once()

    def stub_main(self, root):
        source = root / "source.py"
        source.write_text("value = 1\n")
        events = self.events()
        events[0]["part"]["state"].update(input={"path": str(source)}, output=f"Read file {source}, lines 1-1\n1: value = 1")
        exported = {"info": {"id": "ses_test", "outcome": "succeeded", "tokens": {"input": 100, "output": 20}},
                    "messages": [{"type": "assistant", "finish": "stop", "content": [{"type": "text", "text": '{"findings":[]}'}]}]}
        binary = root / "stub-runtime"
        # Only synthetic credentials; the child records presence/equality, not values.
        binary.write_text(f"#!{sys.executable}\n" +
            "import json,os,sys\nfrom pathlib import Path\n" +
            "assert 'GH_TOKEN' not in os.environ\nassert 'SENTINEL_CREDENTIAL' not in os.environ\n" +
            "assert os.environ.get('OPENAI_API_KEY') == 'fixture-only'\n" +
            "Path('seen-' + sys.argv[1]).write_text('selected environment observed')\n" +
            f"print({chr(10).join(json.dumps(e) for e in events)!r} if sys.argv[1] == 'run' else {json.dumps(exported)!r})\n")
        binary.chmod(0o700)
        argv = ["review-run", "--binary", str(binary), "--binary-sha256", runner.binary_digest(binary),
                "--cwd", str(root), "--source", str(source), "--model", "fixture/model", "--isolated-guest",
                "--output", str(root / "output")]
        return argv

    def test_main_real_stub_run_and_export_share_selected_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            argv = self.stub_main(root)
            environment = root / "operator.json"
            environment.write_text(json.dumps({"OPENAI_API_KEY": "fixture-only", "LC_ALL": "C"}))
            environment.chmod(0o600)
            argv += ["--environment-file", str(environment)]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()), \
                    mock.patch.dict(os.environ, {"SENTINEL_CREDENTIAL": "ambient-only", "GH_TOKEN": "ambient-only"}):
                self.assertEqual(runner.main(), 0)
            self.assertTrue((root / "seen-run").is_file())
            self.assertTrue((root / "seen-session").is_file())
            receipt = (root / "output/receipt.json").read_text()
            self.assertEqual(json.loads(receipt)["environment"], "operator-supplied")
            self.assertEqual(json.loads(receipt)["status"], "REVIEW_OBSERVED")
            for sensitive in ("OPENAI_API_KEY", "fixture-only", "ambient-only", "operator.json"):
                self.assertNotIn(sensitive, receipt)

    def test_api_empty_environment_does_not_inherit(self):
        with mock.patch.dict(os.environ, {"SENTINEL_CREDENTIAL": "ambient-only"}):
            data, _, rc, failure = runner.execute([sys.executable, "-c",
                "import os; print('SENTINEL_CREDENTIAL' in os.environ)"], Path.cwd(), 5, {})
        self.assertEqual((data, rc, failure), (b"False\n", 0, None))

    def test_main_cancellation_reaps_without_export_or_new_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            argv = self.stub_main(root)
            children = []
            popen = subprocess.Popen
            def spawn(*args, **kwargs):
                child = popen(*args, **kwargs)
                children.append(child)
                return child
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(runner.subprocess, "Popen", side_effect=spawn), \
                    mock.patch.object(runner.selectors, "DefaultSelector", side_effect=KeyboardInterrupt), \
                    self.assertRaises(KeyboardInterrupt):
                runner.main()
            self.assertEqual(len(children), 1)
            self.assert_reaped(children[0])
            self.assertFalse((root / "output/receipt.json").exists())

    def test_cleanup_failure_suppresses_observation_and_export(self):
        for phase in ("run", "export"):
            with tempfile.TemporaryDirectory() as directory, self.subTest(phase=phase):
                root = Path(directory)
                argv = self.stub_main(root)
                data = b"\n".join(json.dumps(e).encode() for e in self.events())
                manifest = {"/source/a.py": "digest"}
                failure = "runtime cleanup failed: child reap"
                first = (data, b"", 0, failure if phase == "run" else None)
                with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()), \
                        mock.patch.object(runner, "source_manifest", return_value=manifest), \
                        mock.patch.object(runner, "execute", side_effect=[first, (b"{}", b"", 0, failure)]) as execute:
                    self.assertEqual(runner.main(), 3)
                self.assertEqual(execute.call_count, 1 if phase == "run" else 2)
                receipt = json.loads((root / "output/receipt.json").read_text())
                self.assertEqual(receipt["status"], "UNVERIFIED")
                self.assertEqual(receipt["failure" if phase == "run" else "export_failure"], failure)

    def test_environment_policy_rejects_before_spawn(self):
        invalid = [[], {"HOME": 1}, {"HOME": "bad\x00value"}, {"HOME": "\ud800"},
                   {"HOME": "x" * (runner.MAX_ENV_VALUES + 1)}, {str(i): "" for i in range(65)}]
        invalid += [{name: "fixture"} for name in ("LD_PRELOAD", "PYTHONPATH", "GH_TOKEN", "HTTPS_PROXY",
                    "http_proxy", "NODE_OPTIONS", "OPENCODE_CONFIG", "XDG_CONFIG_DIRS", "AWS_ACCESS_KEY_ID")]
        for value in invalid:
            with self.subTest(value_type=type(value).__name__), mock.patch.object(runner.subprocess, "Popen") as spawn:
                with self.assertRaises(runner.Unverified):
                    runner.execute(["unused"], Path.cwd(), 5, value)
                spawn.assert_not_called()
        selected = {"HOME": "x" * runner.MAX_ENV_VALUES}
        self.assertEqual(runner.selected_environment(selected), selected)
        self.assertIsNot(runner.selected_environment(selected), selected)

    def test_environment_file_strict_private_bounded_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "environment.json"
            path.write_text('{"HOME":"/work"}')
            path.chmod(0o600)
            self.assertEqual(runner.environment_read(path), {"HOME": "/work"})
            for data in (b'{"HOME":"a","HOME":"b"}', b'[]', b'{', b'\xff', '{}'.encode("utf-16"),
                         b'{"HOME": "\\ud800"}', b'x' * (runner.MAX_ENV_FILE + 1)):
                path.write_bytes(data)
                with self.assertRaises(runner.Unverified):
                    runner.environment_read(path)
            path.write_text('{}')
            with mock.patch.object(runner.os, "geteuid", return_value=os.geteuid() + 1), self.assertRaises(runner.Unverified):
                runner.environment_read(path)
            path.chmod(0o644)
            with self.assertRaises(runner.Unverified):
                runner.environment_read(path)
            alias = root / "alias"
            alias.symlink_to(path)
            fifo = root / "fifo"
            os.mkfifo(fifo, 0o600)
            for bad in (alias, fifo, root, Path("relative.json")):
                with self.assertRaises(runner.Unverified):
                    runner.environment_read(bad)

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
