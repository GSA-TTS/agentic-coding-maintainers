#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
V1="${OPENCODE_V1:-}"
V2="${OPENCODE_V2:-}"

python3 - "$ROOT" <<'PY'
from pathlib import Path
import re, sys
root = Path(sys.argv[1])
for skill in ("cross-repo-epic", "workspace-orchestrator"):
    path = root / ".agents" / "skills" / skill / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    assert text.count("---\n") >= 2
    frontmatter = text.split("---\n", 2)[1]
    assert "\t" not in frontmatter
    top, metadata, section = {}, {}, None
    for line in frontmatter.splitlines():
        if not line.strip(): continue
        if line.startswith("  "):
            assert section == "metadata" and ":" in line
            key, value = line.strip().split(":", 1)
            assert key and value.strip() and key not in metadata
            metadata[key] = value.strip().strip('"')
            continue
        assert not line.startswith(" ") and ":" in line
        key, value = line.split(":", 1)
        assert key and key not in top
        top[key], section = value.strip(), key
    assert top["name"] == skill
    assert top["description"]
    assert re.search(r"OpenCode 1\.19\+ and 2\.0\+", top["compatibility"])
    assert metadata and all(isinstance(value, str) and value for value in metadata.values())
print("skill frontmatter: PASS")

# Static packaging and authored-example checks only, not LLM compliance.
# Installed profile byte parity is covered by operating-surface-test.sh.
skill = root / ".agents/skills/workspace-orchestrator"
guide = skill / "docs/REVIEW-OUTPUT.md"
assert guide.is_file(), "review output guidance must ship with the skill"
for source in [
    skill / "profiles/opencode-v1" / f"{name}.md"
    for name in ("qa-reviewer", "security-reviewer", "pr-review-coordinator")
]:
    paths = re.findall(r"repository-root `([^`]+)`", source.read_text(encoding="utf-8"))
    assert any((root / path).resolve() == guide.resolve() for path in paths), source.name
links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", (skill / "docs/OPERATOR-GUIDE.md").read_text())
assert any((skill / "docs" / link).resolve() == guide.resolve() for link in links)

examples = re.findall(r"```text\n(.*?)\n```", guide.read_text(encoding="utf-8"), re.S)
assert len(examples) == 3, "expected defect, no-findings, and unverified examples"
defect, clean, unverified = examples
for example in examples:
    assert re.search(r"AI-assisted .*head [0-9a-f]{40}\.", example), "missing head/attribution"
assert re.match(r"Should-fix — [^\s:]+:[1-9][0-9]* — ", defect), "missing finding location"
assert "UNVERIFIED" in defect, "defect example must retain material uncertainty"
assert not re.search(r"^(Blocker|Should-fix|Nit)\b", clean, re.M), "clean example has a finding"
assert clean.splitlines()[0] == "No actionable findings."
assert unverified.startswith("UNVERIFIED — ")
assert not re.search(r"\bclean\b|no actionable findings", unverified, re.I), (
    "unverified example must not claim a clean review"
)
print("review output packaging and synthetic examples: PASS (static; no model compliance claim)")
PY

if [[ -z "$V1" || -z "$V2" ]]; then
  echo "OpenCode runtime probes: SKIP (set OPENCODE_V1 and OPENCODE_V2)"
  exit 0
fi
[[ -x "$V1" && -x "$V2" ]] || { echo "OpenCode probe paths must be executable" >&2; exit 2; }

