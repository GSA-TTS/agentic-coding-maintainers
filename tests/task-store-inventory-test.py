#!/usr/bin/env python3
"""Structural contract for docs/TASK-STORE-INVENTORY.md.

Reads the document and cited files as text only. It does not import or execute any
inventoried code and makes no claim about runtime behavior. A passing run shows that the
document is well formed and that every citation still lands inside an existing file; it
does not show that a cited line still says what its row claims.
"""

import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/TASK-STORE-INVENTORY.md"
PINNED_SHA = "159bc1fc7593fc420d0d6d580199ddc7edea08dc"
SKIP_DIRS = {".git", ".orchestrator", ".import", "work", "clones", "tmp", "__pycache__"}

SECTIONS = [
    "Status and scope", "Enumeration method", "Core store: orchestrator-state.py",
    "Consumers: skill controllers", "Consumers: root scripts and wrappers",
    "Consumer assumptions", "Tests and fixtures", "Adjacent reservation and lock directories",
    "Authority boundary", "Findings", "Unknowns and not inspected",
    "PROPOSED: task-store seam (not implemented)", "Links",
]
PROPOSED_SUBSECTIONS = [
    "Evidence that shapes the seam", "Smallest seam (recommendation)",
    "Invariants the seam must preserve (all observed above)",
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
    "Invariants the seam must preserve (all observed above)": [["Invariant", "Evidence"]],
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


def source_files():
    names = {}
    for directory, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            names.setdefault(name, []).append(Path(directory, name))
    return names


def resolve(path, names):
    """Map a cited path or unique basename to a file inside the repository."""
    if "/" in path:
        candidate = (ROOT / path).resolve()
        return candidate if candidate.is_file() and candidate.is_relative_to(ROOT) else None
    found = names.get(path, [])
    return found[0] if len(found) == 1 else None


def line_count(path):
    return len(path.read_bytes().decode("utf-8", errors="replace").splitlines())


def row_citations(cells, base, names):
    """Yield (span, resolved path or None, start, end) for each citation in a row."""
    for cell in cells:
        for span in SPAN.findall(cell):
            match = CITATION.match(span)
            if not match:
                continue
            path = match.group(1) or base
            start = int(match.group(2))
            end = int(match.group(3) or match.group(2))
            yield span, (resolve(path, names) if path else None), start, end


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
        cls.names = source_files()
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
        self.assertEqual(shas - {PINNED_SHA}, {"392e501384cc7ee2084f90d573c6351321278d35"})

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

    def test_every_citation_resolves_to_a_valid_range(self):
        checked = 0
        for section in self.sections:
            for table in section["tables"]:
                for row in table["rows"]:
                    base = row_base(row)
                    if re.fullmatch(r"[A-Z]\d{1,2}", row[0]):
                        base = self.id_base(row[0]) or base
                    for span, path, start, end in row_citations(row, base, self.names):
                        with self.subTest(section=section["title"], row=row[0], citation=span):
                            self.assertIsNotNone(path, "citation path does not resolve to one file")
                            self.assertGreaterEqual(start, 1)
                            self.assertLessEqual(start, end)
                            self.assertLessEqual(end, line_count(path))
                        checked += 1
            prose = "\n".join(line for line in section["lines"] if not line.startswith("|"))
            for span, path, start, end in row_citations([prose], None, self.names):
                with self.subTest(section=section["title"], prose=span):
                    self.assertIsNotNone(path)
                    self.assertLessEqual(end, line_count(path))
                checked += 1
        for match in PERMALINK.finditer(self.source):
            path = resolve(match.group(2), self.names)
            end = int(match.group(4) or match.group(3))
            self.assertIsNotNone(path, match.group(2))
            self.assertLessEqual(end, line_count(path))
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
                    cited = any(True for _ in row_citations(row, row_base(row), self.names))
                    self.assertTrue(cited, (section["title"], row[0]))
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
                has_citation = any(True for _ in row_citations(row, row_base(row), self.names))
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


if __name__ == "__main__":
    unittest.main()
