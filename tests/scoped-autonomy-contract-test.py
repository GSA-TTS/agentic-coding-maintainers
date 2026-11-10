#!/usr/bin/env python3
"""Documentation contracts only: no grant resolver, executor or approval simulation."""

import copy
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docs/SCOPED-AUTONOMY.md"
FIXTURES = ROOT / "tests/fixtures/scoped-autonomy"
SKILL = ROOT / ".agents/skills/workspace-orchestrator"
COMMAND = SKILL / "examples/commands/orchestrate-start.md"
GROUPS = {"identity", "target", "objective", "scope", "lifetime", "budgets", "evidence"}
CLASSES = {
    "SCOPED": {"read-admit", "issue-create", "issue-edit", "labels-add",
               "assignees-add", "status-update", "branch-push", "isolated-check",
               "pr-publish", "review-publish"},
    "HUMAN": {"merge", "auto-merge", "queue", "policy-install", "human-overwrite",
              "issue-lifecycle", "assignees-remove", "delete", "pr-close", "release-deploy"},
    "REFUSE": {"force-protected-foreign", "self-approve-bypass"},
}


def normalized(text):
    return " ".join(text.split())


def sections(text):
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def matrix(text):
    """Parse documentation rows, never evaluate an action request."""
    return re.findall(r"^\| ([a-z-]+) \| (SCOPED|HUMAN|REFUSE) \| (.+) \|$",
                      sections(text)["Canonical action matrix"], re.MULTILINE)


def scenario_reference_errors(text, scenarios):
    """Only validate authored cases' action/section/quotation references."""
    document = sections(text)
    actions = {row[0] for row in matrix(text)}
    return {case["id"] for case in scenarios
            if case["action"] not in actions
            or normalized(case["rule"]) not in normalized(document.get(case["section"], ""))}


class ScopedAutonomyContractTests(unittest.TestCase):
    def test_action_matrix_is_complete_unique_and_classified(self):
        rows = matrix(POLICY.read_text())
        self.assertEqual(len(rows), sum(map(len, CLASSES.values())))
        for classification, actions in CLASSES.items():
            self.assertEqual({action for action, kind, _ in rows if kind == classification}, actions)
        self.assertEqual(len({row[0] for row in rows}), len(rows))

    def test_matrix_class_and_deletion_mutations_are_visible(self):
        text = POLICY.read_text()
        expected = {(action, kind) for kind, actions in CLASSES.items() for action in actions}
        for changed in (text.replace("| merge | HUMAN |", "| merge | SCOPED |"),
                        re.sub(r"^\| issue-create \|.*\n", "", text, flags=re.MULTILINE)):
            self.assertNotEqual({(action, kind) for action, kind, _ in matrix(changed)}, expected)

    def test_scenario_coverage_and_rule_references(self):
        cases = json.loads((FIXTURES / "scenarios.json").read_text())
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        self.assertEqual({case["id"] for case in cases}, {
            "inactive-policy", "bootstrap", "covered-routine", "wrong-target-field",
            "budget-restart", "expired-revoked", "human-drift", "unknown-create",
            "green-no-human", "human-exact-head", "stale-head", "fabricated-approval",
            "auto-enable", "queue-entry", "indirect-closure", "pr-close", "unknown-154",
            "paused-158", "host-boundary", "interrupted-dispatch",
        })
        for case in cases:
            self.assertEqual(set(case), {"id", "action", "given", "expect", "section", "rule"})
            self.assertTrue(all(isinstance(value, str) and value for value in case.values()))
        self.assertEqual(scenario_reference_errors(POLICY.read_text(), cases), set())
        for field, value in (("action", "unlisted-action"), ("section", "Absent section"),
                             ("rule", "Invented rule with no source")):
            changed = copy.deepcopy(cases)
            changed[0][field] = value
            self.assertIn(cases[0]["id"], scenario_reference_errors(POLICY.read_text(), changed))

    def test_grant_example_covers_groups_without_activation(self):
        text = sections(POLICY.read_text())["Structured grant contract"]
        documented = set(re.findall(r"^\| ([a-z]+) \|", text, re.MULTILINE))
        self.assertEqual(documented, GROUPS)
        example = json.loads((FIXTURES / "grant-example.json").read_text())
        self.assertEqual(set(example), GROUPS | {"fixture_kind"})
        self.assertEqual(example["fixture_kind"], "synthetic-inactive-contract-example")
        self.assertIsNone(example["lifetime"]["activated_at"])
        self.assertEqual(example["lifetime"]["revocation_state"], "INACTIVE")
        self.assertEqual(example["objective"]["tracker"], "none")
        self.assertLessEqual(set(example["scope"]["actions"]), CLASSES["SCOPED"])
        for group in GROUPS:
            changed = copy.deepcopy(example)
            del changed[group]
            self.assertNotEqual(set(changed), GROUPS | {"fixture_kind"})

    def test_local_entrypoints_link_single_policy(self):
        for relative in ("AGENTS.md", "CONTRIBUTING.md", "docs/HUMAN-REVIEWED-DELIVERY.md",
                         "docs/CLAIM-PUBLISHER-PROTOCOL.md", "docs/PR-DESCRIPTIONS.md",
                         "docs/REPOSITORY-SETUP.md"):
            path = ROOT / relative
            text = path.read_text()
            targets = {(path.parent / link.split("#", 1)[0]).resolve()
                       for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
                       if "://" not in link and not link.startswith("#")}
            with self.subTest(path=relative):
                self.assertIn(POLICY, targets)
                self.assertTrue(all(target.is_file() for target in targets))
                self.assertNotIn("| Action ID | Class |", text)

    def test_packaged_guidance_is_consumer_neutral_and_command_matches(self):
        for path in (SKILL / "docs/MAINTAINER-SERVICE.md",
                     SKILL / "docs/OPERATOR-GUIDE.md", COMMAND):
            text = path.read_text()
            with self.subTest(path=path):
                self.assertIn("consumer", text.lower())
                for forbidden in ("1422648445", "#154", "#158", "| Action ID | Class |",
                                  "](SCOPED-AUTONOMY.md)"):
                    self.assertNotIn(forbidden, text)
                for binding in ("approver identity", "repository/PR identity", "policy revision"):
                    self.assertIn(binding, normalized(text))
        self.assertEqual(COMMAND.read_bytes(),
                         (ROOT / ".opencode/commands/orchestrate-start.md").read_bytes())
        self.assertIn("tests/scoped-autonomy-contract-test.py", (ROOT / "Makefile").read_text())


if __name__ == "__main__":
    unittest.main()
