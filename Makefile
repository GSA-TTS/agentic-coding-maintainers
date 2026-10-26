SHELL := /bin/bash

.PHONY: test check strict-check

test:
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
	bash tests/operating-surface-test.sh

check: test
	@set -euo pipefail; tmp="$$(mktemp)"; (cd .agents/skills/workspace-orchestrator && find . -type d -name __pycache__ -prune -o -type f ! -name CANONICAL-SHA256SUMS ! -name '*.pyc' ! -name '*.pyo' -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > "$$tmp"; diff -u .agents/skills/workspace-orchestrator/CANONICAL-SHA256SUMS "$$tmp"; rm -f "$$tmp"
	@set -euo pipefail; while IFS= read -r file; do bash -n "$$file"; done < <(git ls-files --cached --others --exclude-standard -- '*.sh' '.agents/skills/*/tests/fixtures/*/gh')
	@PYTHONDONTWRITEBYTECODE=1 python3 -c 'import ast, pathlib, subprocess; files = [pathlib.Path(p) for p in subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.py"], text=True).splitlines()]; [compile(ast.parse(p.read_text(encoding="utf-8"), filename=str(p)), str(p), "exec") for p in files]; print(f"python syntax: PASS ({len(files)} files)")'
	@PYTHONDONTWRITEBYTECODE=1 python3 -c 'import json, pathlib, subprocess; files = [pathlib.Path(p) for p in subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.json"], text=True).splitlines()]; [json.loads(p.read_text(encoding="utf-8")) for p in files]; print(f"json syntax: PASS ({len(files)} files)")'
	@if command -v shellcheck >/dev/null 2>&1; then git ls-files -z --cached --others --exclude-standard -- '*.sh' '.agents/skills/*/tests/fixtures/*/gh' | xargs -0 shellcheck && printf '%s\n' 'shellcheck: PASS'; else printf '%s\n' 'shellcheck: SKIP (not installed)'; fi
	@bash scripts/forbidden-paths.sh --check
	@set -euo pipefail; pattern='-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}'; while IFS= read -r file; do if grep -Iq . "$$file" && grep -En -- "$$pattern" "$$file"; then exit 1; fi; done < <(git ls-files --cached --others --exclude-standard)
	@printf '%s\n' 'repository checks: PASS'

strict-check: ## Run all pinned local quality/security gates
	@bash scripts/strict-check.sh

core-quality-check: ## Run the quality subset also enforced by hosted CI
	@bash scripts/core-quality-check.sh
