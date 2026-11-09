#!/usr/bin/env python3
"""Offline documentation contracts, not a PR validator or policy/LLM evaluator."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs/PR-DESCRIPTIONS.md"
TEMPLATE = ROOT / ".github/pull_request_template.md"
FIXTURES = ROOT / "tests/fixtures/pr-descriptions"
ENTRYPOINTS = (
    ROOT / "AGENTS.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "docs/HUMAN-REVIEWED-DELIVERY.md",
    TEMPLATE,
)
CHECKBOXES = (
    "`make check` passes",
    "Behavior changes include offline fixture coverage",
    "Executable modes and provenance are preserved where applicable",
    "No secrets, sensitive state, CA bundles, handoffs, issue drafts, Nexus "
    "records, or engagement artifacts are included",
    "AI assistance is disclosed when it materially contributed",
)


def headings(text):
    return re.findall(r"^## (.+)$", text, re.MULTILINE)


def checkboxes(text):
    return [" ".join(value.split()) for value in re.findall(
        r"^- \[[ x]\] (.*(?:\n[ \t]+[^\n]+)*)", text, re.MULTILINE
    )]


def local_targets(path, text):
    targets = []
    canonical = "https://github.com/GSA-TTS/agentic-coding-maintainers/blob/main/"
    for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if link.startswith(canonical):
            targets.append((ROOT / link.removeprefix(canonical).split("#", 1)[0]).resolve())
        elif "://" not in link and not link.startswith("#"):
            targets.append((path.parent / link.split("#", 1)[0]).resolve())
    return targets


def explanatory_words(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"^- \[[ x]\] .*?(?=\n\S|\n\n|\Z)", "", text,
                  flags=re.MULTILINE | re.DOTALL)
    text = re.sub(r"^(?:## |Co-authored-by: ).*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"https?://\S+|`[^`]+`", "", text)
    return len(text.split())


def example_errors(text, *, repository, harness):
    """Check only the authored fixtures' declared structural contract."""
    errors = set()
    expected = (["Summary", "Validation", "Sync Impact", "AI assistance"]
                if repository else ["Summary", "Verification"])
    if headings(text) != expected:
        errors.add("sections")
    if repository and checkboxes(text) != list(CHECKBOXES):
        errors.add("checkboxes")
    for field in ("Context", "Plan", "Rollback", "Security"):
        if not re.search(rf"^- {field}: \S.+$", text, re.MULTILINE):
            errors.add("fields")
    credit = f"Co-authored-by: {harness}"
    credits = re.findall(r"^Co-authored-by: .+$", text, re.MULTILINE)
    if credits != [credit]:
        errors.add("credit")
    if not text.rstrip().endswith("\n\n" + credit):
        errors.add("ending")
    if explanatory_words(text) > 200:
        errors.add("length")
    if "<!--" in text or re.search(r"<[^>]+>", text):
        errors.add("placeholder")
    return errors


class DescriptionGuidanceTests(unittest.TestCase):
    def test_entrypoints_reach_canonical_guide(self):
        for path in ENTRYPOINTS:
            with self.subTest(path=path):
                self.assertIn(GUIDE, local_targets(path, path.read_text()))

    def test_local_document_links_exist(self):
        for path in (*ENTRYPOINTS, GUIDE, FIXTURES / "README.md"):
            for target in local_targets(path, path.read_text()):
                with self.subTest(path=path, target=target):
                    self.assertTrue(target.is_file(), str(target))

    def test_broken_link_mutation_is_detected(self):
        targets = local_targets(TEMPLATE, "[guide](../docs/DOES-NOT-EXIST.md)")
        self.assertEqual(len(targets), 1)
        self.assertFalse(targets[0].exists())

    def test_guide_exposes_nine_ordered_rules(self):
        numbers = re.findall(r"^## (\d+)\. ", GUIDE.read_text(), re.MULTILINE)
        self.assertEqual(numbers, [str(number) for number in range(1, 10)])

    def test_template_retains_sections_checkboxes_and_context_slots(self):
        text = TEMPLATE.read_text()
        self.assertEqual(headings(text), ["Summary", "Validation", "Sync Impact", "AI assistance"])
        self.assertEqual(checkboxes(text), list(CHECKBOXES))
        self.assertEqual(len(re.findall(r"^- \[ \] ", text, re.MULTILINE)), 5)
        for field in ("Context", "Plan", "Rollback", "Security"):
            self.assertRegex(text, rf"(?m)^- {field}: \S")
        self.assertTrue(text.rstrip().endswith(
            "\n\nCo-authored-by: AI assistant (harness unknown)"))

    def test_authored_examples(self):
        for name, repository, harness in (
            ("routine", True, "OpenCode"),
            ("partial", True, "OpenCode"),
            ("fallback", False, "AI assistant (harness unknown)"),
        ):
            with self.subTest(name=name):
                text = (FIXTURES / f"{name}.md").read_text()
                self.assertEqual(example_errors(text, repository=repository, harness=harness), set())

    def test_structural_mutations_are_detected(self):
        text = (FIXTURES / "routine.md").read_text()
        mutations = (
            (text.replace("## Sync Impact", "## Notes"), "sections"),
            (text.replace("- [x] `make check` passes\n", ""), "checkboxes"),
            (text.replace("- Rollback:", "- Reversal:"), "fields"),
            (text + "\nCo-authored-by: OpenCode\n", "credit"),
            (text.replace("Co-authored-by: OpenCode", "Co-authored-by: model-name"), "credit"),
            (text + "\nText after attribution.\n", "ending"),
            (text.replace("\n\nCo-authored-by:", "\nCo-authored-by:"), "ending"),
            (text.replace("## Summary\n", "## Summary\n" + "filler " * 201), "length"),
            (text.replace("- Plan:", "<required plan>\n- Plan:"), "placeholder"),
        )
        for changed, error in mutations:
            with self.subTest(error=error):
                self.assertIn(error, example_errors(changed, repository=True, harness="OpenCode"))

    def test_preserved_editor_credit_and_unknown_fallback(self):
        partial = (FIXTURES / "partial.md").read_text()
        self.assertEqual(partial.count("Credit: existing editor (retained synthetic credit)."), 1)
        fallback = (FIXTURES / "fallback.md").read_text()
        changed = fallback.replace("AI assistant (harness unknown)", "OpenCode")
        self.assertIn("credit", example_errors(
            changed, repository=False, harness="AI assistant (harness unknown)"))


if __name__ == "__main__":
    unittest.main()
