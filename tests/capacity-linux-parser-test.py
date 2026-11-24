"""Offline synthetic fixtures; execute only in the reviewed workspace sandbox."""

import ast
import builtins
import copy
import importlib.util
import io
import os
import socket
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import patch


PARSER_PATH = Path(__file__).resolve().parent.parent / "scripts/capacity-linux-parser.py"
PARSER_SOURCE = PARSER_PATH.read_text(encoding="utf-8")
SPEC = importlib.util.spec_from_file_location("capacity_linux_parser", PARSER_PATH)
assert SPEC is not None and SPEC.loader is not None
PARSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARSER)
U64 = (1 << 64) - 1
METRICS = (
    "cpu.max", "memory.max", "memory.current",
    "cpu.pressure", "memory.pressure", "io.pressure",
)
PSI = "some avg10=0.00 avg60=1.23 avg300=100.00 total=0\nfull avg10=2.01 avg60=0.01 avg300=0.00 total=42\n"


def context():
    return {
        "producer_id": "fixture",
        "producer_version": "1",
        "collector_instance_id": "collector:1",
        "domain_id": "cgroup:fixture",
        "boot_id": "boot-1",
        "clock_domain_id": "clock-1",
        "backing": {"kind": "declared", "domain_id": "vm:fixture"},
        "start_ns": 10,
        "end_ns": 20,
        "sequence": 0,
        "policy_digest": "a" * 64,
        "config_digest": "b" * 64,
    }


def source(text, complete=True):
    return {"kind": "text", "text": text, "complete": complete}


def sample_text(metric):
    if metric.endswith(".pressure"):
        return PSI
    return "1000 100000\n" if metric == "cpu.max" else "0\n"


class StringSubclass(str):
    pass


class IntSubclass(int):
    pass


class DictSubclass(dict):
    pass


class Trap:
    """A rejected object must not get a chance to coerce or compare itself."""

    def __str__(self):
        raise AssertionError("coercion")

    def __int__(self):
        raise AssertionError("coercion")

    def __eq__(self, other):
        raise AssertionError("comparison")

    def __bool__(self):
        raise AssertionError("truthiness")


