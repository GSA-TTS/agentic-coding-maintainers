"""Offline inert-contract fixtures. Execute only in a workspace sandbox."""

import ast
import builtins
import copy
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

if not sys.flags.isolated or not sys.dont_write_bytecode:
    raise SystemExit("Run this sandbox test with python3 -I -B")

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/portable-work-contract.py"
FIXTURES = ROOT / "tests/fixtures/portable-work"
SPEC = importlib.util.spec_from_file_location("portable_work_contract", SOURCE)
assert SPEC is not None and SPEC.loader is not None
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


def fixture(name="staged-documents-v1.json"):
    return json.loads((FIXTURES / name).read_bytes())


def revision(value):
    return {"kind": "exact", "value": value}


class PortableWorkTests(unittest.TestCase):
    def reject(self, value, code=None):
        with self.assertRaises(CONTRACT.ContractError) as error:
            CONTRACT.validate_bundle(value)
        if code is not None:
            self.assertEqual(str(error.exception), code)
        self.assertRegex(str(error.exception), r"^[A-Z_]+$")

    def test_examples_and_unchanged_input(self):
        for path in sorted(FIXTURES.glob("*.json")):
            with self.subTest(path=path.name):
                value = CONTRACT.decode_bundle(path.read_bytes())
                before = copy.deepcopy(value)
                self.assertIsNone(CONTRACT.validate_bundle(value))
                self.assertEqual(before, value)
        value = fixture()
        self.assertNotIn("coordinator", value["runs"][0])
        self.assertEqual(value["work"]["profile"], {"kind": "documents"})

    def test_decode_refusals(self):
        samples = [b"", b"\xff", b"\xef\xbb\xbf{}", b"{} trailing", b"[]",
                   b'{"version":1,"version":1}', b'{"x":{"a":1,"a":2}}',
                   b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1.0}', b'{"x":1e0}',
                   b'{"x":-0}', b'{"x":9007199254740992}', b'{"x":true}',
                   b'{"x":null}', b'{"x":"\\ud800"}',
                   b"[" * 1000 + b"]" * 1000,
                   b" " * (CONTRACT.MAX_BYTES + 1)]
        for sample in samples:
            with self.subTest(sample=sample[:60]):
                with self.assertRaises(CONTRACT.ContractError):
                    CONTRACT.decode_bundle(sample)
        for sample in ("{}", bytearray(b"{}"), None):
            with self.assertRaisesRegex(CONTRACT.ContractError, "TYPE"):
                CONTRACT.decode_bundle(sample)
        with self.assertRaisesRegex(CONTRACT.ContractError, "DUPLICATE_KEY"):
            CONTRACT.decode_bundle(b'{"x":1,"\\u0078":2}')

    def test_exact_types_and_limits(self):
        for version in (True, False, 1.0, "1", 2, 4, 5):
            value = fixture()
            value["version"] = version
            self.reject(value)
        for quantity in (-1, True, 1.0, "1", 9007199254740992):
            value = fixture()
            value["runs"][0]["budget"]["model_calls"] = quantity
            self.reject(value)
        value = fixture()
        value["work"]["constraints"] = ["a"] * 129
        self.reject(value, "LIMIT")
        value = fixture()
        value["work"]["outcome"] = "a" * 4097
        self.reject(value, "LIMIT")
        value["work"]["outcome"] = "a"
        value["work"]["constraints"] = ["a" * 4096] * 128
        self.reject(value, "LIMIT")
        cycle = []
        cycle.append(cycle)
        self.reject(cycle, "LIMIT")
        class Hostile(dict):
            def items(self):
                raise AssertionError("subclass hook called")
        self.reject(Hostile(), "TYPE")
        value = fixture()
        nested = "x"
        for _ in range(17):
            nested = [nested]
        value["work"]["constraints"] = nested
        self.reject(value, "LIMIT")
        value = fixture()
        value["work"]["constraints"] = [["x"] * 128] * 128
        self.reject(value, "LIMIT")

    def test_closed_fields_every_object(self):
        original = fixture("coding-link-v1.json")
        paths = []
        def walk(item, path):
            if isinstance(item, dict):
                paths.append(path)
                for key, child in item.items():
                    walk(child, path + [key])
            elif isinstance(item, list):
                for index, child in enumerate(item):
                    walk(child, path + [index])
        walk(original, [])
        for path in paths:
            with self.subTest(path=path):
                value = copy.deepcopy(original)
                target = value
                for key in path:
                    target = target[key]
                target["unauthorized_field"] = "inert"
                self.reject(value)

    def test_identity_and_reference_refusals(self):
        for identity in ("Mutable title", "", "a\n", "a" * 257, "é", {"id": "a"}):
            value = fixture()
            value["work"]["id"] = identity
            self.reject(value, "IDENTITY")
        mutations = [
            lambda b: b["attempts"][0].update(run_id="run:missing"),
            lambda b: b["attempts"][0].update(step_id="step:missing"),
            lambda b: b["artifacts"][0].update(producer_attempt_id="attempt:missing"),
            lambda b: b["evidence"][0].update(producer_attempt_id="attempt:missing"),
            lambda b: b["evidence"][0].update(acceptance_id="accept:missing"),
            lambda b: b["evidence"][0]["artifact"].update(id="artifact:missing"),
            lambda b: b["evidence"][0]["subject"].update(revision=revision("brief:wrong")),
            lambda b: b["target"].update(support=["evidence:missing"]),
            lambda b: b["runs"][0].update(work_id="work:missing"),
            lambda b: b["artifacts"][0]["provenance"][0].update(revision=revision("wrong:1")),
            lambda b: b["work"]["acceptance"].clear(),
            lambda b: b["evidence"][0].pop("acceptance_id"),
            lambda b: b["evidence"][0].pop("producer_attempt_id"),
            lambda b: b["work"].update(revision={"kind": "branch", "value": "main"}),
        ]
        for mutation in mutations:
            value = fixture()
            mutation(value)
            self.reject(value)
        for collection in ("runs", "attempts", "artifacts", "evidence"):
            value = fixture()
            value[collection].append(copy.deepcopy(value[collection][0]))
            self.reject(value, "DUPLICATE_ID")

    def test_malformed_field_types_have_fixed_diagnostics(self):
        original = fixture("coding-link-v1.json")
        paths = []
        def walk(item, path):
            if isinstance(item, dict):
                for key, child in item.items():
                    paths.append(path + [key])
                    walk(child, path + [key])
            elif isinstance(item, list):
                for index, child in enumerate(item):
                    paths.append(path + [index])
                    walk(child, path + [index])
        walk(original, [])
        for path in paths:
            for replacement in ([], {}, 7):
                value = copy.deepcopy(original)
                target = value
                for key in path[:-1]:
                    target = target[key]
                old = target[path[-1]]
                if type(old) is type(replacement):
                    continue
                with self.subTest(path=path, replacement=replacement):
                    target[path[-1]] = replacement
                    self.reject(value)

    def test_declared_dependency_change_refuses_support_not_history(self):
        for dependency in ("input", "configuration", "workflow", "subject"):
            with self.subTest(dependency=dependency):
                value = fixture()
                history = copy.deepcopy(value["evidence"])
                if dependency == "input":
                    value["work"]["inputs"][0]["revision"] = revision("document:2")
                    value["target"]["inputs"][0]["revision"] = revision("document:2")
                elif dependency == "configuration":
                    value["target"]["configurations"][0]["revision"] = revision("config:2")
                elif dependency == "workflow":
                    value["workflow"]["revision"] = revision("workflow:2")
                    value["target"]["workflow_revision"] = revision("workflow:2")
                else:
                    artifact = copy.deepcopy(value["artifacts"][0])
                    artifact.update(id="artifact:brief-2", revision=revision("brief:2"))
                    value["artifacts"].append(artifact)
                    value["target"]["subject"] = {"id": artifact["id"], "revision": artifact["revision"]}
                self.reject(value, "APPLICABILITY")
                self.assertEqual(value["evidence"], history)
                value["target"]["support"] = []
                self.assertIsNone(CONTRACT.validate_bundle(value))
                self.assertEqual(value["evidence"], history)

    def test_selective_support_and_declared_provenance(self):
        value = fixture()
        value["work"]["inputs"][1]["revision"] = revision("background:99")
        value["target"]["inputs"][1]["revision"] = revision("background:99")
        value["target"]["configurations"].append({"id": "config:unrelated", "revision": revision("other:2")})
        self.assertIsNone(CONTRACT.validate_bundle(value))
        # Cannot omit a dependency that the subject's own provenance declares.
        value["artifacts"][0]["provenance"].append(copy.deepcopy(value["runs"][0]["inputs"][1]))
        self.reject(value, "DEPENDENCY")
        # Target input declarations must agree with the work, not hide drift.
        value = fixture()
        value["work"]["inputs"][0]["revision"] = revision("document:2")
        self.reject(value, "DEPENDENCY")

    def test_removed_input_remains_history(self):
        value = fixture()
        value["work"]["inputs"].pop(0)
        value["target"]["inputs"].pop(0)
        self.reject(value, "APPLICABILITY")
        value["target"]["support"] = []
        self.assertIsNone(CONTRACT.validate_bundle(value))

    def test_cross_run_evidence_refuses(self):
        value = fixture()
        other = copy.deepcopy(value["runs"][0])
        other["id"] = "run:other"
        value["runs"].append(other)
        value["attempts"][1]["run_id"] = other["id"]
        self.reject(value, "CROSS_RUN")

    def test_operation_identity_survives_run_and_attempt_labels(self):
        value = fixture()
        run = copy.deepcopy(value["runs"][0])
        run["id"] = "run:retry"
        attempt = copy.deepcopy(value["attempts"][0])
        attempt.update(id="attempt:retry", run_id=run["id"], parent_attempt_id=value["attempts"][0]["id"])
        value["runs"].append(run)
        value["attempts"].append(attempt)
        self.assertIsNone(CONTRACT.validate_bundle(value))
        run["inputs"].reverse()
        self.assertIsNone(CONTRACT.validate_bundle(value))
        run["budget"]["model_calls"] += 1
        self.reject(value, "OPERATION_CONFLICT")
        run["budget"]["model_calls"] -= 1
        run["inputs"][0]["revision"] = revision("changed:1")
        self.reject(value, "OPERATION_CONFLICT")

    def test_parent_cycles_and_conflicting_operations(self):
        value = fixture()
        value["attempts"][0]["parent_attempt_id"] = value["attempts"][0]["id"]
        self.reject(value, "REFERENCE")
        value = fixture()
        value["attempts"][0]["parent_attempt_id"] = value["attempts"][1]["id"]
        self.reject(value, "REFERENCE")
        value = fixture()
        value["attempts"][1]["operation_id"] = value["attempts"][0]["operation_id"]
        self.reject(value, "OPERATION_CONFLICT")

    def test_binding_exactness_and_unsupported_native(self):
        value = fixture("coding-link-v1.json")
        ordinary = copy.deepcopy(value["runs"][0]["coordinator"])
        cooperative = dict(ordinary, schema=3, session_id="session:synthetic", generation=1)
        value["runs"][0]["coordinator"] = copy.deepcopy(cooperative)
        for attempt in value["attempts"]:
            attempt["coordinator"] = copy.deepcopy(cooperative)
        self.assertIsNone(CONTRACT.validate_bundle(value))
        for field, replacement in (("generation", 2), ("session_id", "session:other"),
                                   ("task_digest", "digest:other"),
                                   ("task_revision", revision("task:2"))):
            changed = copy.deepcopy(value)
            changed["attempts"][0]["coordinator"][field] = replacement
            self.reject(changed, "BINDING")
        for schema in (4, 5, True):
            changed = copy.deepcopy(value)
            changed["runs"][0]["coordinator"]["schema"] = schema
            self.reject(changed)
        changed = copy.deepcopy(value)
        del changed["attempts"][0]["coordinator"]
        self.reject(changed, "BINDING")
        changed = fixture("coding-link-v1.json")
        changed["runs"][0]["coordinator"]["generation"] = 1
        self.reject(changed, "SHAPE")
        changed = copy.deepcopy(value)
        del changed["runs"][0]["coordinator"]["session_id"]
        self.reject(changed, "SHAPE")

    def test_request_only_capacity(self):
        for field in ("entitlement", "admitted", "release", "effective_limit"):
            value = fixture("coding-link-v1.json")
            value["attempts"][0]["capacity"][field] = 1
            self.reject(value, "SHAPE")
        for quantity in (-1, True, 0.5, "1", 9007199254740992):
            value = fixture("coding-link-v1.json")
            value["attempts"][0]["capacity"]["resources"]["workers"]["quantity"] = quantity
            self.reject(value)
        value = fixture("coding-link-v1.json")
        value["attempts"][0]["capacity"]["resources"]["workers"]["unit"] = "bytes"
        self.reject(value, "UNIT")
        for field in ("work_id", "run_id", "attempt_id", "operation_id"):
            value = fixture("coding-link-v1.json")
            value["attempts"][0]["capacity"][field] = "wrong:1"
            self.reject(value, "REFERENCE")
        # Repository-free work can request capacity without fabricating lineage.
        value = fixture()
        request = copy.deepcopy(fixture("coding-link-v1.json")["attempts"][0]["capacity"])
        request.update(work_id=value["work"]["id"], run_id=value["runs"][0]["id"],
                       attempt_id=value["attempts"][0]["id"],
                       operation_id=value["attempts"][0]["operation_id"])
        request["class"] = "remote_static"
        request["resources"]["workers"]["quantity"] = 0
        value["attempts"][0]["capacity"] = request
        self.assertIsNone(CONTRACT.validate_bundle(value))

    def test_typed_effects_inert_replay_and_conflict(self):
        value = fixture("coding-link-v1.json")
        value["effects"].append(copy.deepcopy(value["effects"][0]))
        value["effects"][1]["observation"] = "unknown"
        self.assertIsNone(CONTRACT.validate_bundle(value))
        value["effects"][1]["target"] = "destination:other"
        self.reject(value, "OPERATION_CONFLICT")
        value = fixture("coding-link-v1.json")
        value["effects"][0]["operation_id"] = value["attempts"][0]["operation_id"]
        self.reject(value, "OPERATION_CONFLICT")
        for field, replacement in (("kind", "shell"), ("observation", "accepted"),
                                   ("artifact", {"id": "artifact:patch", "revision": revision("patch:2")})):
            value = fixture("coding-link-v1.json")
            value["effects"][0][field] = replacement
            self.reject(value)

    def test_schema_is_local_closed_shape_not_runtime_dependency(self):
        schema = json.loads((ROOT / "docs/portable-work-contract-v1.schema.json").read_bytes())
        self.assertEqual(schema["properties"]["kind"]["const"], "portable-work-bundle")
        self.assertEqual(schema["properties"]["version"]["const"], 1)
        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node["additionalProperties"], False)
                    self.assertLessEqual(set(node.get("required", [])), set(node["properties"]))
                if "$ref" in node:
                    self.assertTrue(node["$ref"].startswith("#/$defs/"))
                    self.assertIn(node["$ref"].removeprefix("#/$defs/"), schema["$defs"])
                for child in node.values():
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)
        walk(schema)

    def test_no_import_or_validation_side_effects(self):
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
        self.assertEqual([alias.name for node in imports for alias in node.names], ["json", "re"])
        code = compile(tree, str(SOURCE), "exec")
        value = fixture()
        value["work"]["outcome"] = '$(touch forbidden); python -c "raise SystemExit"'
        value["work"]["constraints"] = ['[brackets] {inert} "quotes" \\slashes']
        raw = json.dumps(value).encode("utf-8")
        before = copy.deepcopy(value)
        module = types.ModuleType("instrumented_portable_contract")
        original_import = builtins.__import__
        def limited_import(name, *args, **kwargs):
            self.assertIn(name, ("json", "re"))
            return original_import(name, *args, **kwargs)
        def forbidden(*args, **kwargs):
            raise AssertionError("I/O or execution attempted")
        # Sources and fixtures are materialized before instrumentation; importing
        # the module itself is included, unlike a check only after import.
        with ExitStack() as stack:
            for owner, name in ((builtins, "open"), (io, "open"), (os, "open"),
                                (os, "getenv"), (os, "getcwd"), (os, "listdir"),
                                (os, "stat"), (os, "system"), (subprocess, "Popen"),
                                (socket, "socket"), (socket, "getaddrinfo")):
                stack.enter_context(patch.object(owner, name, forbidden))
            stack.enter_context(patch.object(builtins, "__import__", limited_import))
            stack.enter_context(patch.object(os, "environ", {}))
            stdout = stack.enter_context(patch.object(sys, "stdout", io.StringIO()))
            stderr = stack.enter_context(patch.object(sys, "stderr", io.StringIO()))
            exec(code, module.__dict__)
            self.assertIsNone(module.validate_bundle(value))
            self.assertEqual(module.decode_bundle(raw), before)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(value, before)


if __name__ == "__main__":
    unittest.main()
