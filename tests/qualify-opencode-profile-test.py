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
from copy import deepcopy
from pathlib import Path
from unittest.mock import mock_open, patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/qualify-opencode-profile.py"
SPEC = importlib.util.spec_from_file_location("qualify_profile", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
Q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(Q)

NAMESPACE_PROOF = {"status": "VERIFIED", "network_namespace_changed": True,
                   "user_namespace_changed": True, "nonroot_identity_preserved": True,
                   "interfaces": ["lo"], "loopback_up": True}

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
    # macOS injects this process metadata even with an explicit Popen env.
    # The probe's constructed environment remains tested independently below.
    runtime_metadata = {'__CF_USER_TEXT_ENCODING'} if sys.platform == 'darwin' else set()
    assert set(os.environ) - runtime_metadata <= {'PATH','LANG','LC_ALL','HOME','XDG_CONFIG_HOME',
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
        data = {'id': 'ses_fixture', 'agent': json.loads(args[6])['agent'],
                'location': {'directory': str(cwd)}, 'createdAt': 123}
        if mode == 'escaped_password_id':
            data['id'] = 'ses_' + os.environ['OPENCODE_PASSWORD']
            raw = json.dumps({'data': data})
            encoded = ''.join('\\u%04x' % ord(char) for char in os.environ['OPENCODE_PASSWORD'])
            print(raw.replace(os.environ['OPENCODE_PASSWORD'], encoded))
        else:
            reply(data)
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
        # Test-owned injection only: never change the unittest process namespace.
        namespace = patch.object(Q, "setup_private_namespace", return_value=dict(NAMESPACE_PROOF))
        self.namespace_setup = namespace.start()
        self.addCleanup(namespace.stop)
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
        with patch.object(Q, "CALL_TIMEOUT", 0.1), self.assertRaisesRegex(Q.Unverified, "command_timeout"):
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
        # Allow the real guest interpreter time to create the descendant under
        # CPU contention; still assert the owned inherited pipe hits a deadline.
        with patch.object(Q, "CALL_TIMEOUT", 1), self.assertRaisesRegex(Q.Unverified, "command_timeout"):
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
                patch.object(Q, "stop", side_effect=track), self.assertRaisesRegex(Q.Unverified, "interrupted"):
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
        self.assertEqual({p.name for p in self.output.iterdir()},
                         {"report.json", "manifest.json", "READY", "report.json.stage", "manifest.json.stage", "READY.stage"})
        report = json.loads(report_bytes)
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertEqual(report["publication"], "REQUIRES_VALID_READY")
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

    def test_unicode_escaped_password_id_never_reaches_permission_command(self):
        password = "a1b2c3d4" * 8
        with patch.object(Q.secrets, "token_hex", side_effect=[password, "f" * 24]):
            row = self.observe(mode="escaped_password_id")
        self.assertEqual(row["status"], "UNVERIFIED")
        self.assertEqual(row["reason"], "secret_in_response")
        self.assertFalse(any("/permission" in arg for command in row["commands"] for arg in command["argv"]))
        self.assertNotIn(password, json.dumps(row))
        self.assertFalse(row["effects"])

    def test_decoded_secret_scan_covers_nested_values_and_keys(self):
        for value in ({"outer": [{"ses_secret-value": 1}]}, {"outer": [{"id": "ses_secret-value"}]}):
            with self.subTest(value=value), self.assertRaisesRegex(Q.Unverified, "secret_in_response"):
                Q.exclude_secrets(value, ["secret-value"])

    def test_command_secret_guard_precedes_logging_and_launch(self):
        runner = self.runner()
        with patch.object(Q.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(Q.Unverified, "secret_in_response"):
                runner.run(["api", "/api/session/ses_" + runner.env["OPENCODE_PASSWORD"]])
            launch.assert_not_called()
        self.assertEqual(runner.commands, [])

    def publication_report(self):
        # Independently constructed, no observe_case or production profile helper.
        def returned(args, code=0):
            return {"argv": ["<binary>", *args], "status": "RETURNED", "exit_code": code,
                    "bytes": {"stdout": 100 if code == 0 else 0, "stderr": 0 if code == 0 else 19}}

        deny_read = [{"action": "*", "resource": "*", "effect": "deny"},
                     {"action": "read", "resource": "*", "effect": "allow"}]
        allow = [{"action": "*", "resource": "*", "effect": "allow"}]
        report = {"schema_version": 1, "status": "PROFILE_POLICY_OBSERVED", "runtime_cleanup": "removed",
                  "version": "2.0.32", "binary_sha256": "4" * 64,
                  "namespace": dict(NAMESPACE_PROOF), "launch_authorized": False,
                  "tool_dispatch_enforcement": "UNVERIFIED", "cases": [],
                  "commands": [returned(["--version"]), returned(["api", "--help"])]}
        for index, (case, status) in enumerate((("clean", "PROFILE_POLICY_OBSERVED"),
                                              ("conflict", "PROFILE_CONTAMINATION_DETECTED"),
                                              ("missing", "CANNOT_QUALIFY"), ("malformed", "CANNOT_QUALIFY"))):
            nonce = str(index + 1) * 24
            agent_id = "qualification-" + nonce
            port = str(18763 + index)
            prefix = ["api", "--server", "http://127.0.0.1:" + port]
            commands = [{"argv": ["<binary>", "serve", "--hostname", "127.0.0.1", "--port", port],
                         "status": "STARTED", "output": "discarded; may contain password"},
                        returned(prefix + ["GET", "/api/config"], 1),
                        returned(prefix + ["GET", "/api/config"])]
            documents = {}
            sources = []
            profiles = {"config/opencode/opencode.json": None, "project/opencode.json": None}
            row = {"case": case, "status": status, "launch_authorized": False,
                   "tool_dispatch_enforcement": "UNVERIFIED", "profile_contamination_detected": case == "conflict",
                   "server_cleanup": "process_group_killed", "commands": commands, "effects": {}}
            if case in ("clean", "conflict"):
                agent = {"mode": "primary", "description": "selected-" + nonce,
                         "system": "Synthetic policy fixture.", "permissions": deny_read}
                documents["config/opencode/opencode.json"] = {"agents": {agent_id: agent}}
                if case == "conflict":
                    documents["project/opencode.json"] = {"agents": {agent_id: {
                        **agent, "description": "selected-" + nonce + "-project", "permissions": allow}}}
                row["resolved_policy"] = {"defaults": allow + [
                    {"action": "read", "resource": "*.env", "effect": "ask"},
                    {"action": "read", "resource": "*.env.*", "effect": "ask"},
                    {"action": "read", "resource": "*.env.example", "effect": "allow"}],
                    "selected": deny_read + (allow if case == "conflict" else []),
                    "suffix": [{"action": "browser", "resource": "*", "effect": "deny"}]}
                commands.extend([returned(prefix + ["GET", "/api/agent/" + agent_id], 1),
                                 returned(prefix + ["GET", "/api/agent/" + agent_id]),
                                 returned(prefix + ["POST", "/api/session", "--data", json.dumps({"agent": agent_id})])])
                for action, resource in (("read", "/candidate/sample.py"), ("edit", "/candidate/sample.py"),
                                         ("shell", "printf fixture"), ("subagent", "fixture-agent")):
                    row["effects"][action] = "allow" if case == "conflict" or action == "read" else "deny"
                    body = {"id": "per_" + nonce + "_" + action, "action": action,
                            "resources": [resource], "agent": agent_id}
                    commands.append(returned(prefix + ["POST", "/api/session/ses_fixture/permission",
                                                       "--data", json.dumps(body)]))
            else:
                row.update(reason="selected_document_not_loaded", rejection_evidence="exact_source_inventory")
                if case == "malformed":
                    profiles["config/opencode/opencode.json"] = hashlib.sha256(b'{"agents":').hexdigest()
            for path, document in documents.items():
                profiles[path] = hashlib.sha256((json.dumps(document, indent=2, sort_keys=True) + "\n").encode()).hexdigest()
                sources.append({"type": "document", "path": path, "info_sha256": hashlib.sha256(
                    json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()})
            sources.append({"type": "directory", "path": "config/opencode"})
            commands.append(returned(prefix + ["GET", "/api/config"]))
            row.update(profiles_before=profiles, profiles_after=deepcopy(profiles),
                       sources_before=sources, sources_after=deepcopy(sources))
            report["cases"].append(row)
        return report

    def test_semantics_rejects_omitted_top_level_conditions(self):
        for key in ("version", "binary_sha256", "namespace", "runtime_cleanup", "commands", "cases",
                    "launch_authorized", "tool_dispatch_enforcement"):
            with self.subTest(key=key):
                report = self.publication_report()
                del report[key]
                with self.assertRaises(Q.Unverified):
                    Q.validate_success_report(report)

    def test_semantics_rejects_every_omitted_case_field(self):
        for index, row in enumerate(self.publication_report()["cases"]):
            for key in row:
                with self.subTest(case=index, key=key):
                    report = self.publication_report()
                    del report["cases"][index][key]
                    with self.assertRaises(Q.Unverified):
                        Q.validate_success_report(report)

    def test_semantics_rejects_mutated_success_claims(self):
        mutations = [
            lambda r: r.update(version="2.0.33"),
            lambda r: r.update(binary_sha256="4199ae"),
            lambda r: r.update(runtime_cleanup="failed"),
            lambda r: r["namespace"].update(loopback_up=1),
            lambda r: r["namespace"].update(network_namespace_changed=False),
            lambda r: r["namespace"].update(interfaces=["lo", "eth0"]),
            lambda r: r["cases"][1]["effects"].update(edit="deny"),
            lambda r: r["cases"][0]["effects"].update(read="deny"),
            lambda r: r["cases"][2]["effects"].update(read="allow"),
            lambda r: r["cases"][3].update(reason="startup_failed"),
            lambda r: r["cases"][3]["profiles_before"].update({"config/opencode/opencode.json": "0" * 64}),
            lambda r: r["cases"][0]["profiles_after"].update({"config/opencode/opencode.json": "0" * 64}),
            lambda r: r["cases"][0]["sources_before"][0].update(info_sha256="0" * 64),
            lambda r: r["cases"][0].update(server_cleanup="not_started"),
            lambda r: r["cases"][1]["resolved_policy"].update(selected=[{"action": "*", "resource": "*", "effect": "allow"}]),
            lambda r: r["cases"][0]["resolved_policy"]["defaults"].append({"action": "shell", "resource": "*", "effect": "allow"}),
            lambda r: r["cases"][0]["commands"][-2].update(exit_code=1),
            lambda r: r["cases"][0]["commands"][-1].update(exit_code=1),
            lambda r: r["cases"][0]["commands"][2]["bytes"].update(stdout=True),
            lambda r: r["cases"].__setitem__(3, deepcopy(r["cases"][2])),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                report = self.publication_report()
                mutate(report)
                with self.assertRaises(Q.Unverified):
                    Q.validate_success_report(report)

    def test_rehashed_invalid_conflict_still_fails_publication_inspection(self):
        self.output.mkdir()
        report = self.publication_report()
        report["cases"][1]["effects"]["edit"] = "deny"
        result = Q.publish_output(self.output, report, [])
        self.assertTrue((self.output / "READY").exists())
        self.assertEqual(result["status"], "UNVERIFIED")

    def test_semantics_namespace_fields_require_exact_types_and_coverage(self):
        for key in NAMESPACE_PROOF:
            with self.subTest(missing=key):
                report = self.publication_report()
                del report["namespace"][key]
                with self.assertRaises(Q.Unverified):
                    Q.validate_success_report(report)
        for key in ("loopback_up", "network_namespace_changed", "user_namespace_changed", "nonroot_identity_preserved"):
            for value in (1, "true", False, None):
                with self.subTest(key=key, value=value):
                    report = self.publication_report()
                    report["namespace"][key] = value
                    with self.assertRaises(Q.Unverified):
                        Q.validate_success_report(report)

    def test_semantics_equal_but_wrong_source_inventories_and_profile_hashes(self):
        for case_index in range(4):
            for fault in ("profile", "source_role", "directory", "duplicate"):
                with self.subTest(case=case_index, fault=fault):
                    report = self.publication_report()
                    row = report["cases"][case_index]
                    if fault == "profile":
                        for key in ("profiles_before", "profiles_after"):
                            row[key]["project/opencode.json"] = "0" * 64
                    else:
                        sources = row["sources_before"]
                        if fault == "source_role":
                            sources.append({"type": "document", "path": "project/opencode.json", "info_sha256": "0" * 64})
                        elif fault == "directory":
                            sources[-1]["path"] = "../outside"
                        else:
                            sources.append(deepcopy(sources[0]))
                        row["sources_after"] = deepcopy(sources)
                    with self.assertRaises(Q.Unverified):
                        Q.validate_success_report(report)

    def test_final_serialization_rejects_prior_case_password_before_writing(self):
        self.output.mkdir()
        report = self.publication_report()
        report["reason"] = "prior-case-secret"
        with self.assertRaisesRegex(Q.Unverified, "secret_in_response"):
            Q.publish_output(self.output, report, ["current-secret", "prior-case-secret"])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_completion_validation_and_inspection_cli(self):
        self.output.mkdir()
        result = Q.publish_output(self.output, self.publication_report(), [])
        self.assertEqual(result["status"], "PROFILE_POLICY_OBSERVED")
        self.assertEqual(json.loads((self.output / "report.json").read_text())["status"], "UNVERIFIED")
        stdout = io.StringIO()
        with redirect_stdout(stdout), patch.object(Q.subprocess, "Popen") as launch:
            code = Q.main(["--inspect-output", str(self.output)])
            launch.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["publication"], "COMPLETE")

    def test_inspection_rejects_execution_arguments(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            Q.main(["--inspect-output", str(self.output), "--binary", str(self.binary)])

    def test_publication_faults_never_leave_authoritative_success(self):
        real_fsync, real_link, real_digest = Q.os.fsync, Q.os.link, Q.digest_file
        for fault in ("hash", "manifest_fsync", "ready_fsync", "directory_fsync", "ready_link"):
            with self.subTest(fault=fault):
                output = self.root / fault
                output.mkdir()
                calls = 0

                def fsync(fd, fault=fault):
                    nonlocal calls
                    calls += 1
                    if calls == {"manifest_fsync": 2, "ready_fsync": 3, "directory_fsync": 4}.get(fault):
                        raise OSError("fixture fsync failure")
                    return real_fsync(fd)

                def link(source, target, fault=fault, **kwargs):
                    if fault == "ready_link" and Path(target).name == "READY":
                        raise OSError("fixture ready failure")
                    return real_link(source, target, **kwargs)

                def digest(path, *args, fault=fault):
                    if fault == "hash":
                        raise Q.Unverified("fixture_hash_failure")
                    return real_digest(path, *args)

                with patch.object(Q.os, "fsync", side_effect=fsync), patch.object(Q.os, "link", side_effect=link), \
                        patch.object(Q, "digest_file", side_effect=digest), self.assertRaises((OSError, Q.Unverified)):
                    Q.publish_output(output, self.publication_report(), [])
                self.assertFalse((output / "READY").exists())
                self.assertEqual(Q.validate_output(output)["status"], "UNVERIFIED")
                for path in output.glob("report.json*"):
                    self.assertEqual(json.loads(path.read_text())["status"], "UNVERIFIED")
                before = {p.name: p.read_bytes() for p in output.iterdir()}
                with self.assertRaises(FileExistsError):
                    Q.publish_output(output, self.publication_report(), [])
                self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, before)

    def test_validator_rejects_missing_corrupt_or_mismatched_artifacts(self):
        self.assertEqual(Q.validate_output(self.output)["status"], "UNVERIFIED")
        for name in ("READY", "manifest.json", "report.json"):
            for change in ("missing", "corrupt", "tamper"):
                with self.subTest(name=name, change=change):
                    output = self.root / (name + "-" + change)
                    output.mkdir()
                    Q.publish_output(output, self.publication_report(), [])
                    path = output / name
                    if change == "missing":
                        path.unlink()
                    elif change == "corrupt":
                        path.write_text("{")
                    else:
                        path.write_bytes(path.read_bytes() + b" ")
                        if name == "READY":
                            value = json.loads(path.read_text())
                            value["report_sha256"] = "0" * 64
                            path.write_text(json.dumps(value))
                    self.assertEqual(Q.validate_output(output)["status"], "UNVERIFIED")

    def test_main_reports_failure_if_ready_publication_fails(self):
        self.mode.write_text("malformed_ignored")
        real_link = Q.os.link

        def link(source, target, **kwargs):
            if Path(target).name == "READY":
                raise OSError("fixture ready failure")
            return real_link(source, target, **kwargs)

        with patch.object(Q.os, "link", side_effect=link):
            code, summary = self.invoke()
        self.assertEqual(code, 3)
        self.assertEqual(summary["status"], "UNVERIFIED")
        self.assertEqual(summary["reason"], "publication_failed")
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["observation_status"], "PROFILE_POLICY_OBSERVED")
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertEqual(Q.validate_output(self.output)["status"], "UNVERIFIED")

    def test_password_excluded_from_all_published_artifacts(self):
        self.mode.write_text("escaped_password_id")
        passwords = [format(index, "064x") for index in range(1, 5)]
        tokens = [token for password in passwords for token in (password, "f" * 24)]
        with patch.object(Q.secrets, "token_hex", side_effect=tokens):
            code, summary = self.invoke()
        self.assertEqual(code, 3)
        self.assertEqual(summary["status"], "UNVERIFIED")
        for path in self.output.iterdir():
            if path.is_file():
                raw = path.read_bytes()
                for password in passwords:
                    self.assertNotIn(password.encode(), raw)
                Q.exclude_secrets(json.loads(raw), passwords)

    def test_validator_refuses_evidence_symlink(self):
        self.output.mkdir()
        Q.publish_output(self.output, self.publication_report(), [])
        (self.output / "READY").unlink()
        (self.output / "READY").symlink_to(self.output / "READY.stage")
        self.assertEqual(Q.validate_output(self.output)["status"], "UNVERIFIED")

    def test_namespace_failure_precedes_all_runtime_and_auth_work(self):
        self.namespace_setup.side_effect = Q.Unverified("namespace_creation_refused")
        with patch.object(Q.subprocess, "Popen") as launch, patch.object(Q.secrets, "token_hex") as password:
            code, summary = self.invoke()
            launch.assert_not_called()
            password.assert_not_called()
        self.assertEqual((code, summary["reason"]), (3, "namespace_creation_refused"))
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["commands"], [])
        self.assertEqual(report["cases"], [])

    def test_version_child_requires_namespace_setup_first(self):
        self.mode.write_text("version")
        original = Q.Runner.run

        def run(runner, args):
            self.namespace_setup.assert_called_once_with()
            return original(runner, args)

        with patch.object(Q.Runner, "run", run):
            self.invoke()

    def test_inspection_never_creates_namespace(self):
        self.output.mkdir()
        Q.publish_output(self.output, self.publication_report(), [])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(Q.main(["--inspect-output", str(self.output)]), 0)
        self.namespace_setup.assert_not_called()

    def test_publication_without_namespace_proof_cannot_validate_success(self):
        self.output.mkdir()
        report = self.publication_report()
        del report["namespace"]
        self.assertEqual(Q.publish_output(self.output, report, [])["status"], "UNVERIFIED")


class NamespaceSetupTest(unittest.TestCase):
    """Exercise ordering/refusal without creating sockets or real namespaces."""

    def setUp(self):
        for name, value in (("getuid", 502), ("geteuid", 502), ("getgid", 20), ("getegid", 20)):
            handle = patch.object(Q.os, name, return_value=value)
            handle.start()
            self.addCleanup(handle.stop)
        platform = patch.object(Q.sys, "platform", "linux")
        platform.start()
        self.addCleanup(platform.stop)

    def test_refused_unshare_never_maps_or_opens_socket(self):
        with patch.object(Q.os, "readlink", side_effect=["net:[1]", "user:[1]"]), \
                patch.object(Q, "unshare_user_network", side_effect=PermissionError()), \
                patch.object(Q, "write_namespace_map") as maps, \
                patch.object(Q, "enable_private_loopback") as loopback:
            with self.assertRaisesRegex(Q.Unverified, "namespace_creation_refused"):
                Q.setup_private_namespace()
            maps.assert_not_called()
            loopback.assert_not_called()

    def test_unchanged_namespace_refused_before_socket(self):
        with patch.object(Q.os, "readlink", side_effect=["net:[1]", "user:[1]", "net:[1]", "user:[2]"]), \
                patch.object(Q, "unshare_user_network"), patch.object(Q, "write_namespace_map") as maps, \
                patch.object(Q, "enable_private_loopback") as loopback:
            with self.assertRaisesRegex(Q.Unverified, "namespace_not_fresh"):
                Q.setup_private_namespace()
            maps.assert_not_called()
            loopback.assert_not_called()

    def test_maps_original_nonzero_ids_before_loopback(self):
        events = []
        maps = {"uid_map": "502 502 1\n", "gid_map": "20 20 1\n", "setgroups": "deny\n"}

        def read_map(path, **kwargs):
            return mock_open(read_data=maps[Path(path).name])()

        with patch.object(Q.os, "readlink", side_effect=["net:[1]", "user:[1]", "net:[2]", "user:[2]"]), \
                patch.object(Q, "unshare_user_network", side_effect=lambda: events.append("unshare")), \
                patch.object(Q, "write_namespace_map", side_effect=lambda name, value: events.append((name, value))), \
                patch("builtins.open", side_effect=read_map), \
                patch.object(Q, "enable_private_loopback", side_effect=lambda: events.append("loopback")):
            self.assertEqual(Q.setup_private_namespace(), NAMESPACE_PROOF)
        self.assertEqual(events, ["unshare", ("setgroups", "deny\n"), ("uid_map", "502 502 1\n"),
                                  ("gid_map", "20 20 1\n"), "loopback"])

    def test_mapping_failure_never_opens_socket(self):
        with patch.object(Q.os, "readlink", side_effect=["net:[1]", "user:[1]", "net:[2]", "user:[2]"]), \
                patch.object(Q, "unshare_user_network"), \
                patch.object(Q, "write_namespace_map", side_effect=PermissionError()), \
                patch.object(Q, "enable_private_loopback") as loopback:
            with self.assertRaisesRegex(Q.Unverified, "namespace_setup_failed"):
                Q.setup_private_namespace()
            loopback.assert_not_called()

    def test_root_identity_refused_before_unshare(self):
        with patch.object(Q.os, "getuid", return_value=0), patch.object(Q, "unshare_user_network") as unshare:
            with self.assertRaisesRegex(Q.Unverified, "namespace_nonroot_identity_required"):
                Q.setup_private_namespace()
            unshare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
