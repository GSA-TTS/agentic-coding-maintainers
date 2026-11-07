---
title: "Compare minimal local operation with the Paseo experience"
description: "Research equivalent operating behavior across minimal and richer bindings."
status: draft
tier: 2
labels: ["wayfinder:research"]
---

# Compare minimal local operation with the Paseo experience

Type: research
Status: resolved
Assignee: runtime-bindings-researcher (AI)
Blocked by: none
Parent: [Portable team-as-code: scale down, scale up](../map.md)

## Question

What is the smallest practical configuration that supports the team-operating
skills, and how can Paseo supply a richer experience under the same contracts?

Use OpenRig primary sources to identify essential team behaviors. Compare local
Markdown/Git tasks and knowledge, CLI-driven agent execution, and cron-compatible
or foreground-loop wakes with Paseo agents, profiles, messaging, scheduling, and
a plugin team panel. Verify the applicable kit pin and label version differences.

Specify observable outcomes for overlapping ticks, daemon/loop exit, missed wakes,
busy recipients, occupant replacement, and uncertain notification delivery.
Separate timer execution from reassessment by an agent. Determine the minimum
runtime required to launch or resume an agent without Paseo.

Investigate ongoing memory as well as handover: OpenRig's authored knowledge,
what Paseo actually retains, and which storage/retrieval functions the local
Markdown default must supply. Feed facts into the separate memory decision.

List what can genuinely stay identical in the skills and what needs declared
capabilities. UI enhancements must consume the same authoritative state and
operations. Record unsupported guarantees and necessary human actions explicitly.

## Comments

2026-11-06: Created by an AI assistant from the user-approved research scope.
No scheduler or model run is authorized by this research ticket.

2026-11-06: The user separately authorized research-agent model runs in fresh
Paseo workspaces. Demonstration model runs and scheduler activation remain out
of scope. See the [research admission record](../research/research-admission.md).
Researcher owns `research/minimal-and-paseo-bindings.md` in its assigned
workspace; the primary Wayfinder alone integrates findings and resolves this ticket.

## Answer

2026-11-06, AI Wayfinder: the [runtime and memory report](../research/minimal-and-paseo-bindings.md)
establishes source-backed differences and candidate interfaces. It does not prove
an implemented minimal binding or resolve human contract decisions.

- OpenRig separates stable seats, occupant generations, and execution observations.
  Its authored knowledge is Markdown; live queue state is SQLite-canonical.
- The configured Patterns kit pins Paseo 0.15.0; the researcher observed 0.12.0
  installed. Durable finish subscriptions differ by version. Busy heartbeat
  refusal and missed-tick behavior need an explicit portable policy.
- CLI launch/resume and file retrieval support a small team binding, but OpenCode
  still uses its own server/persistence. A foreground loop avoids requiring cron;
  it does not supply durable recurrence or replacement safety automatically.
- Authored knowledge needs stable addresses, sources, correction/supersession,
  explicit retrieval and delivery. Provider transcript retention does not supply
  those semantics. Writing a shared file does not prove an occupant read it.
- Paseo profiles are launch settings, and a team panel can consume team operations
  while Paseo owns runtime facts. This does not require competing task authorities.

Primary read the full report and checked `opencode run --help`, correcting claims
about server-free execution, unavailable steering, inevitable loss of atomicity,
exclusive file-based instructions, and transcript portability. Default Markdown
authority and a panel consuming team operations were already agreed, so the
report's O1/O7 are marked settled direction. Other choices feed the existing
contract, memory and demonstration tickets. The worker's original is preserved.
Detailed product behavior remains source-inspected, not live-qualified.
