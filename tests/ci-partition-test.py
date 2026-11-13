"""Offline CI partition coverage and actual inline aggregate-gate fixtures.

Run only in an independently isolated workspace sandbox. Bounded workflow
extraction is not a YAML interpreter; hosted runtimes still need measurement.
Uses only the standard library, bash and make; no network or GitHub writes.
"""

import itertools
import os
import re
import subprocess
import sys
import textwrap
import unittest
from collections import Counter
from pathlib import Path

if not sys.flags.isolated or not sys.dont_write_bytecode:
    raise SystemExit("Run this sandbox test with python3 -I -B")

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
FOREGROUND = [
    "python3 -I -B .agents/skills/workspace-orchestrator/tests/foreground-handoff-test.py",
    "python3 -I -B .agents/skills/workspace-orchestrator/tests/foreground-delivery-test.py",
]
# Pre-partition test recipe, including shell syntax and shell fixture commands.
# Keep this explicit: deriving expected coverage from the current Makefile would
# let an accidentally deleted test silently disappear from both sides.
ORIGINAL_TESTS = """\
python3 -I -B tests/ci-tool-installer-test.py
python3 -I -B tests/cooperative-session-binding-test.py
python3 -I -B tests/release-config-test.py
python3 -I -B tests/shared-authority-admission-test.py
python3 -I -B tests/workspace-cleanup-test.py
python3 -I -B .agents/skills/federal-authority-research/tests/validate-test.py
python3 -I -B tests/pr-review-eligibility-test.py
python3 -I -B tests/pr-description-guidance-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/runtime-observation-test.py
python3 -I -B tests/scoped-autonomy-contract-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/review-reservation-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/review-handoff-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/foreground-handoff-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/foreground-delivery-test.py
sh -n scripts/review-workspace-preflight.sh
python3 -I -B tests/review-workspace-preflight-test.py
python3 -I -B tests/qualify-opencode-profile-test.py
python3 -I -B tests/qualify-opencode-tools-test.py
python3 -I -B tests/delivery-batch-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/candidate-binding-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/monitor-journal-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/qualification-driver-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/repair-proposal-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/repair-apply-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/execution-plan-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/execution-observe-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/review-packet-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/review-evidence-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/review-run-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/review-collect-test.py
python3 -I -B .agents/skills/workspace-orchestrator/tests/review-accept-test.py
PYTHONDONTWRITEBYTECODE=1 bash .agents/skills/cross-repo-epic/tests/portfolio-status-test.sh
PYTHONDONTWRITEBYTECODE=1 bash .agents/skills/cross-repo-epic/tests/epic-status-test.sh
PYTHONDONTWRITEBYTECODE=1 bash .agents/skills/workspace-orchestrator/tests/orchestrator-state-test.sh
PYTHONDONTWRITEBYTECODE=1 bash .agents/skills/workspace-orchestrator/tests/orchestrator-monitor-test.sh
PYTHONDONTWRITEBYTECODE=1 bash .agents/skills/workspace-orchestrator/tests/orchestrator-demo.sh
PYTHONDONTWRITEBYTECODE=1 bash .agents/skills/workspace-orchestrator/tests/orchestrator-production-worktree-test.sh
bash tests/import-sync-test.sh
bash tests/opencode-compat-test.sh
bash tests/forbidden-paths-test.sh
bash tests/strict-version-test.sh
bash tests/evaluate-workflow-test.sh
bash tests/cohort-reflection-test.sh
python3 -I -B tests/append-cohort-event-test.py
python3 -I -B tests/intake-inventory-test.py
python3 -I -B tests/merge-evidence-test.py
python3 -I -B tests/observe-merge-test.py
python3 -I -B tests/plan-exception-test.py
python3 -I -B tests/evaluate-exception-replay-test.py
python3 -I -B tests/check-intake-sources-test.py
python3 -I -B tests/observe-github-issues-test.py
python3 -I -B tests/observe-review-requests-test.py
python3 -I -B tests/adapt-issues-capture-test.py
python3 -I -B tests/check-native-ownership-test.py
python3 -I -B tests/native-claim-test.py
python3 -I -B tests/prepare-task-claim-test.py
python3 -I -B tests/prepare-approved-claim-test.py
python3 -I -B tests/journal-claim-intent-test.py
python3 -I -B tests/journal-approved-claim-test.py
python3 -I -B tests/publish-github-assignment-test.py
python3 -I -B tests/assignment-dispatch-test.py
python3 -I -B tests/standing-grant-test.py
python3 -I -B tests/standing-grant-executor-test.py
python3 -I -B tests/observe-github-claims-test.py
python3 -I -B tests/observe-claim-intent-test.py
python3 -I -B tests/record-claim-observation-test.py
bash tests/operating-surface-test.sh
""".splitlines()
PARTITION_TEST = "python3 -I -B tests/ci-partition-test.py"
SYNTAX_TEST = "python3 -I -B tests/syntax-first-test.py"
CORE_QUALITY_TEST = "python3 -I -B tests/core-quality-check-test.py"
PREFLIGHT_SYNTAX = "sh -n scripts/review-workspace-preflight.sh"


