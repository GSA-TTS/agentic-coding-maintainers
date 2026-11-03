"""Additional cases installed into the existing foreground public-CLI suite."""

import copy
import contextlib
import io
import json
import os
import sys
from unittest import mock


def install(base, delivery, c):
    class AdoptionTests(base):
        # Inherit fixture methods, but the loader below selects only adoption cases.
        def prepare_adoption(self):
            self.repair_cli(self.collected_two_file_proposal())
            self.git("add", "source.py", "second.py")
            self.git("commit", "-qm", "test: operator-created repair")
            self.adopted_head = self.git("rev-parse", "HEAD").strip()
            (self.worktree / ".git/info").mkdir(exist_ok=True)
            return self.adopt_request()

        def adopt_request(self, operation="adopt"):
            request = self.request("adopt-owner-repair-head", operation)
            request["payload"] = {"apply_operation_id": "apply-owner-proposal", "head": self.adopted_head}
            return request

        def test_adopt_public_cli_atomic_history_pause_and_later_head(self):
            request = self.prepare_adoption()
            self.dispatch(self.request("pause", "pause-adopt"))
            self.dispatch(self.adopt_request(), expected=3)
            self.dispatch(self.request("resume", "resume-adopt"))
            before = self.record()
            before["legacy_finding_dispositions"] = {"epoch": 0, "history": []}
            before["reviewers"], before["reviewed_sha"], before["validation"] = ["old"], self.head, ["old"]
            self.store_record(before)
            request = self.adopt_request()
            result = self.dispatch(request)
            after = self.record()
            self.assertEqual(result["status"], "REPAIR_HEAD_ADOPTED_UNREVIEWED")
            self.assertEqual(after["revision"], before["revision"] + 1)
            self.assertEqual(after["head_sha"], self.adopted_head)
            self.assertEqual(after["review_protocol"]["material_epoch"], before["review_protocol"]["material_epoch"] + 1)
            self.assertEqual(after["legacy_finding_dispositions"]["epoch"], 1)
            for field, expected in (("reviewers", []), ("reviewed_sha", ""), ("validation", [])):
                self.assertEqual(after[field], expected)
            for field in ("worker", "leases", "state", "base_sha"):
                self.assertEqual(after[field], before[field])
            self.assertEqual(self.dispatch()["next_action"], "ADOPTED_REPAIR_REQUIRES_FRESH_EXECUTION_AND_REVIEW")
            self.dispatch(self.adopt_request("adopt-again"), expected=3)
            reference = after["foreground_control"]["receipts"]["adopt"]["reference"]
            self.assertEqual(len(reference["comparison"]["files"]), 2)
            self.assertEqual(reference["comparison"]["parent"], self.head)
            self.git("commit", "--allow-empty", "-qm", "test: later operator head")
            newer = self.git("rev-parse", "HEAD").strip()
            self.cli("state", "update-head", "fixture", newer)
            (self.worktree / "source.py").write_bytes(b"later dirty bytes\n")
            self.dispatch(self.request("pause", "pause-after-adopt"))
            saved = self.task_path.read_bytes()
            self.assertEqual(self.dispatch(request), result)
            self.assertEqual(self.task_path.read_bytes(), saved)
            self.assertEqual(self.record()["head_sha"], newer)

        def test_adopt_rejects_dirty_index_ignored_modes_and_branch(self):
            request = self.prepare_adoption()
            for name in ("source.py", "second.py"):
                path = self.worktree / name
                raw = path.read_bytes()
                path.write_bytes(b"different\n")
                self.dispatch(request, expected=3)
                self.git("update-index", "--assume-unchanged", name)
                self.dispatch(request, expected=3)
                self.git("update-index", "--no-assume-unchanged", name)
                self.git("update-index", "--skip-worktree", name)
                self.dispatch(request, expected=3)
                self.git("update-index", "--no-skip-worktree", name)
                path.write_bytes(raw)
                path.chmod(0o600)
                self.dispatch(request, expected=3)  # retained mode was 0644
                path.chmod(0o644)
            self.git("update-index", "--cacheinfo", "100644," + self.git("rev-parse", self.head + ":source.py").strip() + ",source.py")
            self.dispatch(request, expected=3)
            self.git("reset", "-q", "HEAD", "--", "source.py")
            (self.worktree / ".git/info/exclude").write_text("ignored\n")
            ignored = self.worktree / "ignored"
            ignored.write_text("not clean")
            self.dispatch(request, expected=3)
            ignored.rename(self.root / "ignored.saved")
            self.git("checkout", "-qb", "wrong")
            self.dispatch(request, expected=3)
            self.git("checkout", "-q", "fixture")
            self.dispatch(request)

        def test_adopt_rejects_extra_removed_renamed_mode_merge_and_tag(self):
            request = self.prepare_adoption()
            good = self.adopted_head
            for damage in ("extra", "removed", "renamed", "mode", "wrongparent", "merge", "tag"):
                with self.subTest(damage=damage):
                    self.git("reset", "--hard", good)
                    if damage == "tag":
                        self.git("tag", "-a", "repair-tag", "-m", "tag", good)
                        head = self.git("rev-parse", "repair-tag").strip()
                    elif damage == "merge":
                        tree = self.git("rev-parse", good + "^{tree}").strip()
                        head = self.git("commit-tree", tree, "-p", self.head, "-p", good, "-m", "merge").strip()
                        self.git("reset", "--hard", head)
                    else:
                        if damage == "extra":
                            (self.worktree / "extra.py").write_text("extra")
                        elif damage == "removed":
                            self.git("rm", "source.py")
                        elif damage == "renamed":
                            self.git("mv", "source.py", "renamed.py")
                        elif damage == "mode":
                            (self.worktree / "source.py").chmod(0o755)
                        self.git("add", "-A")
                        if damage == "wrongparent":
                            self.git("commit", "--allow-empty", "-qm", "wrong parent")
                        else:
                            self.git("commit", "--amend", "-qm", "wrong repair")
                        head = self.git("rev-parse", "HEAD").strip()
                    changed = copy.deepcopy(request)
                    changed["payload"]["head"] = head
                    self.dispatch(changed, expected=3)
            self.git("reset", "--hard", good)
            self.dispatch(request)

        def test_adopt_retained_objects_and_witness_required_not_checkout(self):
            request = self.prepare_adoption()
            result = self.dispatch(request)
            saved = self.record()
            witness = saved["foreground_control"]["receipts"]["adopt"]["reference"]["comparison"]
            for oid in (self.head, self.adopted_head, witness["files"][0]["before_oid"], witness["files"][0]["after_oid"]):
                path = self.worktree / ".git/objects" / oid[:2] / oid[2:]
                moved = path.with_suffix(".missing")
                path.rename(moved)
                self.dispatch(expected=3)
                self.dispatch(request, expected=3)
                moved.rename(path)
            broken = copy.deepcopy(saved)
            broken["foreground_control"]["receipts"]["adopt"]["reference"]["comparison"]["files"][0]["after_oid"] = "0" * 40
            self.store_record(broken)
            self.dispatch(request, expected=3)
            self.store_record(saved)
            self.assertEqual(self.dispatch(request), result)

        def test_adopt_raw_filters_replacements_and_git_environment_canaries(self):
            request = self.prepare_adoption()
            canary = self.root / "filter-ran"
            script = self.root / "canary.sh"
            script.write_text("#!/bin/sh\ntouch " + str(canary) + "\nexit 1\n")
            script.chmod(0o700)
            (self.worktree / ".git/info/attributes").write_text("* filter=canary diff=canary\n")
            for key in ("filter.canary.clean", "filter.canary.smudge", "filter.canary.process", "diff.canary.command", "diff.canary.textconv", "core.fsmonitor"):
                self.git("config", key, str(script))
            self.env.update(GIT_EXTERNAL_DIFF=str(script), GIT_INDEX_FILE="/absent/index", GIT_WORK_TREE="/absent/tree",
                            GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.fsmonitor", GIT_CONFIG_VALUE_0=str(script))
            (self.worktree / "source.py").write_bytes(b"dirty despite filter\n")
            self.dispatch(request, expected=3)
            self.assertFalse(canary.exists())
            (self.worktree / "source.py").write_bytes(b"result = 2\n")
            self.dispatch(request)
            self.assertFalse(canary.exists())
            # Retention is also filter-free after adoption.
            self.dispatch(request)
            self.assertFalse(canary.exists())

        def test_adopt_single_file_private_mode_and_reconciled_application(self):
            (self.worktree / "source.py").chmod(0o600)
            self.prepare_owner()
            self.admit_owner()
            self.dispatch(self.request("collect-owner-proposal"), bundle=True)
            self.injected_apply(self.request("apply-owner-proposal"), "after-writes")
            self.repair_cli(self.request("reconcile-owner-proposal"))
            self.git("add", "source.py")
            self.git("commit", "-qm", "test: operator one-file repair")
            self.adopted_head = self.git("rev-parse", "HEAD").strip()
            request = self.adopt_request()
            head = self.worktree / ".git/objects" / self.adopted_head[:2] / self.adopted_head[2:]
            head.rename(head.with_suffix(".missing"))
            self.dispatch(request, expected=3)
            head.with_suffix(".missing").rename(head)
            self.dispatch(request)
            files = self.record()["foreground_control"]["receipts"]["adopt"]["reference"]["comparison"]["files"]
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]["filesystem_mode"], 0o600)

        def test_adopt_raw_parent_ignores_replace_and_rejects_wrong_blob_bytes(self):
            request = self.prepare_adoption()
            good = self.adopted_head
            self.git("commit", "--allow-empty", "-qm", "test: wrong parent")
            wrong = self.git("rev-parse", "HEAD").strip()
            self.git("replace", wrong, good)
            request["payload"]["head"] = wrong
            self.dispatch(request, expected=3)
            self.git("replace", "-d", wrong)
            self.git("reset", "--hard", good)
            (self.worktree / "source.py").write_bytes(b"result = 3\n")
            self.git("add", "source.py")
            self.git("commit", "--amend", "-qm", "test: wrong replacement")
            request["payload"]["head"] = self.git("rev-parse", "HEAD").strip()
            self.dispatch(request, expected=3)

        def test_adopt_context_missing_objects_and_public_cli_budgets(self):
            request = self.prepare_adoption()
            saved = self.record()
            for damage in ("epoch", "cycle", "scope", "worker", "owner", "phase"):
                record = copy.deepcopy(saved)
                if damage == "epoch":
                    record["review_protocol"]["material_epoch"] += 1
                elif damage == "cycle":
                    record["rework_count"] += 1
                elif damage == "scope":
                    record["owned_paths"] = ["other"]
                elif damage == "worker":
                    record["worker"]["worker_id"] = "different"
                elif damage == "owner":
                    record["owner"] = "different"
                else:
                    op = record["foreground_repairs"]["applications"]["apply-owner-proposal"]["repair_operation_id"]
                    record["repair_protocol"]["operations"][op]["phase"] = "NOT_APPLIED_OBSERVED"
                self.store_record(record)
                self.dispatch(request, expected=3)
            self.store_record(saved)
            missing = copy.deepcopy(request)
            missing["payload"]["head"] = "0" * 40
            self.dispatch(missing, expected=3)
            for pretty in (False, True):
                record = copy.deepcopy(saved)
                record["budget_metadata"] = {str(i): ["x"] * 20 for i in range(1000)} if pretty else {}
                def measure(value):
                    return len((json.dumps(value, sort_keys=True, indent=2) + "\n").encode()) if pretty else len(c.canonical(value))
                record["budget_metadata"]["padding"] = "x" * ((999_500 if pretty else 899_500) - measure(record) - 20)
                coordinator = delivery.dependency("orchestrator-state")
                coordinator.validate_record(record, "fixture")
                coordinator.serialized_json(record)
                delivery.validate_retained(record, self.state_root, c, delivery.dependency("review-evidence"))
                self.store_record(record)
                self.dispatch(request, expected=3)
            self.store_record(saved)
            record = saved
            bridge = delivery.dependency("foreground-repair")
            while len(record["foreground_control"]["receipts"]) + bridge.count(record) < delivery.MAX_RECEIPTS:
                req = self.request("resume", "budget-" + str(record["revision"]))
                req["expected_revision"] = record["revision"]
                record, _, _ = delivery.dispatch(record, req, self.state_root)
                record["revision"] += 1
            self.store_record(record)
            self.dispatch(self.adopt_request(), expected=3)

        def test_adopt_one_write_failure_and_comparison_limits(self):
            request = self.prepare_adoption()
            saved = self.record()
            helper = delivery.dependency("foreground-adopt")
            for name in ("MAX_BYTES", "MAX_CALLS", "MAX_FILES", "MAX_SECONDS"):
                with mock.patch.object(helper, name, 0):
                    with self.assertRaisesRegex(Exception, "bound|budget"):
                        helper.adopt(copy.deepcopy(saved), request, self.state_root)
                self.assertEqual(self.record(), saved)
            coordinator = delivery.dependency("orchestrator-state")
            original_dependency = delivery.dependency
            path = self.root / "atomic-adopt.json"
            path.write_bytes(c.canonical(request))
            with mock.patch.dict(os.environ, self.env, clear=True), \
                    mock.patch.object(sys, "argv", ["foreground-delivery", "fixture", "--request", str(path)]), \
                    mock.patch.object(delivery, "dependency", side_effect=lambda name: coordinator if name == "orchestrator-state" else original_dependency(name)), \
                    contextlib.redirect_stdout(io.StringIO()):
                atomic = coordinator.atomic_json
                def fail_task(path, data):
                    if path == self.task_path:
                        raise OSError("injected write failure")
                    return atomic(path, data)
                with mock.patch.object(coordinator, "atomic_json", side_effect=fail_task), \
                        mock.patch.object(coordinator, "write_task", wraps=coordinator.write_task) as writes:
                    self.assertEqual(delivery.main(), 3)
                    self.assertEqual(writes.call_count, 1)
                self.assertEqual(self.record(), saved)
                with mock.patch.object(coordinator, "write_task", wraps=coordinator.write_task) as writes:
                    self.assertEqual(delivery.main(), 0)
                    self.assertEqual(writes.call_count, 1)
            self.assertEqual(self.record()["revision"], saved["revision"] + 1)

    return AdoptionTests