class ParserTests(unittest.TestCase):
    def parse(self, metric, text, ctx=None):
        return PARSER.parse_sample(metric, source(text), context() if ctx is None else ctx)

    def refuses(self, code, metric="memory.current", src=None, ctx=None):
        if src is None:
            src = source("0\n")
        if ctx is None:
            ctx = context()
        with self.assertRaises(PARSER.ParseError) as caught:
            PARSER.parse_sample(metric, src, ctx)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)
        self.assertEqual(caught.exception.args, (code,))

    def bad_text(self, code, text, metric="memory.current"):
        self.refuses(code, metric, source(text))

    def test_envelope_and_exact_fraction(self):
        ctx = context()
        output = self.parse("cpu.max", "1501 100001\n", ctx)
        self.assertEqual(output, {
            "format": "capacity-linux-observation", "version": 1,
            "metric": "cpu.max", "context": ctx, "duration_ns": 10,
            "result": {"kind": "cpu_quota", "unit": "microseconds",
                       "quota": {"kind": "finite", "value": 1501}, "period": 100001},
        })

    def test_cpu_boundaries(self):
        for quota in (1000, 1001, U64):
            for period in (1000, 1000000):
                with self.subTest(quota=quota, period=period):
                    result = self.parse("cpu.max", f"{quota} {period}\n")["result"]
                    self.assertEqual(result["quota"], {"kind": "finite", "value": quota})
                    self.assertEqual(result["period"], period)
        for period in (1000, 1000000):
            self.assertEqual(self.parse("cpu.max", f"max {period}\n")["result"], {
                "kind": "cpu_quota", "unit": "microseconds",
                "quota": {"kind": "unlimited"}, "period": period,
            })
        for text in ("0 1000\n", "999 1000\n", f"{U64 + 1} 1000\n",
                     "1000 0\n", "1000 999\n", "1000 1000001\n", f"1000 {U64}\n"):
            self.bad_text("RANGE", text, "cpu.max")
        self.bad_text("DECIMAL", "1000 max\n", "cpu.max")

    def test_memory_boundaries_and_distinct_states(self):
        for metric in ("memory.max", "memory.current"):
            for number in (0, 1, U64):
                self.assertEqual(self.parse(metric, f"{number}\n")["result"], {
                    "kind": "finite", "unit": "bytes", "value": number,
                })
            self.bad_text("RANGE", f"{U64 + 1}\n", metric)
        self.assertEqual(self.parse("memory.max", "max\n")["result"], {
            "kind": "unlimited", "unit": "bytes",
        })
        self.bad_text("DECIMAL", "max\n")
        kinds = [self.parse("memory.max", text)["result"]["kind"] for text in ("0\n", "max\n")]
        kinds.append(PARSER.parse_sample("memory.max", {
            "kind": "unavailable", "reason": "unsupported",
        }, context())["result"]["kind"])
        self.assertEqual(kinds, ["finite", "unlimited", "unavailable"])

    def test_unsigned_canonical_decimal(self):
        for token in ("-1", "+1", "00", "01", "1.0", "1e3", "0x10", "1_000", "MAX"):
            for metric in ("memory.max", "memory.current", "cpu.max"):
                text = token + (" 1000\n" if metric == "cpu.max" else "\n")
                with self.subTest(token=token, metric=metric):
                    self.bad_text("DECIMAL", text, metric)
            self.bad_text("DECIMAL", PSI.replace("total=42", f"total={token}"), "io.pressure")
        self.bad_text("LIMIT", "1" * 21 + "\n")
        self.bad_text("LIMIT", "0" * 21 + "\n")

    def test_pressure_values_and_ordering(self):
        expected = {
            "kind": "pressure", "average_unit": "percent_hundredths", "total_unit": "microseconds",
            "rows": {"some": {"avg10": 0, "avg60": 123, "avg300": 10000, "total": 0},
                     "full": {"avg10": 201, "avg60": 1, "avg300": 0, "total": 42}},
        }
        for metric in METRICS[3:]:
            self.assertEqual(self.parse(metric, PSI)["result"], expected)
            reordered = "\n".join(
                "\t" + " \t".join([line.split()[0], *reversed(line.split()[1:])]) + " \t"
                for line in reversed(PSI.rstrip("\n").split("\n"))
            ) + "\n"
            self.assertEqual(self.parse(metric, reordered)["result"], expected)
            text = PSI.replace("total=42", f"total={U64}")
            self.assertEqual(self.parse(metric, text)["result"]["rows"]["full"]["total"], U64)
            self.bad_text("RANGE", PSI.replace("total=42", f"total={U64 + 1}"), metric)

    def test_pressure_averages(self):
        for token, expected in (("0.00", 0), ("0.01", 1), ("99.99", 9999), ("100.00", 10000)):
            text = PSI.replace("avg10=0.00", f"avg10={token}")
            self.assertEqual(self.parse("cpu.pressure", text)["result"]["rows"]["some"]["avg10"], expected)
        for token in ("0", "0.0", "0.000", ".00", "00.00", "+0.00", "-0.00", "1e0", "1.a0", "1.0a", "1..00"):
            self.bad_text("DECIMAL", PSI.replace("avg10=0.00", f"avg10={token}"), "cpu.pressure")
        for token in ("100.01", "101.00", f"{U64}.00"):
            self.bad_text("RANGE", PSI.replace("avg10=0.00", f"avg10={token}"), "cpu.pressure")
        self.bad_text("LIMIT", PSI.replace("avg10=0.00", "avg10=" + "1" * 21 + ".00"), "cpu.pressure")

    def test_pressure_missing_duplicate_unknown_and_malformed(self):
        for metric in METRICS[3:]:
            for row in PSI.splitlines(keepends=True):
                self.bad_text("INCOMPLETE", row, metric)
                self.bad_text("DUPLICATE_FIELD", row + row, metric)
            for key in ("avg10", "avg60", "avg300", "total"):
                fields = PSI.splitlines()[0].split()
                token = next(field for field in fields[1:] if field.startswith(key + "="))
                self.bad_text("INCOMPLETE", PSI.replace(" " + token, "", 1), metric)
                self.bad_text("DUPLICATE_FIELD", PSI.replace(token, token + " " + token, 1), metric)
            self.bad_text("UNKNOWN_FIELD", PSI.replace("some ", "other "), metric)
            self.bad_text("UNKNOWN_FIELD", PSI.replace("avg10=", "avg20=", 1), metric)
            self.bad_text("SHAPE", PSI.replace("total=42", "total==42"), metric)
            self.bad_text("SHAPE", PSI.replace("total=42", "total"), metric)
            self.bad_text("DECIMAL", PSI.replace("total=42", "total="), metric)
            self.bad_text("SHAPE", PSI + "\n", metric)
            self.bad_text("SHAPE", PSI.replace("\nfull", "\n\nfull"), metric)

    def test_truncation_and_incomplete_assertion(self):
        for metric in METRICS:
            text = sample_text(metric)
            for prefix_length in range(len(text)):
                prefix = text[:prefix_length]
                with self.subTest(metric=metric, prefix_length=prefix_length):
                    self.refuses("INCOMPLETE", metric, source(prefix, complete=False))
                    # The only LF-terminated proper prefix is a complete PSI row.
                    self.bad_text("INCOMPLETE", prefix, metric)
            self.refuses("INCOMPLETE", metric, source(text, complete=False))
            for empty in ("", "\n", " \t\n"):
                self.bad_text("INCOMPLETE", empty, metric)
        self.bad_text("INCOMPLETE", "1000\n", "cpu.max")
        self.bad_text("INCOMPLETE", "max\n", "cpu.max")

    def test_text_bounds_whitespace_and_encoding(self):
        for metric in METRICS:
            text = sample_text(metric)
            limit = 1024 if metric.endswith(".pressure") else 128
            padded = " " * (limit - len(text)) + text
            self.assertEqual(self.parse(metric, padded), self.parse(metric, text))
            self.bad_text("LIMIT", " " + padded, metric)
            self.bad_text("LIMIT", "1" * 100000, metric)
            for bad in ("\r", "\x00", "\x0b", "\x0c", "\x7f", "é", "１", "\u2028", "\ud800"):
                self.bad_text("ENCODING", bad + text, metric)
            self.refuses("SHAPE", metric, source(text.encode("ascii")))
            self.refuses("SHAPE", metric, source(StringSubclass(text)))
        self.assertEqual(self.parse("cpu.max", " \t1000\t 100000 \t\n"), self.parse("cpu.max", "1000 100000\n"))
        for text in ("0 1\n", "0\n0\n", "0\n\n"):
            self.bad_text("SHAPE", text)
        self.bad_text("SHAPE", "1000 1000 1000\n", "cpu.max")
        # Size and encoding gates precede completeness/tokenization.
        self.refuses("LIMIT", src=source("é" * 129, False))
        self.refuses("ENCODING", src=source("\r", False))

    def test_unavailable(self):
        for metric in METRICS:
            for reason in ("not_collected", "not_visible", "permission_denied", "unsupported", "inapplicable", "read_failed"):
                src = {"kind": "unavailable", "reason": reason}
                result = PARSER.parse_sample(metric, src, context())["result"]
                self.assertEqual(result, src)
                self.assertIsNot(result, src)
        for reason in ("", "ENOENT", "raw private error", None, True, Trap(), StringSubclass("unsupported")):
            self.refuses("SHAPE", src={"kind": "unavailable", "reason": reason})
        self.refuses("UNKNOWN_FIELD", src={"kind": "unavailable", "reason": "unsupported", "text": "0\n"})

    def test_asserted_metadata_is_not_cross_sample_verification(self):
        # No stateful sequence/digest/boot/clock policy, or ancestry inference.
        first_context = context()
        first_context.update(sequence=U64, start_ns=U64, end_ns=U64)
        self.parse("memory.current", f"{U64}\n", first_context)
        second_context = context()
        second_context.update(sequence=0, start_ns=0, end_ns=0, boot_id="other-boot")
        second_context["backing"]["domain_id"] = second_context["domain_id"]
        result = self.parse("memory.current", "0\n", second_context)
        self.assertEqual(result["context"], second_context)
        self.assertEqual(result["duration_ns"], 0)
        # Independent local max/current samples are not an effective-limit fit test.
        self.parse("memory.max", "0\n", second_context)
        self.parse("memory.current", f"{U64}\n", second_context)

    def test_closed_source_and_metric(self):
        for metric in (None, [], {}, 0, True, Trap(), "cpu.weight", StringSubclass("cpu.max")):
            self.refuses("SHAPE", metric=metric)
        for src in ([], None, "0\n", DictSubclass(source("0\n"))):
            # None is the helper's default, so invoke directly for that one.
            if src is None:
                with self.assertRaises(PARSER.ParseError):
                    PARSER.parse_sample("memory.current", None, context())
            else:
                self.refuses("SHAPE", src=src)
        for field in ("kind", "text", "complete"):
            src = source("0\n")
            del src[field]
            self.refuses("SHAPE", src=src)
        for value in (None, 0, 1, "true", Trap()):
            self.refuses("SHAPE", src=source("0\n", value))
        for kind in ("other", None, Trap(), StringSubclass("text")):
            src = source("0\n")
            src["kind"] = kind
            self.refuses("SHAPE", src=src)
        self.refuses("SHAPE", src={StringSubclass("kind"): "text", "text": "0\n", "complete": True})
        for extra in ("healthy", "fresh", "verified", "admitted", "entitlement"):
            src = source("0\n")
            src[extra] = True
            self.refuses("UNKNOWN_FIELD", src=src)

    def test_context_closed_types_and_integer_boundaries(self):
        for key in context():
            ctx = context()
            del ctx[key]
            self.refuses("SHAPE", ctx=ctx)
        for key in ("healthy", "fresh", "verified", "admitted", "entitlement"):
            ctx = context()
            ctx[key] = True
            self.refuses("UNKNOWN_FIELD", ctx=ctx)
        for ctx in ([], "context", Trap(), DictSubclass(context())):
            self.refuses("SHAPE", ctx=ctx)
        ctx = context()
        ctx[StringSubclass("producer_id")] = ctx.pop("producer_id")
        self.refuses("SHAPE", ctx=ctx)
        for key in ("start_ns", "end_ns", "sequence"):
            for value in (True, False, 0.0, "0", None, IntSubclass(0), Trap()):
                ctx = context()
                ctx[key] = value
                self.refuses("SHAPE", ctx=ctx)
            for value in (-1, U64 + 1):
                ctx = context()
                ctx[key] = value
                self.refuses("RANGE", ctx=ctx)
        for start, end, duration in ((0, 0, 0), (U64, U64, 0), (0, U64, U64)):
            ctx = context()
            ctx.update(start_ns=start, end_ns=end, sequence=U64)
            self.assertEqual(self.parse("memory.current", "0\n", ctx)["duration_ns"], duration)
        ctx = context()
        ctx.update(start_ns=21, end_ns=20)
        self.refuses("RANGE", ctx=ctx)

    def test_context_identity_digest_and_backing(self):
        identities = ("producer_id", "producer_version", "collector_instance_id", "domain_id", "boot_id", "clock_domain_id")
        for key in identities:
            for good in ("0", "a" * 256, "A._:/@+-09"):
                ctx = context()
                ctx[key] = good
                self.assertEqual(self.parse("memory.current", "0\n", ctx)["context"][key], good)
            for bad in ("", "a b", "-a", "/a", "é", "a\n", "a\\b", 1, None, Trap(), StringSubclass("a")):
                ctx = context()
                ctx[key] = bad
                self.refuses("SHAPE", ctx=ctx)
            ctx = context()
            ctx[key] = "a" * 257
            self.refuses("LIMIT", ctx=ctx)
        for key in ("policy_digest", "config_digest"):
            for bad in ("a" * 63, "a" * 65, "g" * 64, "A" * 64, "é" * 64, 0, True, StringSubclass("a" * 64), Trap()):
                ctx = context()
                ctx[key] = bad
                self.refuses("SHAPE", ctx=ctx)
        ctx = context()
        ctx["backing"] = {"kind": "unavailable"}
        self.assertEqual(self.parse("memory.current", "0\n", ctx)["context"]["backing"], {"kind": "unavailable"})
        for bad, code in (
            ({}, "SHAPE"), ({"kind": "declared"}, "SHAPE"),
            ({"kind": "declared", "domain_id": ""}, "SHAPE"),
            ({"kind": "unavailable", "domain_id": "a"}, "UNKNOWN_FIELD"),
            ({"kind": "unavailable", "reason": "unsupported"}, "UNKNOWN_FIELD"),
            ({"kind": "other"}, "SHAPE"), ({"kind": Trap()}, "SHAPE"),
            ({StringSubclass("kind"): "unavailable"}, "SHAPE"),
            (DictSubclass({"kind": "unavailable"}), "SHAPE"), (None, "SHAPE"),
        ):
            ctx = context()
            ctx["backing"] = bad
            self.refuses(code, ctx=ctx)

    def test_copies_and_no_input_mutation_even_on_refusal(self):
        for metric in METRICS:
            ctx = context()
            src = source(sample_text(metric))
            before = copy.deepcopy((src, ctx))
            first = PARSER.parse_sample(metric, src, ctx)
            second = PARSER.parse_sample(metric, src, ctx)
            self.assertEqual((src, ctx), before)
            self.assertEqual(first, second)
            self.assertIsNot(first, second)
            self.assertIsNot(first["result"], second["result"])
            self.assertIsNot(first["context"], ctx)
            self.assertIsNot(first["context"]["backing"], ctx["backing"])
            first["context"]["backing"]["domain_id"] = "changed"
            self.assertEqual(ctx, before[1])
            self.assertEqual(second["context"], before[1])
            if metric.endswith(".pressure"):
                first["result"]["rows"]["some"]["total"] = 999
                self.assertEqual(second["result"]["rows"]["some"]["total"], 0)
            if metric == "cpu.max":
                first["result"]["quota"]["value"] = 999
                self.assertEqual(second["result"]["quota"]["value"], 1000)
            src["complete"] = False
            before = copy.deepcopy((src, ctx))
            self.refuses("INCOMPLETE", metric, src, ctx)
            self.assertEqual((src, ctx), before)

    def test_no_effects_or_dynamic_dependencies(self):
        tree = ast.parse(PARSER_SOURCE)
        self.assertFalse(any(isinstance(node, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)) for node in ast.walk(tree)))
        # Constrain call targets, not just imports: catches built-in I/O/eval and
        # attribute-based access to external effects without executing them.
        allowed_calls = {
            "super", "type", "len", "any", "int", "ParseError", "_record", "_opaque",
            "_u64", "_digest", "_context", "_decimal", "_average", "_text", "_scalar", "_pressure",
        }
        allowed_methods = {"__init__", "get", "split", "count", "isascii", "endswith", "strip"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.assertIn(node.func.id, allowed_calls)
                else:
                    self.assertIsInstance(node.func, ast.Attribute)
                    self.assertIn(node.func.attr, allowed_methods)
        # Test tools may do I/O to load the reviewed module. Calls under test may not.
        with patch.object(builtins, "open", side_effect=AssertionError("file I/O")), \
             patch.object(io, "open", side_effect=AssertionError("file I/O")), \
             patch.object(os, "getenv", side_effect=AssertionError("environment")), \
             patch.object(time, "time", side_effect=AssertionError("clock")), \
             patch.object(time, "monotonic", side_effect=AssertionError("clock")), \
             patch.object(socket, "socket", side_effect=AssertionError("network")), \
             patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
            for metric in METRICS:
                self.assertEqual(self.parse(metric, sample_text(metric)), self.parse(metric, sample_text(metric)))
                self.bad_text("INCOMPLETE", "", metric)
                self.refuses("SHAPE", metric, source(Trap()))


if __name__ == "__main__":
    unittest.main()