fixture="$(mktemp -d "${TMPDIR:-/tmp}/opencode-compat.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT HUP INT TERM
mkdir -p "$fixture/repo/.opencode/agents" "$fixture/repo/.agents/skills"
cp "$ROOT"/.agents/skills/workspace-orchestrator/profiles/opencode-v1/*.md "$fixture/repo/.opencode/agents/"
cp -R "$ROOT/.agents/skills/cross-repo-epic" "$fixture/repo/.agents/skills/"
cp -R "$ROOT/.agents/skills/workspace-orchestrator" "$fixture/repo/.agents/skills/"
git -C "$fixture/repo" init -q

v1_version="$($V1 --version | sed 's/^opencode v//')"
v2_version="$($V2 --version | sed 's/^opencode v//')"
python3 - "$v1_version" "$v2_version" <<'PY'
import sys
def parts(value): return tuple(int(x) for x in value.split(".")[:3])
v1, v2 = map(parts, sys.argv[1:])
assert (1, 19, 0) <= v1 < (2, 0, 0), v1
assert v2 >= (2, 0, 0), v2
PY

v1root="$fixture/v1"
mkdir -p "$v1root"/{home,config,data,cache,state,tmp}
for agent in pr-review-coordinator backlog-project-monitor implementation-worker qa-reviewer security-reviewer orchestration-qa; do
  (
    cd "$fixture/repo"
    env -i HOME="$v1root/home" XDG_CONFIG_HOME="$v1root/config" XDG_DATA_HOME="$v1root/data" \
      XDG_CACHE_HOME="$v1root/cache" XDG_STATE_HOME="$v1root/state" TMPDIR="$v1root/tmp" \
      PATH="/usr/bin:/bin:/usr/sbin:/sbin" USER="${USER:-tester}" SHELL=/bin/sh \
      "$V1" debug agent "$agent" >/dev/null
  )
done
echo "OpenCode v1 agent profiles: PASS"
(
  cd "$fixture/repo"
  env -i HOME="$v1root/home" XDG_CONFIG_HOME="$v1root/config" XDG_DATA_HOME="$v1root/data" \
    XDG_CACHE_HOME="$v1root/cache" XDG_STATE_HOME="$v1root/state" TMPDIR="$v1root/tmp" \
    PATH="/usr/bin:/bin:/usr/sbin:/sbin" USER="${USER:-tester}" SHELL=/bin/sh \
    "$V1" debug skill
) >"$fixture/v1-skills.json"
grep -q 'cross-repo-epic' "$fixture/v1-skills.json"
grep -q 'workspace-orchestrator' "$fixture/v1-skills.json"
echo "OpenCode v1 skill discovery: PASS"

v2root="$fixture/v2"
mkdir -p "$v2root"/{home,config,data,cache,state,tmp}
for agent in pr-review-coordinator backlog-project-monitor implementation-worker qa-reviewer security-reviewer orchestration-qa; do
  set +e
  (
    cd "$fixture/repo"
    env -i HOME="$v2root/home" XDG_CONFIG_HOME="$v2root/config" XDG_DATA_HOME="$v2root/data" \
      XDG_CACHE_HOME="$v2root/cache" XDG_STATE_HOME="$v2root/state" TMPDIR="$v2root/tmp" \
      PATH="/usr/bin:/bin:/usr/sbin:/sbin" USER="${USER:-tester}" SHELL=/bin/sh \
      "$V2" run --standalone --agent "$agent" --model invalid-provider/invalid-model \
      --format json 'No model call should succeed.'
  ) >"$fixture/v2-$agent.out" 2>"$fixture/v2-$agent.err"
  known_rc=$?
  set -e
  [[ "$known_rc" -ne 0 ]]
  grep -q 'provider.no-route' "$fixture/v2-$agent.out"
  if grep -q 'Agent not found' "$fixture/v2-$agent.out"; then
    echo "known OpenCode v2 agent was not discovered: $agent" >&2
    exit 1
  fi
done
set +e
(
  cd "$fixture/repo"
  env -i HOME="$v2root/home" XDG_CONFIG_HOME="$v2root/config" XDG_DATA_HOME="$v2root/data" \
    XDG_CACHE_HOME="$v2root/cache" XDG_STATE_HOME="$v2root/state" TMPDIR="$v2root/tmp" \
    PATH="/usr/bin:/bin:/usr/sbin:/sbin" USER="${USER:-tester}" SHELL=/bin/sh \
    "$V2" run --standalone --agent definitely-not-an-agent --model invalid-provider/invalid-model \
    --format json 'No model call should succeed.'
) >"$fixture/v2-missing.out" 2>"$fixture/v2-missing.err"
missing_rc=$?
set -e

[[ "$missing_rc" -ne 0 ]]
grep -q 'Agent not found' "$fixture/v2-missing.out"
grep -q '/.agents/skills' "$v2root/data/opencode/log/opencode.log"
echo "OpenCode v2 skill path watch and all agent profiles: PASS (skill enumeration unavailable)"
