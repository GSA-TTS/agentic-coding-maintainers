#!/usr/bin/env python3
"""Meaningful static-preflight fixtures; execute only in the sandbox."""

from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/review-workspace-preflight.py"
SPEC = importlib.util.spec_from_file_location("preflight", SCRIPT)
P = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = P
SPEC.loader.exec_module(P)


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    return path


def manifest(root):
    base = root / P.ORCHESTRATOR
    rows = []
    for path in sorted(base.rglob("*")):
        if path.is_file() and path.name != "CANONICAL-SHA256SUMS":
            rows.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  ./" + path.relative_to(base).as_posix())
    put(root, P.MANIFEST, "\n".join(rows) + "\n")


def task(schema=2):
    raw = {key: "" for key in ("owner", "repo", "branch", "worktree", "base_sha", "next_action")}
    raw.update({key: [] for key in ("owned_paths", "restricted_paths", "acceptance_criteria",
                                   "dependencies", "reviewers", "findings", "validation")})
    raw.update(schema_version=schema, task_id="example", state="Done", scope="fixture",
               scope_key=hashlib.sha256(b"fixture").hexdigest(), kind="review", revision=1,
               created_at="2026-10-30T00:00:00Z", updated_at="2026-10-30T00:00:00Z", worker=None,
               leases={"global_slot": None, "implementation_lane": None, "scope_token": "a" * 32})
    if schema == 2:
        raw.update(tracker_type="none", tracker_number=0, head_sha="", reviewed_sha="",
                   transition_intent=None, rework_count=0)
    return raw


def reservation(group):
    raw = {"token": "d" * 32}
    if group in {"slots", "implementation"}:
        raw.update(task_id="example", owner="fixture", pid=123, process_start="fixture",
                   worker_id="b" * 32, hostname="fixture.invalid", created_at="fixture")
    else:
        raw["schema_version"] = 2
        if group == "scopes":
            raw.update(task_id="example", scope="fixture")
        else:
            raw.update(pid=123, hostname="fixture.invalid", created_at="fixture")
    return raw


class PreflightTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="static-preflight-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source, self.consumer = self.root / "source", self.root / "consumer"
        for skill in P.SKILLS:
            put(self.source, P.SKILL_ROOT + skill + "/SKILL.md", "fixture skill\n")
            put(self.source, P.SKILL_ROOT + skill + "/run.sh", "not executable code\n").chmod(0o755)
        for path in (P.ORCHESTRATOR + "/profiles/opencode-v1/reviewer.md", ".opencode/agents/reviewer.md"):
            put(self.source, path, "profile\n")
        for path in (P.ORCHESTRATOR + "/examples/commands/start.md", ".opencode/commands/start.md"):
            put(self.source, path, "command\n")
        put(self.source, ".opencode/commands/status.md", "status command\n")
        manifest(self.source)
        self.git("init", "-q")
        self.git("add", "--", *P.PACKAGE)
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.consumer.mkdir()
        for relative in P.PACKAGE:
            destination = self.consumer / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.source / relative, destination)
        for group in P.GROUPS:
            (self.consumer / ".orchestrator" / group).mkdir(parents=True)

    def git(self, *args):
        return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(self.source), *args],
                                       env={"PATH": os.environ["PATH"], "HOME": str(self.root),
                                            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
                                       stderr=subprocess.PIPE, text=True)

    def report(self, expected=None):
        return P.preflight(str(self.source), str(self.consumer), expected or self.sha)

    def assert_status(self, status, expected=None):
        report = self.report(expected)
        self.assertEqual(report["status"], status, report)
        return report

    def write_task(self, raw=None, relative="example/task.json"):
        return put(self.consumer, ".orchestrator/tasks/" + relative, json.dumps(raw or task()))

    def test_aligned_empty_initialized_state_and_cli(self):
        report = self.assert_status("ALIGNED_STATIC")
        self.assertEqual(report["counts"]["tasks"], 0)
        self.assertGreater(report["counts"]["source_files"], 0)
        out = io.StringIO()
        with redirect_stdout(out):
            code = P.main(["--source", str(self.source), "--consumer", str(self.consumer), "--expected-source", self.sha])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()), report)

    def test_empty_and_missing_source(self):
        shutil.rmtree(self.source)
        self.assert_status("UNVERIFIED")
        self.source.mkdir()
        self.assert_status("UNVERIFIED")

    def test_empty_missing_or_corrupt_manifest(self):
        path = self.source / P.MANIFEST
        for content in (b"", b"bad", b"0" * 64 + b"  ./../../outside\n"):
            with self.subTest(content=content):
                path.write_bytes(content)
                self.assert_status("UNVERIFIED")
        path.unlink()
        self.assert_status("UNVERIFIED")

    def test_source_dirty_even_with_regenerated_manifest(self):
        put(self.source, P.ORCHESTRATOR + "/SKILL.md", "edited and rehashed")
        manifest(self.source)
        self.assert_status("UNVERIFIED")

    def test_source_extra_and_missing_inventory(self):
        extra = put(self.source, P.SKILL_ROOT + "cross-repo-epic/extra.md", "untracked")
        self.assert_status("UNVERIFIED")
        extra.unlink()
        (self.source / P.SKILL_ROOT / "cross-repo-epic/run.sh").unlink()
        self.assert_status("UNVERIFIED")

    def test_git_revision_and_failure(self):
        self.assert_status("UNVERIFIED", "0" * 40)
        self.assert_status("UNVERIFIED", "abc")
        with patch.object(P, "git_read", side_effect=P.Unverified("git_query_failed")):
            self.assert_status("UNVERIFIED")

    def test_manifest_omitted_file(self):
        path = self.source / P.MANIFEST
        path.write_text(path.read_text().split("\n", 1)[1])
        self.assert_status("UNVERIFIED")

    def test_source_profile_internal_mismatch(self):
        put(self.source, ".opencode/agents/reviewer.md", "changed source profile")
        self.assert_status("UNVERIFIED")

    def test_repository_canonical_manifest_and_profiles(self):
        # Exercise the real declared package without importing its controllers.
        snapshot = P.package_snapshot(str(SCRIPT.parents[1]))
        P.verify_manifest(snapshot)
        self.assertGreater(sum(item.kind == "file" for item in snapshot.values()), 50)

    def test_changed_missing_and_extra_install(self):
        path = self.consumer / P.ORCHESTRATOR / "SKILL.md"
        path.write_text("changed")
        self.assert_status("ACTION_REQUIRED")
        path.unlink()
        self.assert_status("ACTION_REQUIRED")
        put(self.consumer, P.ORCHESTRATOR + "/unexpected.md", "extra")
        self.assert_status("ACTION_REQUIRED")

    def test_missing_entire_installed_skill(self):
        shutil.rmtree(self.consumer / P.ORCHESTRATOR)
        self.assert_status("ACTION_REQUIRED")

    def test_profiles_and_commands_are_compared(self):
        for relative in (".opencode/agents/reviewer.md", ".opencode/commands/start.md", ".opencode/commands/status.md"):
            with self.subTest(relative=relative):
                path = self.consumer / relative
                original = path.read_bytes()
                path.write_bytes(b"changed install")
                self.assert_status("ACTION_REQUIRED")
                path.unlink()
                self.assert_status("ACTION_REQUIRED")
                path.write_bytes(original)

    def test_modes_compared(self):
        path = self.consumer / P.ORCHESTRATOR / "run.sh"
        path.chmod(0o644)
        self.assert_status("ACTION_REQUIRED")
        (self.source / P.ORCHESTRATOR / "run.sh").chmod(0o644)
        self.assert_status("UNVERIFIED")

    def test_missing_state_is_not_empty(self):
        shutil.rmtree(self.consumer / ".orchestrator")
        self.assert_status("UNVERIFIED")

    def test_missing_state_component(self):
        (self.consumer / ".orchestrator/slots").rmdir()
        self.assert_status("UNVERIFIED")

    def test_supported_shapes_not_compatibility(self):
        for schema in (1, 2):
            with self.subTest(schema=schema):
                self.write_task(task(schema))
                report = self.assert_status("ALIGNED_STATIC")
                self.assertEqual(report["counts"][f"schema_{schema}_observed"], 1)
                self.assertEqual(report["state_schema"], "observed_shape_only")
                self.assertIn("not_runtime_compatibility", report["limitations"])

    def test_recorded_activity_no_process_queries(self):
        worker = {"pid": 999999, "worker_id": "b" * 32, "token": "c" * 32,
                  "task_id": "example", "owner": "private person", "process_start": "private process",
                  "hostname": "private-host.invalid"}
        for field, value in (("state", "Implementing"), ("worker", worker), ("transition_intent", "Done"),
                             ("leases", {"global_slot": 0, "implementation_lane": 0, "scope_token": "a" * 32})):
            with self.subTest(field=field):
                raw = task()
                raw[field] = value
                self.write_task(raw)
                with patch.object(os, "kill", side_effect=AssertionError("process query")), \
                     patch.object(socket, "gethostname", side_effect=AssertionError("host query")), \
                     patch.object(socket, "socket", side_effect=AssertionError("network query")):
                    report = self.assert_status("ACTION_REQUIRED")
                self.assertNotIn("private", json.dumps(report))

    def test_corrupt_missing_fields_and_unknown_schema(self):
        path = self.write_task()
        for data in ("{", "[]", '{"schema_version":2}', '{"schema_version":1,"schema_version":2}',
                     json.dumps(dict(task(), schema_version=3)), json.dumps(dict(task(), schema_version=True)),
                     json.dumps(dict(task(), worker={})), json.dumps(dict(task(), leases={}))):
            with self.subTest(data=data):
                path.write_text(data)
                self.assert_status("UNVERIFIED")

    def test_nested_tasks_and_missing_task_record(self):
        self.write_task(relative="example/nested/task.json")
        self.assert_status("UNVERIFIED")
        shutil.rmtree(self.consumer / ".orchestrator/tasks/example/nested")
        self.assert_status("UNVERIFIED")

    def test_reservation_and_coordinator_contents(self):
        for group in ("locks", "scopes", "slots", "implementation"):
            with self.subTest(group=group):
                lock = f".orchestrator/{group}/coordinator.lock"
                path = put(self.consumer, lock + "/owner.json", json.dumps(reservation(group)))
                self.assert_status("ACTION_REQUIRED")
                path.write_text("{private malformed record")
                self.assert_status("UNVERIFIED")
                path.unlink()
                self.assert_status("UNVERIFIED")
                shutil.rmtree(path.parent)

    def test_nested_corrupt_lock_file_is_not_ignored(self):
        base = ".orchestrator/slots/0.lock/"
        put(self.consumer, base + "owner.json", json.dumps(reservation("slots")))
        put(self.consumer, base + "nested/owner.json", "corrupt")
        self.assert_status("UNVERIFIED")

    def test_sync_markers(self):
        for suffix in ("sync-lock", "sync-in-progress", "previous.12", "sync.abcd"):
            path = self.consumer / P.SKILL_ROOT / (".workspace-orchestrator." + suffix)
            path.mkdir()
            self.assert_status("ACTION_REQUIRED")
            path.rmdir()

    def test_monitor_lock_contents(self):
        path = put(self.consumer, ".orchestrator/monitor/poll.lock/owner.json", "{}")
        self.assert_status("ACTION_REQUIRED")
        path.write_text("corrupt")
        self.assert_status("UNVERIFIED")

    def test_monitor_json_bounded_regular_and_parsed(self):
        for name in sorted(P.MONITOR_JSON):
            with self.subTest(name=name):
                path = put(self.consumer, ".orchestrator/monitor/" + name, '{"note":"PRIVATE-MONITOR"}')
                report = self.assert_status("ALIGNED_STATIC")
                self.assertNotIn("PRIVATE-MONITOR", json.dumps(report))
                for content in ("{", "[]", "x" * (P.MAX_FILE + 1)):
                    path.write_text(content)
                    self.assert_status("UNVERIFIED")
                path.unlink()
                path.symlink_to(self.source / P.ORCHESTRATOR / "SKILL.md")
                self.assert_status("UNVERIFIED")
                path.unlink()

    def test_monitor_same_name_json_change(self):
        for name in sorted(P.MONITOR_JSON):
            with self.subTest(name=name):
                path = put(self.consumer, ".orchestrator/monitor/" + name, '{"revision":1}')
                original = P.state_snapshot
                calls = []

                def changed(root):
                    calls.append(root)
                    if len(calls) == 2:
                        path.write_text('{"revision":2}')
                    return original(root)

                with patch.object(P, "state_snapshot", side_effect=changed):
                    report = self.assert_status("UNVERIFIED")
                self.assertIn("state_changed_between_passes", report["unverified_codes"])
                path.unlink()

    def test_sqlite_is_explicitly_unmeasured_and_never_opened(self):
        for name in sorted(P.MONITOR_SQLITE):
            put(self.consumer, ".orchestrator/monitor/" + name, b"not parsed as a database")
        real_open = os.open

        def guarded(path, *args, **kwargs):
            self.assertNotIn(os.path.basename(path), P.MONITOR_SQLITE)
            return real_open(path, *args, **kwargs)

        with patch.object(os, "open", side_effect=guarded):
            report = self.assert_status("ACTION_REQUIRED")
        self.assertEqual(report["counts"]["monitor_sqlite_unmeasured"], len(P.MONITOR_SQLITE))
        self.assertIn("monitor_sqlite_unmeasured", report["action_codes"])
        path = self.consumer / ".orchestrator/monitor/history.sqlite3"
        path.unlink()
        path.symlink_to(self.source / P.ORCHESTRATOR / "SKILL.md")
        self.assert_status("UNVERIFIED")

    def test_unknown_monitor_entry_rejected(self):
        put(self.consumer, ".orchestrator/monitor/unknown.json", "{}")
        report = self.assert_status("UNVERIFIED")
        self.assertIn("unrecognized_monitor_entry", report["unverified_codes"])

    def test_task_atomic_write_artifacts(self):
        self.write_task()
        for relative in ("example/.new-pending", ".new-pending", "example/evidence/.new-pending"):
            with self.subTest(relative=relative):
                path = put(self.consumer, ".orchestrator/tasks/" + relative, "incomplete private write")
                report = self.assert_status("ACTION_REQUIRED")
                self.assertIn("task_write_artifact_present", report["action_codes"])
                path.unlink()

    def test_disappeared_descendant_not_missing_install(self):
        original = P.Reader.entry

        def disappeared(reader, fd, name):
            if name == "SKILL.md":
                raise FileNotFoundError("simulated descendant disappearance")
            return original(reader, fd, name)

        with patch.object(P.Reader, "entry", new=disappeared):
            with self.assertRaisesRegex(P.Unverified, "tree_descendant_disappeared"):
                P.package_snapshot(str(self.consumer), installed=True)

    def isolated_entry_fixture(self):
        # Copy only the entry points into a hostile import directory in the guest.
        directory = self.root / "entry points"
        directory.mkdir()
        python = directory / SCRIPT.name
        wrapper = directory / "review-workspace-preflight.sh"
        shutil.copyfile(SCRIPT, python)
        shutil.copyfile(SCRIPT.with_suffix(".sh"), wrapper)
        put(directory, "json.py", 'raise RuntimeError("SHADOW_JSON_EXECUTED")\n')
        shadow = self.root / "pythonpath"
        put(shadow, "json.py", 'raise RuntimeError("PYTHONPATH_JSON_EXECUTED")\n')
        env = dict(os.environ, PYTHONPATH=str(shadow))
        args = ["--source", str(self.source), "--consumer", str(self.consumer), "--expected-source", self.sha]
        return directory, python, wrapper, env, args

    def test_wrapper_ignores_shadow_json_and_pythonpath(self):
        directory, _, wrapper, env, args = self.isolated_entry_fixture()
        result = subprocess.run(["sh", str(wrapper), *args], env=env, cwd=directory,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["status"], "ALIGNED_STATIC")
        self.assertEqual(result.stderr, "")
        self.assertFalse(list(directory.rglob("*.pyc")))
        self.assertFalse(list((self.root / "pythonpath").rglob("*.pyc")))

    def test_direct_python_refuses_missing_flags_before_json_import(self):
        directory, python, _, env, args = self.isolated_entry_fixture()
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        for flags in ([], ["-B"], ["-I"]):
            with self.subTest(flags=flags):
                result = subprocess.run([sys.executable, *flags, str(python), *args], env=env,
                                        cwd=directory, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 3, result.stderr + result.stdout)
                self.assertEqual(json.loads(result.stdout)["unverified_codes"], ["isolated_no_bytecode_required"])
                self.assertEqual(result.stderr, "")
        self.assertFalse(list(directory.rglob("*.pyc")))

    def test_two_pass_task_content_change(self):
        self.write_task()
        original = P.state_snapshot
        calls = []

        def changed(root):
            calls.append(root)
            if len(calls) == 2:
                self.write_task(dict(task(), next_action="secret changed text"))
            return original(root)

        with patch.object(P, "state_snapshot", side_effect=changed):
            report = self.assert_status("UNVERIFIED")
        self.assertIn("state_changed_between_passes", report["unverified_codes"])
        self.assertNotIn("secret", json.dumps(report))

    def test_two_pass_inventory_change(self):
        original = P.state_snapshot
        calls = []

        def changed(root):
            calls.append(root)
            if len(calls) == 2:
                (self.consumer / ".orchestrator/locks/coordinator.lock").mkdir()
            return original(root)

        with patch.object(P, "state_snapshot", side_effect=changed):
            report = self.assert_status("UNVERIFIED")
        self.assertIn("state_changed_between_passes", report["unverified_codes"])

    def test_two_pass_reservation_content_change(self):
        path = put(self.consumer, ".orchestrator/slots/0.lock/owner.json", json.dumps(reservation("slots")))
        original = P.state_snapshot
        calls = []

        def changed(root):
            calls.append(root)
            if len(calls) == 2:
                path.write_text(json.dumps(dict(reservation("slots"), token="e" * 32)))
            return original(root)

        with patch.object(P, "state_snapshot", side_effect=changed):
            report = self.assert_status("UNVERIFIED")
        self.assertIn("state_changed_between_passes", report["unverified_codes"])

    def test_symlink_file_and_ancestor(self):
        path = self.consumer / P.ORCHESTRATOR / "SKILL.md"
        path.unlink()
        path.symlink_to(self.source / P.ORCHESTRATOR / "SKILL.md")
        self.assert_status("UNVERIFIED")
        path.unlink()
        path.write_text("fixture skill\n")
        shutil.rmtree(self.consumer / ".orchestrator/tasks")
        (self.consumer / ".orchestrator/tasks").symlink_to(self.source, target_is_directory=True)
        self.assert_status("UNVERIFIED")

    def test_oversize_fifo_and_depth(self):
        path = self.write_task()
        path.write_bytes(b"x" * (P.MAX_FILE + 1))
        self.assert_status("UNVERIFIED")
        path.unlink()
        os.mkfifo(path)
        self.assert_status("UNVERIFIED")
        path.unlink()
        self.write_task()
        (path.parent / ("nested/" * (P.MAX_DEPTH + 1))).mkdir(parents=True)
        self.assert_status("UNVERIFIED")

    def test_entry_limit(self):
        with patch.object(P, "MAX_ENTRIES", 1):
            self.assert_status("UNVERIFIED")

    def test_no_mutations_and_no_external_output(self):
        self.write_task(dict(task(), owner="SECRET-OWNER", next_action="SECRET-TASK"))

        def inventory():
            return {str(p.relative_to(self.root)): (p.lstat().st_mode, p.lstat().st_mtime_ns,
                                                   p.read_bytes() if p.is_file() else None)
                    for p in self.root.rglob("*")}

        before = inventory()
        real_open = os.open

        def readonly(path, flags, *args, **kwargs):
            # Popen uses a read/write /dev/null descriptor for discarded I/O.
            if path != os.devnull:
                self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            return real_open(path, flags, *args, **kwargs)

        with patch.object(os, "open", side_effect=readonly), \
             patch.object(os, "mkdir", side_effect=AssertionError("mutation")), \
             patch.object(os, "unlink", side_effect=AssertionError("mutation")), \
             patch.object(os, "rename", side_effect=AssertionError("mutation")):
            report = self.assert_status("ALIGNED_STATIC")
        self.assertEqual(before, inventory())
        self.assertNotIn("SECRET", json.dumps(report))
        self.assertNotIn(str(self.root), json.dumps(report))

    def test_git_environment_and_read_only_commands(self):
        real_popen = subprocess.Popen
        calls = []

        def capture(command, **kwargs):
            calls.append(command)
            self.assertNotIn("GIT_DIR", kwargs["env"])
            self.assertEqual(kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")
            self.assertEqual(kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")
            return real_popen(command, **kwargs)

        with patch.dict(os.environ, {"GIT_DIR": "/nonexistent", "GIT_CONFIG_COUNT": "1", "GIT_TRACE": "secret"}), \
             patch.object(subprocess, "Popen", side_effect=capture):
            self.assert_status("ALIGNED_STATIC")
        self.assertEqual(len(calls), 4)
        self.assertTrue(all("rev-parse" in cmd or "ls-tree" in cmd for cmd in calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)
