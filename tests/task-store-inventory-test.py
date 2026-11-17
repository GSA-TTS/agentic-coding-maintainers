#!/usr/bin/env python3
"""Structural contract for docs/TASK-STORE-INVENTORY.md.

Reads the document and pinned Git blobs as text only; never executes inventoried code.
Structural checks run independently of historical range validation. If the pin is
unavailable, the historical test explicitly reports UNVERIFIED as a skip. Historical
success checks paths and ranges at the pin, not citation meaning or current-file validity.
"""

import functools
import os
import re
import subprocess
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/TASK-STORE-INVENTORY.md"
PINNED_SHA = "159bc1fc7593fc420d0d6d580199ddc7edea08dc"

SECTIONS = [
    "Status and scope", "Enumeration method", "Core store: orchestrator-state.py",
    "Consumers: skill controllers", "Consumers: root scripts and wrappers",
    "Consumer assumptions", "Tests and fixtures", "Adjacent reservation and lock directories",
    "Authority boundary", "Findings", "Unknowns and not inspected",
    "PROPOSED: task-store seam (not implemented)", "Links",
]
PROPOSED_SUBSECTIONS = [
    "Evidence that shapes the seam", "Smallest seam (recommendation)",
    "Invariants the seam must preserve (each cited to source)",
    "What must remain outside the seam", "Compatibility and rollback risks",
    "Migration order (recommendation; each step its own reviewed change)",
    "Decisions for the maintainer",
]
CONSUMER_HEADER = ["ID", "Consumer", "Evidence", "Operations", "Schemas", "Lock", "Basis"]
TABLES = {
    "Enumeration method": [["Step", "Command (at the pinned SHA)", "Result"],
                           ["Absence claim", "Command (narrow)", "Result"]],
    "Core store: orchestrator-state.py": [CONSUMER_HEADER],
    "Consumers: skill controllers": [CONSUMER_HEADER],
    "Consumers: root scripts and wrappers": [CONSUMER_HEADER],
    "Consumer assumptions": [["ID", "Durability / atomicity", "Extension keys", "Failure mode",
                              "Coupling", "Tests", "Evidence"]],
    "Tests and fixtures": [["ID", "Test or fixture", "Evidence", "Couples to", "Basis"]],
    "Adjacent reservation and lock directories": [
        ["Directory under .orchestrator/", "Evidence", "Writers", "Readers", "Basis"]],
    "Authority boundary": [["Fact", "Where it lives", "Evidence", "Basis"]],
    "Findings": [["ID", "Finding", "Evidence", "Basis"]],
    "Unknowns and not inspected": [["ID", "Item", "Why unknown", "Next action"]],
    "Evidence that shapes the seam": [["Claim", "Kind", "Evidence"]],
    "Smallest seam (recommendation)": [["Operation", "Shape", "Replaces", "Justification"]],
    "Invariants the seam must preserve (each cited to source)": [["Invariant", "Evidence"]],
    "What must remain outside the seam": [["Item", "Reason", "Basis"]],
    "Compatibility and rollback risks": [["Risk", "Kind", "Evidence", "Mitigation (recommendation)"]],
    "Migration order (recommendation; each step its own reviewed change)": [
        ["Step", "Change", "Behavior change", "Prerequisite"]],
    "Decisions for the maintainer": [["ID", "Decision", "Options", "Default if silent"]],
}
BASIS_VALUES = {"observed", "derived", "inferred", "documented", "unknown"}
KIND_VALUES = BASIS_VALUES | {"recommendation"}
SPAN = re.compile(r"`([^`\n]+)`")
CITATION = re.compile(r"^(?:([A-Za-z0-9_./-]+))?:(\d+)(?:-(\d+))?$")
PERMALINK = re.compile(
    r"https://github\.com/GSA-TTS/agentic-coding-maintainers/blob/([0-9a-f]{40})/([^\s#)]+)#L(\d+)(?:-L(\d+))?")
