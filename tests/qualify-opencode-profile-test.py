#!/usr/bin/env python3
"""Fake-CLI policy qualification tests. Execute only in an isolated guest.

No installed OpenCode binary, network connection, model or provider is used.
The fake wire schemas test the narrow adapters, not runtime compatibility.
"""

import sys

if not sys.flags.isolated or not sys.dont_write_bytecode:
    raise SystemExit("Run this guest test with python3 -I -B")

import hashlib
import importlib.util
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/qualify-opencode-profile.py"
SPEC = importlib.util.spec_from_file_location("qualify_profile", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
Q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(Q)

# Launched as a real child with the driver's allowlisted environment. Fixture
# configuration is private file data, not an environment escape hatch.
FAKE = r'''
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
import time

mode = Path(__file__).with_suffix('.mode').read_text()
args = sys.argv[1:]
cwd = Path.cwd()
assert not (cwd / '.git').exists()
def reply(data):
    print(json.dumps({'data': data}))

if args == ['--version']:
    print('wrong' if mode == 'version' else '2.0.32' if mode == 'bare_version' else 'opencode v2.0.32')
elif args == ['api', '--help']:
    print('--standalone' if mode == 'help' else '--standalone --server')
elif args[0] == 'serve':
    assert args[1:4] == ['--hostname', '127.0.0.1', '--port']
    if mode == 'server_exit':
        sys.exit(1)
    (cwd / 'server.pid').write_text(str(os.getpid()))
    # Ensure a printed synthetic secret is discarded, never retained.
    print('server password ' + os.environ['OPENCODE_PASSWORD'], flush=True)
    time.sleep(60)
elif args[0] == 'api':
    assert args[1] == '--server' and args[2].startswith('http://127.0.0.1:')
    assert set(os.environ) <= {'PATH','LANG','LC_ALL','HOME','XDG_CONFIG_HOME',
        'XDG_DATA_HOME','XDG_CACHE_HOME','XDG_STATE_HOME','XDG_RUNTIME_DIR',
        'TMPDIR','OPENCODE_PASSWORD'}
    assert 'GH_TOKEN' not in os.environ and 'HTTP_PROXY' not in os.environ
    if mode == 'timeout':
        time.sleep(60)
    if mode == 'flood':
        os.write(1, b'x' * 400000)
        sys.exit(0)
    if mode == 'stderr_flood':
        os.write(2, b'x' * 400000)
        sys.exit(0)
    if mode == 'secret':
        print(os.environ['OPENCODE_PASSWORD'])
        sys.exit(0)
    if mode == 'descendant':
        child = subprocess.Popen([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(60)'])
        (cwd / 'child.pid').write_text(str(child.pid))
        sys.exit(0)
    if mode == 'failure':
        print('credential-shaped private failure', file=sys.stderr)
        sys.exit(1)
    method, path = args[3:5]
    config = Path(os.environ['XDG_CONFIG_HOME']) / 'opencode/opencode.json'
    project = cwd / 'opencode.json'
    docs = [str(p) for p in (config, project) if p.exists()]
    try:
        agents = json.loads(config.read_text())['agents'] if config.exists() else {}
        if project.exists():
            for agent_id, project_agent in json.loads(project.read_text())['agents'].items():
                selected = agents.get(agent_id, {})
                permissions = selected.get('permissions', []) + project_agent.get('permissions', [])
                if mode == 'conflict_overwrite':
                    permissions = project_agent.get('permissions', [])
                elif mode == 'conflict_reversed':
                    permissions = project_agent.get('permissions', []) + selected.get('permissions', [])
                agents[agent_id] = {**selected, **project_agent, 'permissions': permissions}
    except ValueError:
        # The driver's rejection of an unknown error shape is deliberate.
        if mode == 'malformed_ignored':
            agents = {}
            docs = []
        else:
            print(json.dumps({'error': 'fixture_config_parse_error'}))
            sys.exit(1)
    if path == '/api/config':
        if mode == 'unknown_schema':
            reply({'source': {'docs': [{'path': p} for p in docs], 'dirs': []}})
        else:
            sources = [{'type': 'document', 'path': p, 'info': json.loads(Path(p).read_text())} for p in docs]
            sources += [{'type': 'directory', 'path': p} for p in [str(config.parent), str(cwd)]]
            if mode == 'foreign_source':
                sources.append({'type': 'document', 'path': '/unrelated/opencode.json', 'info': {}})
            if mode == 'wrong_content':
                sources[0]['info'] = {'agents': {}}
            print(json.dumps(sources))
    elif path.startswith('/api/agent/'):
        attempts = cwd / 'agent-attempts'
        count = int(attempts.read_text()) + 1 if attempts.exists() else 1
        attempts.write_text(str(count))
        if mode == 'agent_failure' or (mode == 'agent_retry' and count < 3):
            sys.exit(1)
        if mode == 'agent_invalid_json':
            print('invalid-json')
            sys.exit(0)
        agent_id = path.rsplit('/', 1)[1]
        agent = agents.get(agent_id)
        if mode == 'empty_agent':
            agent = None
        if mode == 'mutate' and config.exists():
            config.write_text(config.read_text() + ' ')
        defaults = [{'action': '*', 'resource': '*', 'effect': 'allow'},
                    {'action': 'read', 'resource': '*.env', 'effect': 'ask'},
                    {'action': 'read', 'resource': '*.env.*', 'effect': 'ask'},
                    {'action': 'read', 'resource': '*.env.example', 'effect': 'allow'}]
        if mode == 'unknown_default':
            defaults.append({'action': 'shell', 'resource': '*', 'effect': 'allow'})
        data = (dict(agent, id=agent_id, name=agent_id, hidden=False,
                     request={'settings': {}, 'headers': {}, 'body': {}},
                     permissions=defaults + agent['permissions'] +
                     [{'action': 'browser', 'resource': '*', 'effect': 'deny'}]) if agent else None)
        print(json.dumps({'location': {'directory': str(cwd)}, 'data': data}))
    elif path == '/api/session':
        reply({'id': 'ses_fixture', 'agent': json.loads(args[6])['agent'],
               'location': {'directory': str(cwd)}, 'createdAt': 123})
    elif path == '/api/session/ses_fixture/permission':
        request = json.loads(args[6])
        action = request['action']
        effect = 'deny'
        for rule in agents[request['agent']]['permissions']:
            if fnmatch.fnmatchcase(action, rule['action']) and all(
                    fnmatch.fnmatchcase(resource, rule['resource']) for resource in request['resources']):
                effect = rule['effect']
        reply({'id': request['id'], 'effect': 'deny' if mode == 'all_deny' else effect})
    else:
        sys.exit(2)
else:
    sys.exit(2)
'''


class QualificationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="profile-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.binary = self.root / "fake-opencode"
        self.binary.write_text("#!" + sys.executable + " -IB\n" + FAKE)
        self.binary.chmod(0o700)
        # The harness tmpfs is noexec. Dispatch fixture bytes through the guest
        # interpreter; keep real Popen, pipes, environment and process groups.
        real_popen = Q.subprocess.Popen

        def fixture_popen(args, **kwargs):
            if args[0] == str(self.binary):
                args = [sys.executable, "-I", "-B", *args]
            return real_popen(args, **kwargs)

        dispatch = patch.object(Q.subprocess, "Popen", side_effect=fixture_popen)
        dispatch.start()
        self.addCleanup(dispatch.stop)
        self.mode = self.binary.with_suffix(".mode")
        self.mode.write_text("normal")
        self.digest = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        self.output = self.root / "output"

    def args(self, *more):
        return ["--isolated-guest", "--binary", str(self.binary), "--expected-sha", self.digest,
                "--output", str(self.output), "--timeout", "30", *more]

    def invoke(self, *args):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = Q.main(self.args(*args))
        return code, json.loads(stdout.getvalue())

    def observe(self, case="clean", mode="normal"):
        self.mode.write_text(mode)
        self.output.mkdir(exist_ok=True)
        return Q.observe_case(self.binary, self.output, case, 28763, time.monotonic() + 15)

    def runner(self, mode="normal"):
        self.mode.write_text(mode)
        root = self.root / "runner"
        root.mkdir()
        env = Q.environment(root)
        env["OPENCODE_PASSWORD"] = "synthetic-unique-password-for-test"
        return Q.Runner(self.binary, root, env, time.monotonic() + 5, [])

    def test_clean_shared_server_positive_control(self):
        row = self.observe()
        self.assertEqual(row["status"], "PROFILE_POLICY_OBSERVED", row)
        self.assertEqual(row["effects"], {"read": "allow", "edit": "deny", "shell": "deny", "subagent": "deny"})
        self.assertEqual(row["profiles_before"], row["profiles_after"])
        self.assertEqual(row["sources_before"], row["sources_after"])
        self.assertEqual(row["resolved_policy"], {
            "defaults": [{"action": "*", "resource": "*", "effect": "allow"},
                         {"action": "read", "resource": "*.env", "effect": "ask"},
                         {"action": "read", "resource": "*.env.*", "effect": "ask"},
                         {"action": "read", "resource": "*.env.example", "effect": "allow"}],
            "selected": [{"action": "*", "resource": "*", "effect": "deny"},
                         {"action": "read", "resource": "*", "effect": "allow"}],
            "suffix": [{"action": "browser", "resource": "*", "effect": "deny"}],
        })
        self.assertFalse(row["launch_authorized"])
        self.assertEqual(row["tool_dispatch_enforcement"], "UNVERIFIED")
        argv = [r["argv"] for r in row["commands"]]
        self.assertTrue(all("--server" in a for a in argv if a[1] == "api"))
        self.assertNotIn("--standalone", str(argv))
        self.assertNotIn(" run ", str(argv))

    def test_conflict_reports_contamination(self):
        row = self.observe("conflict")
        self.assertEqual(row["status"], "PROFILE_CONTAMINATION_DETECTED", row)
        self.assertTrue(row["profile_contamination_detected"])
        self.assertEqual(set(row["effects"].values()), {"allow"})
        self.assertEqual(row["resolved_policy"]["selected"], [
            {"action": "*", "resource": "*", "effect": "deny"},
            {"action": "read", "resource": "*", "effect": "allow"},
            {"action": "*", "resource": "*", "effect": "allow"},
        ])
        self.assertEqual(row["resolved_policy"]["defaults"][-2:], [
            {"action": "read", "resource": "*.env.*", "effect": "ask"},
            {"action": "read", "resource": "*.env.example", "effect": "allow"},
        ])
        self.assertEqual(row["resolved_policy"]["suffix"], [
            {"action": "browser", "resource": "*", "effect": "deny"},
        ])

    def test_conflict_overwrite_is_not_measured_merge(self):
        row = self.observe("conflict", "conflict_overwrite")
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertEqual(row["reason"], "selected_rules_mismatch")
        self.assertFalse(row["effects"])

    def test_conflict_reordered_rules_are_refused(self):
        row = self.observe("conflict", "conflict_reversed")
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertEqual(row["reason"], "selected_rules_mismatch")

    def test_agent_cli_failures_retry_then_positive_control(self):
        row = self.observe(mode="agent_retry")
        self.assertEqual(row["status"], "PROFILE_POLICY_OBSERVED", row)
        calls = [r for r in row["commands"] if any("/api/agent/" in a for a in r["argv"])]
        self.assertEqual([r["exit_code"] for r in calls], [1, 1, 0])
        self.assertEqual(row["effects"], {"read": "allow", "edit": "deny", "shell": "deny", "subagent": "deny"})

    def test_agent_cli_failures_stop_at_retry_bound(self):
        row = self.observe(mode="agent_failure")
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertEqual(row["reason"], "api_cli_failed")
        calls = [r for r in row["commands"] if any("/api/agent/" in a for a in r["argv"])]
        self.assertEqual(len(calls), Q.AGENT_ATTEMPTS)
        self.assertFalse(row["effects"])

    def test_agent_json_failure_is_not_retried(self):
        row = self.observe(mode="agent_invalid_json")
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertEqual(row["reason"], "invalid_json")
        calls = [r for r in row["commands"] if any("/api/agent/" in a for a in r["argv"])]
        self.assertEqual(len(calls), 1)

    def test_all_deny_never_positive_control(self):
        row = self.observe(mode="all_deny")
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertEqual(row["reason"], "policy_positive_control_failed")

    def test_missing_selected_cannot_qualify(self):
        row = self.observe("missing")
        self.assertEqual(row["status"], "CANNOT_QUALIFY", row)
        self.assertFalse(row["effects"])

    def test_unknown_malformed_error_is_not_measured_rejection(self):
        row = self.observe("malformed")
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertEqual(row["reason"], "api_cli_failed")
        self.assertLessEqual(len(row["commands"]), 1 + Q.READY_ATTEMPTS)

    def test_empty_agent_is_bounded_and_unverified(self):
        row = self.observe(mode="empty_agent")
        self.assertEqual(row["status"], "UNVERIFIED")
        calls = [r for r in row["commands"] if any("/api/agent/" in a for a in r["argv"])]
        self.assertEqual(len(calls), Q.AGENT_ATTEMPTS)

    def test_unknown_source_schema_refused(self):
        row = self.observe(mode="unknown_schema")
        self.assertEqual(row["reason"], "unsupported_config_schema")

    def test_foreign_sources_refused_without_opening(self):
        row = self.observe(mode="foreign_source")
        self.assertEqual(row["reason"], "source_inventory_mismatch")

    def test_profile_mutation_invalidates_observation(self):
        row = self.observe(mode="mutate")
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertEqual(row["reason"], "profile_changed")

    def test_early_owned_server_exit_refused(self):
        row = self.observe(mode="server_exit")
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertEqual(row["reason"], "owned_server_exited")

    def test_cli_deadline(self):
        runner = self.runner("timeout")
        with patch.object(Q, "CALL_TIMEOUT", 0.1):
            with self.assertRaisesRegex(Q.Unverified, "command_timeout"):
                runner.api(28763, "GET", "/api/config")
        self.assertEqual(runner.commands[0]["status"], "UNVERIFIED")

    def test_stdout_and_stderr_are_bounded(self):
        for mode in ("flood", "stderr_flood"):
            with self.subTest(mode=mode):
                self.mode.write_text(mode)
                root = self.root / mode
                root.mkdir()
                runner = Q.Runner(self.binary, root, Q.environment(root), time.monotonic() + 3, [])
                with self.assertRaisesRegex(Q.Unverified, "stream_limit"):
                    runner.api(28763, "GET", "/api/config")

    def test_password_response_not_retained(self):
        runner = self.runner("secret")
        with self.assertRaisesRegex(Q.Unverified, "secret_in_response"):
            runner.api(28763, "GET", "/api/config")
        self.assertNotIn(runner.env["OPENCODE_PASSWORD"], json.dumps(runner.commands))

    def test_environment_does_not_inherit_credentials_or_proxy(self):
        with patch.dict(os.environ, {"GH_TOKEN": "never-forward-this", "HTTP_PROXY": "http://invalid",
                                    "OPENCODE_CONFIG": "/unrelated/config"}):
            row = self.observe()
        self.assertEqual(row["status"], "PROFILE_POLICY_OBSERVED", row)
        self.assertNotIn("never-forward-this", json.dumps(row))

    def test_inherited_pipe_descendant_is_killed(self):
        runner = self.runner("descendant")
        with patch.object(Q, "CALL_TIMEOUT", 0.2):
            with self.assertRaisesRegex(Q.Unverified, "command_timeout"):
                runner.api(28763, "GET", "/api/config")
        pid = int((runner.cwd / "child.pid").read_text())
        # Linux /proc is guest-local and checks only the child created by this test.
        proc = Path(f"/proc/{pid}/stat")
        end = time.monotonic() + 1
        while proc.exists() and time.monotonic() < end:
            if proc.read_text().split()[2] == "Z":
                break
            time.sleep(0.01)
        if proc.exists():
            self.assertEqual(proc.read_text().split()[2], "Z")

    def test_no_server_left_after_success(self):
        self.observe()
        pid = int((self.output / "clean/project/server.pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_api_schema_rejections(self):
        for raw in (b'{"data":{},"data":{}}',
                    b'{"data":NaN}', b'not-json', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises(Q.Unverified):
                Q.parse_json(raw)
        for raw in ({}, {"data": []}, [{"type": "directory", "path": "/a", "extra": True}]):
            with self.subTest(raw=raw), self.assertRaises(Q.Unverified):
                Q.parse_config(raw)

    def test_effect_schema_and_identity(self):
        for data in ({"id": "per_wrong", "effect": "deny"}, {"id": "per_ok", "effect": True},
                     {"id": "per_ok", "effect": "unknown"}, {"id": "per_ok", "effect": "deny", "x": 1}):
            with self.subTest(data=data), self.assertRaises(Q.Unverified):
                Q.parse_permission({"data": data}, "per_ok")

    def test_session_identifier_refuses_paths_and_non_strings(self):
        for value in ("../../other", "ses_a/b", "ses_", "ses_a?b", 1, None):
            with self.subTest(value=value), self.assertRaises(Q.Unverified):
                Q.identifier({"id": value}, "ses_")

    def test_agent_must_match_marker_source_and_rules_schema(self):
        valid = {"id": "agent", "name": "agent", "description": "marker", "permissions": Q.RULES,
                 "request": {"settings": {}, "headers": {}, "body": {}}, "hidden": False,
                 "system": "Synthetic policy fixture.", "mode": "primary"}
        for field, value in (("id", "other"), ("description", "other"), ("source", "defaults"),
                             ("permissions", []), ("permissions", [{"effect": "deny"}])):
            with self.subTest(field=field), self.assertRaises(Q.Unverified):
                Q.parse_agent({"location": {"directory": "/fixture"}, "data": {**valid, field: value}},
                              "agent", "marker", Path("/fixture"), Q.RULES)

    def test_malformed_omitted_from_exact_sources_rejects_selection(self):
        row = self.observe("malformed", "malformed_ignored")
        self.assertEqual(row["status"], "CANNOT_QUALIFY", row)
        self.assertEqual(row["rejection_evidence"], "exact_source_inventory")

    def test_source_content_must_equal_selected_config(self):
        row = self.observe(mode="wrong_content")
        self.assertEqual(row["reason"], "source_content_mismatch")

    def test_unrecognized_default_before_selected_refused(self):
        row = self.observe(mode="unknown_default")
        self.assertEqual(row["reason"], "unknown_default_permission")

    def test_session_bound_to_exact_agent_and_location(self):
        for data in ({"id": "ses_ok", "agent": "other", "location": {"directory": "/fixture"}},
                     {"id": "ses_ok", "agent": "agent", "location": {"directory": "/other"}}):
            with self.subTest(data=data), self.assertRaises(Q.Unverified):
                Q.parse_session({"data": data}, "agent", Path("/fixture"))

    def test_agent_location_and_unknown_trailing_rules_refused(self):
        data = {"id": "agent", "name": "agent", "description": "marker", "permissions": Q.RULES,
                "request": {"settings": {}, "headers": {}, "body": {}}, "hidden": False,
                "system": "Synthetic policy fixture.", "mode": "primary"}
        with self.assertRaisesRegex(Q.Unverified, "unsupported_agent_envelope"):
            Q.parse_agent({"location": {"directory": "/other"}, "data": data},
                          "agent", "marker", Path("/fixture"), Q.RULES)
        data["permissions"] = Q.RULES + [{"action": "shell", "resource": "*", "effect": "allow"}]
        with self.assertRaisesRegex(Q.Unverified, "selected_rules_mismatch"):
            Q.parse_agent({"location": {"directory": "/fixture"}, "data": data},
                          "agent", "marker", Path("/fixture"), Q.RULES)

    def test_duplicate_sources_and_cross_endpoint_envelopes_refused(self):
        row = {"type": "directory", "path": "/fixture"}
        with self.assertRaises(Q.Unverified):
            Q.parse_config([row, row])
        with self.assertRaises(Q.Unverified):
            Q.parse_permission({"location": {}, "data": {"id": "per_ok", "effect": "deny"}}, "per_ok")
        with self.assertRaises(Q.Unverified):
            Q.parse_session([], "agent", Path("/fixture"))

    def test_full_matrix_requires_clean_control_and_known_degraded_evidence(self):
        self.mode.write_text("malformed_ignored")
        code, summary = self.invoke()
        self.assertEqual(code, 0, summary)
        self.assertEqual(summary["status"], "PROFILE_POLICY_OBSERVED")

    def test_verdict_requires_all_distinct_cases(self):
        rows = [{"case": "clean", "status": "PROFILE_POLICY_OBSERVED"},
                {"case": "conflict", "status": "PROFILE_CONTAMINATION_DETECTED"},
                {"case": "missing", "status": "CANNOT_QUALIFY"},
                {"case": "malformed", "status": "CANNOT_QUALIFY"}]
        self.assertEqual(Q.verdict(rows), "PROFILE_POLICY_OBSERVED")
        for altered in ([], rows[:1], rows[:-1], rows + rows[:1], rows[:-1] + [rows[0]],
                        rows[:-1] + [{"case": "malformed", "status": "UNVERIFIED"}]):
            self.assertEqual(Q.verdict(altered), "UNVERIFIED")

    def test_cli_refuses_unbounded_inputs(self):
        for args in (("--timeout", "0"), ("--timeout", "181"), ("--timeout", "nan"),
                     ("--port", "80"), ("--port", "65533"), ("--expected-sha", "4199ae"),
                     ("--output", "relative"), ("--binary", "relative")):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                Q.arguments(self.args(*args))

    def test_guest_flag_required(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            Q.arguments(self.args()[1:])

    def test_hash_verified_before_any_execution(self):
        code, summary = self.invoke("--expected-sha", "0" * 64)
        self.assertEqual(code, 3)
        self.assertEqual(summary["reason"], "binary_hash_mismatch")
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["commands"], [])

    def test_version_verified_before_server_launch(self):
        self.mode.write_text("version")
        code, summary = self.invoke()
        self.assertEqual((code, summary["reason"]), (3, "unsupported_version"))
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(len(report["commands"]), 1)
        self.assertFalse(report["cases"])

    def test_bare_version_is_not_measured_version_output(self):
        self.mode.write_text("bare_version")
        code, summary = self.invoke()
        self.assertEqual((code, summary["reason"]), (3, "unsupported_version"))

    def test_missing_server_cli_option_refused(self):
        self.mode.write_text("help")
        code, summary = self.invoke()
        self.assertEqual((code, summary["reason"]), (3, "unsupported_api_cli"))

    def test_cli_failure_retains_codes_not_error_text(self):
        row = self.observe(mode="failure")
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertNotIn("credential-shaped", json.dumps(row))

    def test_expired_deadline_prevents_process_launch(self):
        runner = self.runner()
        runner.deadline = time.monotonic() - 1
        with patch.object(Q.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(Q.Unverified, "deadline"):
                runner.run(["--version"])
            launch.assert_not_called()

    def test_signal_interruption_cleans_cli_group(self):
        runner = self.runner("timeout")
        # Interrupt the selector after the real child is admitted.
        real_stop = Q.stop
        stopped = []
        def track(process):
            real_stop(process)
            stopped.append(process)
        with patch.object(Q.selectors.DefaultSelector, "select", side_effect=Q.Unverified("interrupted")), \
                patch.object(Q, "stop", side_effect=track):
            with self.assertRaisesRegex(Q.Unverified, "interrupted"):
                runner.api(28763, "GET", "/api/config")
        self.assertEqual(len(stopped), 1)
        self.assertIsNotNone(stopped[0].poll())

    def test_reused_output_refused_and_not_overwritten(self):
        self.output.mkdir()
        (self.output / "report.json").write_text("preserve")
        code, _ = self.invoke()
        self.assertEqual(code, 3)
        self.assertEqual((self.output / "report.json").read_text(), "preserve")

    def test_binary_link_refused(self):
        link = self.root / "link"
        link.symlink_to(self.binary)
        code, summary = self.invoke("--binary", str(link))
        self.assertEqual((code, summary["reason"]), (3, "binary_symlink"))

    def test_manifest_binds_report_and_no_raw_logs(self):
        code, summary = self.invoke()
        self.assertEqual(code, 3)  # Unknown malformed runtime error cannot pass.
        self.assertEqual(summary["case_count"], 4)
        manifest = json.loads((self.output / "manifest.json").read_text())
        report_bytes = (self.output / "report.json").read_bytes()
        self.assertEqual(manifest["files"]["report.json"], hashlib.sha256(report_bytes).hexdigest())
        self.assertFalse(manifest["raw_streams_retained"])
        self.assertEqual(manifest["runtime_cleanup"], "removed")
        self.assertEqual({p.name for p in self.output.iterdir()}, {"report.json", "manifest.json"})
        self.assertFalse(list(self.output.rglob("*.log")))
        self.assertNotIn(b"server password ", report_bytes)

    def test_file_read_is_bounded_and_rejects_symlinks(self):
        path = self.root / "data"
        path.write_bytes(b"abcd")
        with self.assertRaisesRegex(Q.Unverified, "unsafe_or_oversized_file"):
            Q.digest_file(path, 3, time.monotonic() + 1)
        with self.assertRaisesRegex(Q.Unverified, "deadline"):
            Q.digest_file(path, 10, time.monotonic() - 1)
        link = self.root / "data-link"
        link.symlink_to(path)
        with self.assertRaises(OSError):
            Q.digest_file(link, 10, time.monotonic() + 1)


if __name__ == "__main__":
    unittest.main()