def job(name):
    """Extract only this workflow's fixed two-space job-header shape."""
    match = re.search(rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [\w-]+:\n|\Z)", WORKFLOW)
    if match is None:
        raise AssertionError(f"missing job: {name}")
    return match.group(1)


class CIPartitionTests(unittest.TestCase):
    def dry_run(self, target):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("GIT_", "MAKE")) and key != "MFLAGS"}
        result = subprocess.run(
            ["make", "--no-print-directory", "-n", target], cwd=ROOT, env=env,
            check=True, capture_output=True, text=True, timeout=30,
        )
        return result.stdout.splitlines()

    def test_original_test_commands_partition_exactly_once(self):
        self.assertIn("\n.NOTPARALLEL: test\n", MAKEFILE)
        syntax = self.dry_run("check-syntax")
        foreground = self.dry_run("test-foreground")
        rest = self.dry_run("test-rest")
        self.assertEqual(foreground, syntax + FOREGROUND)
        expected_rest = [line for line in ORIGINAL_TESTS
                         if line not in FOREGROUND + [PREFLIGHT_SYNTAX]]
        expected_rest.insert(1, PARTITION_TEST)
        expected_rest.insert(2, SYNTAX_TEST)
        expected_rest.insert(3, CORE_QUALITY_TEST)
        self.assertEqual(rest, syntax + expected_rest)
        self.assertEqual(Counter(FOREGROUND + expected_rest + [PREFLIGHT_SYNTAX]),
                         Counter(ORIGINAL_TESTS + [PARTITION_TEST, SYNTAX_TEST, CORE_QUALITY_TEST]))
        self.assertEqual(self.dry_run("test"), syntax + FOREGROUND + expected_rest)

    def test_syntax_inventory_and_partition_prerequisites(self):
        syntax = self.dry_run("check-syntax")
        self.assertEqual(len(syntax), 4)
        self.assertEqual(syntax[0], PREFLIGHT_SYNTAX)
        for command, marker in zip(syntax[1:], (
            'bash -n "$file"', "python syntax: PASS", "json syntax: PASS",
        ), strict=True):
            self.assertIn(marker, command)
            self.assertIn("--cached", command)
            self.assertIn("--others", command)
            self.assertIn("--exclude-standard", command)
        self.assertIn("'.agents/skills/*/tests/fixtures/*/gh'", syntax[1])
        self.assertIn("compile(ast.parse(", syntax[2])
        for target in ("test-foreground", "test-rest"):
            self.assertIn(f"\n{target}: check-syntax\n", MAKEFILE)

    def test_check_composition_keeps_static_checks_after_tests(self):
        static = self.dry_run("check-static")
        self.assertEqual(len(static), 5)
        for command, marker in zip(static, (
            "CANONICAL-SHA256SUMS", "shellcheck: PASS", "scripts/forbidden-paths.sh --check",
            "PRIVATE KEY", "repository checks: PASS",
        ), strict=True):
            self.assertIn(marker, command)
        for check, tests in (("check", "test"), ("check-rest", "test-rest")):
            with self.subTest(target=check):
                # Recursive make enforces ordering even under make -j. A dry run
                # prints that invocation and expands only its dry-run recipes.
                expected = self.dry_run(tests) + ["make --no-print-directory check-static"] + static
                self.assertEqual(self.dry_run(check), expected)
                self.assertIn(f"\n{check}: {tests}\n\t@$(MAKE) --no-print-directory check-static\n", MAKEFILE)
        strict = (ROOT / "scripts/strict-check.sh").read_text(encoding="utf-8")
        self.assertIn("\nmake check\nbash scripts/core-quality-check.sh\n", strict)

    def test_workflow_jobs_and_security_contract(self):
        self.assertEqual(WORKFLOW.split("jobs:\n")[0], textwrap.dedent("""\
            name: CI

            on:
              pull_request:
              push:
                branches:
                  - main

            permissions:
              contents: read

            concurrency:
              group: ci-${{ github.workflow }}-${{ github.ref }}
              cancel-in-progress: true

            """))
        self.assertEqual(re.findall(r"(?m)^  ([\w-]+):$", WORKFLOW.split("jobs:\n")[1]),
                         ["foreground", "check", "repository-checks"])
        self.assertEqual(WORKFLOW.count("permissions:"), 1)
        self.assertNotIn("continue-on-error:", WORKFLOW)
        for name, target in (("foreground", "test-foreground"), ("check", "check-rest")):
            body = job(name)
            self.assertIn("    timeout-minutes: 15\n", body)
            self.assertIn("    runs-on: ubuntu-latest\n", body)
            self.assertNotIn("    needs:", body)
            self.assertNotIn("if:", body)
            self.assertEqual(re.findall(r"uses: (\S+)", body), [
                "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                "actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0",
            ])
            self.assertIn("          persist-credentials: false\n", body)
            self.assertIn("          python-version: 3.12.15\n", body)
            self.assertIn(f"        run: make {target}\n", body)
        rest = job("check")
        for command in ("tools/install-ci-tools.sh", "run: make check-rest",
                        "run: scripts/core-quality-check.sh", "sha256sum --check --strict",
                        '"$RUNNER_TEMP/gitleaks" dir . --config .gitleaks.toml --redact --no-banner'):
            self.assertIn(command, rest)
        self.assertLess(rest.index("run: make check-rest"), rest.index("run: scripts/core-quality-check.sh"))
        self.assertLess(rest.index("run: scripts/core-quality-check.sh"), rest.index('"$RUNNER_TEMP/gitleaks" dir'))

    def test_actual_aggregate_gate_all_result_pairs(self):
        aggregate = job("repository-checks")
        prefix, body = aggregate.split("        run: |\n")
        self.assertEqual(prefix, textwrap.indent(textwrap.dedent("""\
            name: Repository checks
            needs: [foreground, check]
            if: ${{ always() }}
            runs-on: ubuntu-latest
            timeout-minutes: 1
            steps:
              - name: Require both check jobs to succeed
                env:
                  FOREGROUND_RESULT: ${{ needs.foreground.result }}
                  CHECK_RESULT: ${{ needs.check.result }}
                shell: bash
            """), "    "))
        self.assertEqual(WORKFLOW.count("    name: Repository checks\n"), 1)
        self.assertTrue(all(not line.strip() or line.startswith("          ") for line in body.splitlines()))
        self.assertNotIn("${{", body)
        gate = textwrap.dedent(body)
        results = ("success", "failure", "skipped", "cancelled", "", None, "unknown", "SUCCESS")
        for foreground, rest in itertools.product(results, repeat=2):
            with self.subTest(foreground=foreground, rest=rest):
                env = {"PATH": os.environ.get("PATH", os.defpath)}
                if foreground is not None:
                    env["FOREGROUND_RESULT"] = foreground
                if rest is not None:
                    env["CHECK_RESULT"] = rest
                result = subprocess.run(["bash", "--noprofile", "--norc", "-c", gate],
                                        env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0 if foreground == rest == "success" else 1)


if __name__ == "__main__":
    unittest.main()