ID_REF = re.compile(r"\b(?:[CSRTWFUD]\d{1,2})\b")
PATHLIKE = re.compile(r"^[A-Za-z0-9_./-]+$")


def text():
    return DOC.read_text(encoding="utf-8")


def split_row(line):
    cells = re.split(r"(?<!\\)\|", line.strip())
    return [cell.strip().replace("\\|", "|") for cell in cells[1:-1]]


def strip_ticks(value):
    return value.replace("`", "").strip()


def parse(source):
    """Return (front matter dict, sections) where sections keep heading, level and tables."""
    match = re.match(r"^---\n(.*?)\n---\n", source, re.DOTALL)
    meta = {}
    if match:
        for line in match.group(1).splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip('"')
    sections, current, table = [], None, None
    fenced = False
    for line in source.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = re.match(r"^(#{2,3}) (.+)$", line)
        if heading:
            current = {"level": len(heading.group(1)), "title": heading.group(2).strip(),
                       "tables": [], "lines": []}
            sections.append(current)
            table = None
            continue
        if current is None:
            continue
        current["lines"].append(line)
        if line.startswith("|"):
            if table is None:
                table = {"header": [strip_ticks(c) for c in split_row(line)], "rows": [], "separator": False}
                current["tables"].append(table)
            elif not table["separator"]:
                table["separator"] = bool(re.fullmatch(r"\|[\s:|-]+\|", line.strip()))
            else:
                table["rows"].append(split_row(line))
        else:
            table = None
    return meta, sections


def git_read(*args):
    """Local object reads only, with replacement objects and lazy fetching disabled."""
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(ROOT), *args],
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"},
        capture_output=True, timeout=30, check=False)


class PinUnavailable(Exception):
    """Historical evidence could not be checked; structural tests may still run."""


class PinnedSource:
    def __init__(self):
        try:
            done = git_read("cat-file", "-e", PINNED_SHA + "^{commit}")
        except (OSError, subprocess.SubprocessError) as exc:
            raise PinUnavailable("UNVERIFIED: historical citations skipped; pin unavailable") from exc
        if done.returncode:
            raise PinUnavailable("UNVERIFIED: historical citations skipped; pin unavailable")
        tree = git_read("ls-tree", "-rz", "--full-tree", PINNED_SHA)
        if tree.returncode:
            raise AssertionError("pinned tree could not be read")
        self.paths = set()
        self.names = {}
        for entry in tree.stdout.split(b"\0"):
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            mode, kind, _ = metadata.split()
            if kind != b"blob" or mode not in {b"100644", b"100755"}:
                continue
            path = raw_path.decode("utf-8")
            self.paths.add(path)
            self.names.setdefault(PurePosixPath(path).name, []).append(path)

    def resolve(self, path):
        """Resolve only against the exact pinned tree, regardless of current files."""
        if not path or path.startswith("/") or any(p in {"", ".", ".."} for p in path.split("/")):
            return None
        if "/" in path:
            return path if path in self.paths else None
        found = self.names.get(path, [])
        return found[0] if len(found) == 1 else None

    @functools.lru_cache(maxsize=None)
    def line_count(self, path):
        if path not in self.paths:
            raise AssertionError(f"citation absent from pinned tree: {path}")
        done = git_read("cat-file", "blob", f"{PINNED_SHA}:{path}")
        if done.returncode:
            raise AssertionError(f"pinned blob could not be read: {path}")
        return len(done.stdout.decode("utf-8").splitlines())


def row_citations(cells, base):
    """Yield (span, cited path or None, start, end), independent of Git availability."""
    for cell in cells:
        for span in SPAN.findall(cell):
            match = CITATION.match(span)
            if not match:
                continue
            path = match.group(1) or base
            start = int(match.group(2))
            end = int(match.group(3) or match.group(2))
            yield span, path, start, end


