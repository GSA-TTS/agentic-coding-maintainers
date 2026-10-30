#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
profiles="$ROOT/.agents/skills/workspace-orchestrator/profiles/opencode-v1"
agents="$ROOT/.opencode/agents"
pass=0
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

# A missing copy or a changed permission in either direction must not silently
# drift from the canonical role pack. Refuse an empty directory as unmeasured.
count=0
for source in "$profiles"/*.md; do
  [[ -f "$source" ]] || fail 'no canonical agent profiles found'
  target="$agents/${source##*/}"
  [[ -f "$target" && ! -L "$target" ]] || fail "missing or symlinked installed profile: ${source##*/}"
  cmp -s "$source" "$target" || fail "installed profile differs: ${source##*/}"
  count=$((count+1))
done
[[ "$count" -gt 0 ]] || fail 'zero profiles compared'
for target in "$agents"/*.md; do
  [[ -f "$target" ]] || fail 'no installed agent profiles found'
  [[ -f "$profiles/${target##*/}" ]] || fail "unreviewed installed agent: ${target##*/}"
done
pass=$((pass+1))

# Canonical shipped command examples must match installed bytes. These tests
# change only isolated scratch fixtures, never the real command copies.
python3 -I -B "$ROOT/scripts/check-operating-surface.py" "$ROOT" || fail 'command parity failed'
python3 -I -B - "$ROOT" <<'PY' || fail 'command parity refusal regressions'
import importlib.util
import pathlib
import tempfile
import sys
import subprocess

repo = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("surface", repo / "scripts/check-operating-surface.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory).resolve()
    canonical = root / ".agents/skills/workspace-orchestrator/examples/commands"
    installed = root / ".opencode/commands"
    canonical.mkdir(parents=True)
    installed.mkdir(parents=True)
    source = canonical / "orchestrate-start.md"
    target = installed / source.name
    source.write_bytes(b"canonical command\n")
    target.write_bytes(source.read_bytes())
    assert module.check(root) == 1
    (installed / "project-only.md").write_text("consumer extension\n")
    assert module.check(root) == 1
    def refused():
        try:
            module.check(root)
        except (ValueError, OSError):
            return
        raise AssertionError("unmeasured command parity passed")
    target.write_bytes(b"drifted\n")
    refused()
    result = subprocess.run([sys.executable, "-I", "-B", str(repo / "scripts/check-operating-surface.py"), str(root)], capture_output=True, text=True)
    assert result.returncode == 1 and "FINDINGS" in result.stderr and "orchestrate-start.md" in result.stderr
    target.unlink()
    refused()
    result = subprocess.run([sys.executable, "-I", "-B", str(repo / "scripts/check-operating-surface.py"), str(root)], capture_output=True, text=True)
    assert result.returncode == 3 and "UNVERIFIED" in result.stderr
    target.symlink_to(source)
    refused()
    target.unlink()
    target.write_bytes(b"canonical command\n")
    source.write_bytes(b"")
    refused()
    source.unlink()
    refused()
    source.symlink_to(target)
    refused()
print("command parity refusal cases: PASS")
PY
pass=$((pass+1))

# Run a real dispatcher without network; verify it operates in this repository.
"$ROOT/bin/orchestrator-state.sh" reconcile >/dev/null || fail 'state reconcile failed'
pass=$((pass+1))

# Never fall back to the example. The absent-config state must say UNVERIFIED.
set +e
message="$(ORCHESTRATOR_CONFIG="$ROOT/.nonexistent-monitor-config.json" "$ROOT/bin/orchestrator-monitor.sh" --task-id probe 2>&1)"
rc=$?
set -e
[[ "$rc" -eq 3 && "$message" == *UNVERIFIED* ]] || fail "missing config: rc=$rc, output=$message"
pass=$((pass+1))

# The tracked example must be parseable and declare a bounded portfolio.
python3 - "$ROOT/orchestrator.example.json" <<'PY' || fail 'invalid example config'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
assert data["schema_version"] == 1
assert 1 <= len(data["repositories"]) <= 50
assert len(set(data["repositories"])) == len(data["repositories"])
assert data["project"]["owner_type"] in ("organization", "user")
PY
pass=$((pass+1))
printf 'operating surface: PASS (%s measured checks, %s profiles)\n' "$pass" "$count"
