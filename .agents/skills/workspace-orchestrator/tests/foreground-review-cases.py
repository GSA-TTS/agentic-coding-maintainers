"""Fresh-review cases reuse the real owner/application/adoption CLI fixture."""

import contextlib
import copy
import io
import json
import os
import sys
from unittest import mock


def install(base, delivery, c):
    class FreshReviewTests(base):
        def git(self, *args):
            if args[:2] == ("commit", "-qm") and not hasattr(self, "head") and not hasattr(self, "original_base"):
                directory = self.worktree / "base-only"
                directory.mkdir()
                (directory / "context.txt").write_bytes(b"original base context\n")
                super().git("add", "base-only")
                super().git(*args)
                self.original_base = super().git("rev-parse", "HEAD").strip()
                self.head = self.original_base
                (directory / "context.txt").write_bytes(b"implementation context\n")
                (self.worktree / "auth-policy.txt").write_bytes(b"implementation outside repair\n")
                super().git("add", "auth-policy.txt", "base-only/context.txt")
            return super().git(*args)

        def cli(self, *args, **kwargs):
            if args[:2] == ("state", "create"):
                args = list(args)
                args[args.index("--base-sha") + 1] = self.original_base
            return super().cli(*args, **kwargs)

        def domain(self, tool, action, payload, operation, *extra):
            if tool == "review-evidence" and action == "begin" and operation == "begin":
                # Existing fixture packet must bind the original base as well.
                packet = c.decode(self.packet)
                packet["base"] = self.original_base
                self.packet = c.canonical(packet)
                (self.root / "packet.json").write_bytes(self.packet)
                payload = {**payload, "base": self.original_base, "packet": c.digest(self.packet),
                           "obligations": sorted(set(payload["obligations"]) | {"historical-specialist"})}
            return super().domain(tool, action, payload, operation, *extra)

        def prepare_fresh(self):
            self.dispatch(self.prepare_adoption())
            request = self.request("prepare-repaired-review", "fresh")
            request["payload"] = {"adopt_operation_id": "adopt"}
            return request

        def test_fresh_cli_original_base_union_one_revision_and_historical_replay(self):
            request = self.prepare_fresh()
            before = self.record()
            self.assertEqual(self.dispatch()["next_action"], "PREPARE_REPAIRED_REVIEW")
            result = self.dispatch(request)
            after = self.record()
            self.assertEqual(after["revision"], before["revision"] + 1)
            self.assertEqual(result["domain_result"]["status"], "BEGUN")
            for field in ("worker", "leases", "state", "findings", "base_sha", "head_sha", "validation", "reviewers"):
                self.assertEqual(after[field], before[field])
            self.assertEqual(after["review_protocol"]["generations"][:-1], before["review_protocol"]["generations"])
            generation = after["review_protocol"]["generations"][-1]
            self.assertTrue({"trust-boundary", "historical-specialist"} <= set(generation["obligations"]))
            self.assertEqual(generation["base"], self.original_base)
            self.assertEqual(generation["head"], self.adopted_head)
            helper = delivery.dependency("foreground-review")
            packet = helper.read_packet(self.state_root, generation["packet"])
            self.assertEqual({f["path_utf8"] for f in packet["files"]},
                             {"source.py", "second.py", "auth-policy.txt", "base-only/context.txt"})
            self.assertEqual(packet["comparison"], "direct")
            self.assertEqual(generation["assignments"], {})
            self.assertEqual(self.dispatch()["next_action"], "FRESH_EXECUTION_AND_INDEPENDENT_REVIEW_REQUIRED")
            duplicate = {**request, "operation_id": "another", "expected_revision": after["revision"]}
            self.dispatch(duplicate, expected=3)
            self.git("commit", "--allow-empty", "-qm", "test: later operator commit")
            self.cli("state", "update-head", "fixture", self.git("rev-parse", "HEAD").strip())
            self.dispatch(self.request("pause", "later-pause"))
            (self.worktree / "source.py").write_bytes(b"dirty later\n")
            self.git("remote", "set-url", "origin", "https://github.com/other/project")
            retained = self.task_path.read_bytes()
            self.assertEqual(self.dispatch(request), result)
            original_load = helper.load
            capture = original_load("review-packet")
            original_dependency = delivery.dependency
            with mock.patch.object(capture, "capture", side_effect=AssertionError("no recapture")), \
                    mock.patch.object(helper, "load", side_effect=lambda name: capture if name == "review-packet" else original_load(name)), \
                    mock.patch.object(delivery, "dependency", side_effect=lambda name: helper if name == "foreground-review" else original_dependency(name)):
                _, replay, changed = delivery.dispatch(self.record(), request, self.state_root)
                self.assertEqual(replay, result)
                self.assertFalse(changed)
            self.assertEqual(self.task_path.read_bytes(), retained)

        def test_fresh_current_guards_and_new_generation(self):
            request = self.prepare_fresh()
            saved = self.record()
            for damage in ("worker", "owner", "epoch", "cycle", "scope", "head", "base"):
                changed = copy.deepcopy(saved)
                if damage == "worker":
                    changed["worker"]["worker_id"] = "d" * 32
                elif damage == "owner":
                    changed["owner"] = "other"
                elif damage == "epoch":
                    changed["review_protocol"]["material_epoch"] += 1
                elif damage == "cycle":
                    changed["rework_count"] += 1
                elif damage == "scope":
                    changed["owned_paths"] = ["elsewhere"]
                else:
                    changed[damage + "_sha"] = self.head
                self.store_record(changed)
                self.dispatch(request, expected=3)
            self.store_record(saved)
            self.dispatch({**request, "expected_revision": saved["revision"] - 1}, expected=3)
            self.dispatch(self.request("pause", "pause-fresh"))
            request["expected_revision"] = self.record()["revision"]
            self.dispatch(request, expected=3)
            self.dispatch(self.request("resume", "resume-fresh"))
            request["expected_revision"] = self.record()["revision"]
            path = self.worktree / "source.py"
            raw = path.read_bytes()
            path.write_bytes(b"dirty\n")
            self.dispatch(request, expected=3)
            path.write_bytes(raw)
            self.git("remote", "set-url", "origin", "https://github.com/other/project")
            self.dispatch(request, expected=3)
            self.git("remote", "set-url", "origin", "https://github.com/fixture/project")
            self.git("commit", "--allow-empty", "-qm", "test: late head")
            self.dispatch(request, expected=3)
            self.git("reset", "--hard", self.adopted_head)
            self.domain("review-evidence", "begin", {"base": self.original_base, "head": self.adopted_head,
                "packet": "a" * 64, "policy": "b" * 64,
                "obligations": sorted(delivery.dependency("review-evidence").BASELINE)}, "manual-new")
            request["expected_revision"] = self.record()["revision"]
            self.dispatch(request, expected=3)

        def test_fresh_missing_objects_packet_substitution_and_orphans(self):
            request = self.prepare_fresh()
            base_tree = self.git("rev-parse", self.original_base + "^{tree}").strip()
            descendant = self.git("rev-parse", self.original_base + ":base-only").strip()
            for oid in (self.original_base, base_tree, descendant):
                path = self.worktree / ".git/objects" / oid[:2] / oid[2:]
                moved = path.with_suffix(".missing")
                path.rename(moved)
                self.dispatch(request, expected=3)
                moved.rename(path)
            result = self.dispatch(request)
            saved = self.record()
            generation = saved["review_protocol"]["generations"][-1]
            packet_path = self.state_root / "review-packets" / (generation["packet"] + ".json")
            moved = packet_path.with_suffix(".missing")
            packet_path.rename(moved)
            self.dispatch(request, expected=3)
            moved.rename(packet_path)
            raw = packet_path.read_bytes()
            packet_path.chmod(0o600)
            packet_path.write_bytes(raw.replace(b"implementation outside repair", b"substituted outside repair"))
            packet_path.chmod(0o400)
            self.dispatch(request, expected=3)
            packet_path.chmod(0o600)
            packet_path.write_bytes(raw)
            packet_path.chmod(0o400)
            key = saved["foreground_control"]["receipts"]["fresh"]["reference"]["key"]
            for damage in ("foreground", "domain", "marker", "reference"):
                changed = copy.deepcopy(saved)
                if damage == "foreground":
                    del changed["foreground_control"]["receipts"]["fresh"]
                    with self.assertRaises(Exception):
                        delivery.dependency("review-evidence").validate_protocol(changed)
                elif damage == "domain":
                    del changed["review_protocol"]["operations"][key]
                elif damage == "marker":
                    del changed["foreground_initialized"]
                else:
                    changed["foreground_control"]["receipts"]["fresh"]["reference"]["packet"] = "a" * 64
                self.store_record(changed)
                self.dispatch(request, expected=3)
            self.store_record(saved)
            for oid in (self.original_base, base_tree, descendant):
                path = self.worktree / ".git/objects" / oid[:2] / oid[2:]
                moved = path.with_suffix(".missing")
                path.rename(moved)
                self.dispatch(request, expected=3)
                moved.rename(path)
            self.assertEqual(self.dispatch(request), result)

        def test_fresh_raw_hash_and_capture_substitution_guards(self):
            request = self.prepare_fresh()
            helper = delivery.dependency("foreground-review")
            adopt = helper.load("foreground-adopt")
            git = adopt.Git(self.worktree)
            packet = helper.load("review-packet").capture(self.worktree, "fixture/project", self.original_base, self.adopted_head, "direct")
            for field in ("path_utf8", "status", "content", "mode", "oid", "bytes"):
                changed = copy.deepcopy(packet)
                if field in {"path_utf8", "status"}:
                    changed["files"][0][field] = "substitution"
                else:
                    changed["files"][0]["after"][field] = 1 if field == "bytes" else "substitution"
                with self.assertRaisesRegex(ValueError, "authenticated raw"):
                    helper.verify_packet(changed, git, "fixture/project", self.original_base, self.adopted_head)
            for ref in (self.original_base, self.original_base + "^{tree}", self.original_base + ":base-only"):
                oid = self.git("rev-parse", ref).strip()
                kind = "commit" if ref == self.original_base else "tree"
                raw = git.obj(oid, kind)
                changed = raw.replace(b"context.txt", b"dontext.txt") if ref.endswith(":base-only") else raw.replace(b"base-only", b"case-only") if kind == "tree" else raw + b"substitution"
                fresh = adopt.Git(self.worktree)
                read = fresh.reader.git_bytes
                def readable(repo, *args, **kwargs):
                    return changed if args == ("cat-file", kind, oid) else read(repo, *args, **kwargs)
                with mock.patch.object(fresh.reader, "git_bytes", side_effect=readable):
                    with self.assertRaisesRegex(ValueError, "raw object hash mismatch"):
                        helper.verify_packet(packet, fresh, "fixture/project", self.original_base, self.adopted_head)
            self.dispatch(request)

        def test_fresh_persistence_failure_existing_packet_fsync_and_retry(self):
            request = self.prepare_fresh()
            saved = self.record()
            coordinator = delivery.dependency("orchestrator-state")
            dependency = delivery.dependency
            path = self.root / "fresh-request.json"
            path.write_bytes(c.canonical(request))
            with mock.patch.dict(os.environ, self.env, clear=True), \
                    mock.patch.object(sys, "argv", ["foreground-delivery", "fixture", "--request", str(path)]), \
                    mock.patch.object(delivery, "dependency", side_effect=lambda name: coordinator if name == "orchestrator-state" else dependency(name)), \
                    contextlib.redirect_stdout(io.StringIO()):
                # Lock metadata must still persist; fail only the task write.
                with mock.patch.object(coordinator, "write_task", side_effect=OSError("task write failure")) as writes:
                    self.assertEqual(delivery.main(), 3)
                    self.assertEqual(writes.call_count, 1)
                self.assertEqual(self.record(), saved)
                packets = list((self.state_root / "review-packets").glob("*.json"))
                self.assertEqual(len(packets), 1)
                helper = dependency("foreground-review")
                packet = c.decode(packets[0].read_bytes())
                fsync = os.fsync
                with mock.patch.object(helper.os, "fsync", side_effect=OSError("durability unavailable")):
                    with self.assertRaises(OSError):
                        helper.retain(self.state_root, packet)
                with mock.patch.object(helper.os, "fsync", wraps=fsync) as syncs:
                    self.assertEqual(helper.retain(self.state_root, packet), packets[0].stem)
                    self.assertEqual(syncs.call_count, 3)
                with mock.patch.object(coordinator, "write_task", wraps=coordinator.write_task) as writes:
                    self.assertEqual(delivery.main(), 0)
                    self.assertEqual(writes.call_count, 1)
            self.assertEqual(self.record()["revision"], saved["revision"] + 1)

        def test_fresh_bounds_prefix_and_all_prior_obligations(self):
            request = self.prepare_fresh()
            saved = self.record()
            helper = delivery.dependency("foreground-review")
            adopt = helper.load("foreground-adopt")
            original_load = helper.load
            with mock.patch.object(helper, "load", side_effect=lambda name: adopt if name == "foreground-adopt" else original_load(name)):
                for name in ("MAX_BYTES", "MAX_CALLS", "MAX_FILES", "MAX_SECONDS"):
                    with mock.patch.object(adopt, name, 0):
                        with self.assertRaisesRegex(Exception, "bound|budget"):
                            helper.prepare(copy.deepcopy(saved), request, self.state_root)
            packet = {"obligations": [{"id": "new-specialist"}]}
            history = {"review_protocol": {"generations": [
                {"obligations": ["earliest-only"]}, {"obligations": ["latest-only"]}]}}
            self.assertTrue({"earliest-only", "latest-only", "new-specialist"} <= set(helper.obligation_union(history, packet, 2)))
            history["review_protocol"]["generations"][0]["obligations"] = ["obligation-" + str(i) for i in range(32)]
            with self.assertRaisesRegex(ValueError, "no waiver"):
                helper.obligation_union(history, packet, 2)
            self.dispatch({**request, "operation_id": "fgreview.reserved"}, expected=3)
            malformed = {**request, "payload": {**request["payload"], "extra": True}}
            self.dispatch(malformed, expected=3)
            for pretty in (False, True):
                record = copy.deepcopy(saved)
                record["budget_metadata"] = {str(i): ["x"] * 20 for i in range(1000)} if pretty else {}
                measure = lambda value: len((json.dumps(value, sort_keys=True, indent=2) + "\n").encode()) if pretty else len(c.canonical(value))
                record["budget_metadata"]["padding"] = "x" * ((999_000 if pretty else 899_000) - measure(record) - 20)
                self.store_record(record)
                self.dispatch(request, expected=3)
            self.store_record(saved)
            self.dispatch(request)

        def test_fresh_inherited_findings_wait_for_current_report(self):
            request = self.prepare_fresh()
            self.dispatch(request)
            e = delivery.dependency("review-evidence")
            generation = self.record()["review_protocol"]["generations"][-1]
            def report(run, dispositions, findings):
                self.domain("review-evidence", "assign", {"generation": 2, "run_id": run, "reviewer": "new-reviewer",
                    "profile": "e" * 64, "obligations": generation["obligations"], "adapter": "native-session",
                    "session": "ses_" + run}, "assign-" + run)
                self.domain("review-evidence", "accept", {"generation": 2, "run_id": run,
                    "packet": generation["packet"], "policy": generation["policy"], "profile": "e" * 64,
                    "session": "ses_" + run, "coverage": dict.fromkeys(generation["obligations"], "reviewed"),
                    "findings": findings, "dispositions": dispositions, "limitations": []}, "accept-" + run)
            report("coverage", [], [])
            self.assertTrue(e.assess(self.record())["unresolved_findings"])
            self.assertEqual(self.dispatch()["next_action"], "FRESH_EXECUTION_AND_INDEPENDENT_REVIEW_REQUIRED")
            finding = e.assess(self.record())["unresolved_findings"][0]
            report("persists", [{"finding_id": finding, "resolution": "persists", "counterevidence": "current inspection"}], [])
            self.assertEqual(self.dispatch()["next_action"], "OWNER_REWORK_ADMISSION_REQUIRED")

    return FreshReviewTests