def row_base(cells):
    """First path-like span without a line suffix, else the first one with a suffix."""
    spans = [s for cell in cells for s in SPAN.findall(cell)]
    paths = [s for s in spans if PATHLIKE.match(s) and ("/" in s or re.search(r"\.(py|sh|md|json)$", s)
                                                          or s == "Makefile")]
    if paths:
        return paths[0]
    cited = [CITATION.match(s).group(1) for s in spans if CITATION.match(s) and CITATION.match(s).group(1)]
    return cited[0] if cited else None


def all_rows(sections):
    for section in sections:
        for table in section["tables"]:
            for row in table["rows"]:
                yield section, table, row


class TaskStoreInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = text()
        cls.meta, cls.sections = parse(cls.source)
        cls.by_title = {s["title"]: s for s in cls.sections}

    def test_front_matter(self):
        self.assertEqual(self.meta.get("status"), "proposed")
        self.assertEqual(self.meta.get("tier"), "2")
        for key in ("title", "description"):
            self.assertTrue(self.meta.get(key), key)

    def test_pinned_sha_is_declared_main_sha(self):
        self.assertEqual(self.meta.get("source_sha"), PINNED_SHA)
        self.assertIn(f"`{PINNED_SHA}`", self.source)
        for match in PERMALINK.finditer(self.source):
            self.assertEqual(match.group(1), PINNED_SHA)
        shas = set(re.findall(r"\b[0-9a-f]{40}\b", self.source))
        self.assertEqual(shas - {PINNED_SHA}, {"aa37c5542256b21585fd8a924622de7b85ee954d"})

    def test_required_sections_in_order(self):
        titles = [s["title"] for s in self.sections if s["level"] == 2]
        self.assertEqual(titles, SECTIONS)
        proposed = [s["title"] for s in self.sections if s["level"] == 3]
        self.assertEqual(proposed, PROPOSED_SUBSECTIONS)
        order = [s["title"] for s in self.sections]
        self.assertLess(order.index("Unknowns and not inspected"),
                        order.index("PROPOSED: task-store seam (not implemented)"))
        self.assertLess(order.index("PROPOSED: task-store seam (not implemented)"),
                        order.index(PROPOSED_SUBSECTIONS[0]))

    def test_table_columns(self):
        for title, expected in TABLES.items():
            section = self.by_title[title]
            headers = [t["header"] for t in section["tables"]]
            self.assertEqual(headers, expected, title)
            for table in section["tables"]:
                self.assertTrue(table["separator"], title)
                self.assertTrue(table["rows"], title)
                for row in table["rows"]:
                    self.assertEqual(len(row), len(table["header"]), (title, row[:1]))

    def test_historical_citations_resolve_to_pinned_ranges(self):
        try:
            history = PinnedSource()
        except PinUnavailable as exc:
            self.skipTest(str(exc))
        checked = 0
        for section in self.sections:
            for table in section["tables"]:
                for row in table["rows"]:
                    base = row_base(row)
                    if re.fullmatch(r"[A-Z]\d{1,2}", row[0]):
                        base = self.id_base(row[0]) or base
                    for span, cited, start, end in row_citations(row, base):
                        with self.subTest(section=section["title"], row=row[0], citation=span):
                            path = history.resolve(cited)
                            self.assertIsNotNone(path, "citation path does not resolve to one file")
                            self.assertGreaterEqual(start, 1)
                            self.assertLessEqual(start, end)
                            self.assertLessEqual(end, history.line_count(path))
                        checked += 1
            prose = "\n".join(line for line in section["lines"] if not line.startswith("|"))
            for span, cited, start, end in row_citations([prose], None):
                with self.subTest(section=section["title"], prose=span):
                    path = history.resolve(cited)
                    self.assertIsNotNone(path)
                    self.assertGreaterEqual(start, 1)
                    self.assertLessEqual(start, end)
                    self.assertLessEqual(end, history.line_count(path))
                checked += 1
        for match in PERMALINK.finditer(self.source):
            path = history.resolve(match.group(2))
            end = int(match.group(4) or match.group(3))
            self.assertIsNotNone(path, match.group(2))
            self.assertGreaterEqual(int(match.group(3)), 1)
            self.assertLessEqual(int(match.group(3)), end)
            self.assertLessEqual(end, history.line_count(path))
        self.assertGreater(checked, 150)

    @classmethod
    def id_base(cls, identifier):
        """Path for an ID taken from the first table where its row names a file."""
        for section in cls.sections:
            for table in section["tables"]:
                for row in table["rows"]:
                    if row[0] == identifier and row_base(row[:2]):
                        return row_base(row[:2])
        return None

    def test_cited_paths_are_relative(self):
        for _, _, row in all_rows(self.sections):
            for cell in row:
                for span in SPAN.findall(cell):
                    match = CITATION.match(span)
                    if match and match.group(1) and "/" in match.group(1):
                        self.assertFalse(match.group(1).startswith(("/", "..")), span)

    def test_inferred_rows_have_line_evidence(self):
        inferred = 0
        for section, table, row in all_rows(self.sections):
            header = table["header"]
            for name in ("Basis", "Kind"):
                if name in header and row[header.index(name)].strip() == "inferred":
                    inferred += 1
                    base = self.id_base(row[0]) if re.fullmatch(r"[A-Z]\d{1,2}", row[0]) else None
                    cited = [path for _, path, _, _ in row_citations(row, base or row_base(row))]
                    self.assertTrue(cited and all(path is not None for path in cited),
                                    (section["title"], row[0], "inferred row needs named line evidence"))
        self.assertGreaterEqual(inferred, 1)

    def test_classified_rows_cite_evidence_or_an_inventory_id(self):
        for section, table, row in all_rows(self.sections):
            header = table["header"]
            for name in ("Basis", "Kind"):
                if name not in header:
                    continue
                value = row[header.index(name)].strip()
                self.assertIn(value, KIND_VALUES, (section["title"], row[0]))
                joined = " ".join(row)
                has_citation = any(True for _ in row_citations(row, row_base(row)))
                has_reference = bool(ID_REF.search(joined)) or "docs/" in joined
                if value != "recommendation":
                    self.assertTrue(has_citation or has_reference, (section["title"], row[0]))

    def test_every_consumer_has_an_assumptions_row_and_known_tests(self):
        consumers = []
        for title in ("Core store: orchestrator-state.py", "Consumers: skill controllers",
                      "Consumers: root scripts and wrappers"):
            consumers += [row[0] for row in self.by_title[title]["tables"][0]["rows"]]
        self.assertEqual(len(consumers), len(set(consumers)))
        assumptions = self.by_title["Consumer assumptions"]["tables"][0]["rows"]
        self.assertEqual(sorted(row[0] for row in assumptions), sorted(consumers))
        tests = {row[0] for row in self.by_title["Tests and fixtures"]["tables"][0]["rows"]}
        for row in assumptions:
            for ref in re.findall(r"\bT\d{1,2}\b", row[5]):
                self.assertIn(ref, tests, (row[0], ref))
            for cell in row[1:]:
                self.assertTrue(cell.strip(), row[0])

    def test_every_test_row_is_referenced_and_ids_are_unique(self):
        # An ID may recur across tables (a consumer has an access row and an
        # assumptions row); within one table it must be unique.
        for section in self.sections:
            for table in section["tables"]:
                ids = [row[0] for row in table["rows"] if re.fullmatch(r"[A-Z]\d{1,2}", row[0])]
                self.assertEqual(len(ids), len(set(ids)), (section["title"], "duplicate ID in one table"))
        tests = {row[0] for row in self.by_title["Tests and fixtures"]["tables"][0]["rows"]}
        referenced = set()
        for row in self.by_title["Consumer assumptions"]["tables"][0]["rows"]:
            referenced |= set(re.findall(r"\bT\d{1,2}\b", row[5]))
        self.assertEqual(tests - referenced, set(), "test rows no consumer row refers to")

    def test_consumer_counts_match_documented_scope(self):
        counts = {title: len(self.by_title[title]["tables"][0]["rows"]) for title in (
            "Core store: orchestrator-state.py", "Consumers: skill controllers",
            "Consumers: root scripts and wrappers", "Tests and fixtures")}
        self.assertEqual(sum(counts.values()), 12 + 19 + 14 + 29, counts)

    def test_no_stale_overclaims(self):
        for phrase in ("all observed above", "Everything above this heading is observed",
                       "Three consumers read task data", "Three controllers hold", "Checkpoint placeholder",
                       "leave the seam unhashed", "hash / not hash",
                       "checked in both directions before admission or mutation",
                       "no storage I/O", "there is no unhashed alternative", "There is no unhashed option"):
            self.assertNotIn(phrase, self.source, phrase)

    def test_decisions_and_unknowns_are_sequential(self):
        for prefix, title in (("D", "Decisions for the maintainer"), ("U", "Unknowns and not inspected")):
            ids = [row[0] for row in self.by_title[title]["tables"][0]["rows"]]
            self.assertEqual(sorted(ids, key=lambda i: int(i[1:])), ids, title)
            self.assertEqual(ids, [f"{prefix}{n}" for n in range(1, len(ids) + 1)], title)

    def test_manifest_decision_has_no_unhashed_option(self):
        row = next(r for r in self.by_title["Decisions for the maintainer"]["tables"][0]["rows"] if r[0] == "D6")
        self.assertIn("defer", row[2].lower())
        self.assertNotIn("not hash", " ".join(row))

    def test_id_references_resolve(self):
        known = set()
        for _, _, row in all_rows(self.sections):
            if re.fullmatch(r"[A-Z]\d{1,2}", row[0]):
                known.add(row[0])
        # Documented ranges such as "D1 to D8" and "S8 to S12" name endpoints that must exist.
        for ref in set(ID_REF.findall(self.source)):
            self.assertIn(ref, known, ref)

    def test_inventory_states_method_exclusions_and_unmerged_item(self):
        for needle in ("**Exclusions", "not a proof of completeness", "git grep",
                       "Static only", "No inventoried\n  code, test or build was executed"):
            self.assertIn(needle, self.source)
        status = "\n".join(self.by_title["Status and scope"]["lines"])
        self.assertIn("#168", status)
        self.assertIn("not inventoried", status.lower())

    def test_proposed_section_is_labelled_and_separated(self):
        for title in PROPOSED_SUBSECTIONS:
            self.assertIn(title, self.by_title)
        intro = "\n".join(self.by_title["PROPOSED: task-store seam (not implemented)"]["lines"])
        self.assertIn("recommendation", intro)
        self.assertIn("changes no code", intro)
        self.assertNotIn("Checkpoint placeholder", self.source)

    def test_issue_references_are_qualified(self):
        bare = re.findall(r"(?<![\w/])#(138|161|165|167|168)\b", self.source)
        # Allow the display text of a Markdown link whose target is fully qualified.
        linked = re.findall(r"\[#(138|161|165|167|168)\]\(https://github\.com/GSA-TTS/agentic-coding-maintainers/",
                            self.source)
        self.assertEqual(len(bare), len(linked), "unqualified issue or PR reference")
        for number in ("138", "161", "165", "167"):
            self.assertIn(f"GSA-TTS/agentic-coding-maintainers#{number}", self.source)

    def test_no_secret_shaped_values(self):
        for pattern in (r"gh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}",
                        r"-----BEGIN [A-Z ]*PRIVATE KEY-----"):
            self.assertIsNone(re.search(pattern, self.source), pattern)


class HistoricalSourceTests(unittest.TestCase):
    """Fake Git responses keep regression coverage available even in shallow clones."""

    def setUp(self):
        self.pin_exists = True
        self.paths = ["old/reader.py", "Makefile"]
        self.blobs = {"old/reader.py": b"old line one\nold line two\n", "Makefile": b"old target\n"}
        self.git = self.enterContext(mock.patch(__name__ + ".git_read", side_effect=self.fake_git))

    def fake_git(self, *args):
        if args == ("cat-file", "-e", PINNED_SHA + "^{commit}"):
            return subprocess.CompletedProcess(args, 0 if self.pin_exists else 1, b"", b"")
        if args == ("ls-tree", "-rz", "--full-tree", PINNED_SHA):
            tree = b"".join(b"100644 blob " + b"0" * 40 + b"\t" + p.encode() + b"\0"
                            for p in self.paths)
            return subprocess.CompletedProcess(args, 0, tree, b"")
        if len(args) == 3 and args[:2] == ("cat-file", "blob"):
            self.assertTrue(args[2].startswith(PINNED_SHA + ":"))
            data = self.blobs.get(args[2].split(":", 1)[1])
            return subprocess.CompletedProcess(args, 1 if data is None else 0, data or b"", b"")
        self.fail(f"unexpected Git request: {args}")

    def test_old_file_and_ranges_ignore_new_current_content(self):
        with mock.patch.object(Path, "read_bytes", return_value=b"new\n" * 20) as current:
            history = PinnedSource()
            self.assertEqual(history.resolve("reader.py"), "old/reader.py")
            self.assertEqual(history.line_count("old/reader.py"), 2)
            self.assertEqual(history.line_count("Makefile"), 1)
            current.assert_not_called()

    def test_new_current_file_cannot_resolve_at_pin(self):
        with mock.patch.object(Path, "is_file", return_value=True) as current:
            history = PinnedSource()
            self.assertIsNone(history.resolve("new/reader.py"))
            self.assertIsNone(history.resolve("new.py"))
            with self.assertRaisesRegex(AssertionError, "absent from pinned tree"):
                history.line_count("new/reader.py")
            current.assert_not_called()

    def test_historical_file_deleted_currently_still_resolves(self):
        with mock.patch.object(Path, "is_file", return_value=False) as current:
            history = PinnedSource()
            self.assertEqual(history.resolve("old/reader.py"), "old/reader.py")
            self.assertEqual(history.resolve("reader.py"), "old/reader.py")
            self.assertEqual(history.line_count("old/reader.py"), 2)
            current.assert_not_called()

    def test_missing_blob_with_present_pin_fails_without_current_fallback(self):
        del self.blobs["old/reader.py"]
        with mock.patch.object(Path, "read_bytes", return_value=b"current replacement\n") as current:
            history = PinnedSource()
            with self.assertRaisesRegex(AssertionError, "pinned blob could not be read"):
                history.line_count("old/reader.py")
            current.assert_not_called()

    def test_missing_pin_explicitly_skips_historical_portion(self):
        self.pin_exists = False
        result = unittest.TestResult()
        TaskStoreInventoryTests("test_historical_citations_resolve_to_pinned_ranges").run(result)
        self.assertEqual(len(result.skipped), 1)
        self.assertIn("UNVERIFIED: historical citations skipped", result.skipped[0][1])
        self.assertEqual(result.failures + result.errors, [])
        self.assertEqual(self.git.call_count, 1)
        # Structural checks still run without Git or a claim of historical success.
        structural = TaskStoreInventoryTests("test_front_matter")
        structural.meta, _ = parse(text())
        structural.run(result)
        self.assertEqual(result.testsRun, 2)
        self.assertEqual(result.failures + result.errors, [])
        self.assertEqual(self.git.call_count, 1)

    def test_ambiguous_basename_uses_pinned_tree_only(self):
        self.paths.append("another/reader.py")
        history = PinnedSource()
        self.assertIsNone(history.resolve("reader.py"))
        self.assertEqual(history.resolve("old/reader.py"), "old/reader.py")
        self.assertIsNone(history.resolve("../old/reader.py"))


if __name__ == "__main__":
    # Verbose output names historical validation and includes any UNVERIFIED skip reason.
    unittest.main(verbosity=2)
