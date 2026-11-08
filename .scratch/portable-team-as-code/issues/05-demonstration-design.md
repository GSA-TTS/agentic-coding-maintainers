---
title: "Design the scale-down and scale-up demonstration"
description: "Agree on a concrete demonstration and evidence for portable skills."
status: draft
tier: 2
labels: ["wayfinder:prototype"]
---

# Design the scale-down and scale-up demonstration

Type: prototype
Status: resolved
Assignee: primary AI Wayfinder with user
Blocked by: 03, 04, 06
Parent: [Portable team-as-code: scale down, scale up](../map.md)

## Question

What small demonstration would convincingly show that the same operating skills
work with minimal local bindings and with Paseo plus a team panel?

Use [Agree on the portable team and binding contracts](03-team-and-binding-contract.md)
and [Define what a binding migration preserves](04-migration-contract.md).
Create a rough walkthrough and panel sketch for human reaction, not production
code. Include assignment, review handoff, occupant replacement, restart, and a
missed or duplicate wake. Decide whether migration belongs in the first demo or
only the design proposal. Define evidence and success criteria for both profiles.

Use [Define ongoing team memory and continuity](06-team-memory.md). A successor
builder must retrieve relevant decisions and failed approaches without inheriting
the predecessor's conversation, verify consequential claims, and correct or
supersede a stale entry. Show a useful discovery becoming shared team knowledge.

Distinguish what a written walkthrough establishes from behavior requiring a
future live experiment. The finished map should support a concrete implementation
proposal without claiming the experiment has already run.

## Prototype for discussion

[Demonstration walkthrough and team-panel sketch](../research/demonstration-sketch.md)
is a written prototype. The user accepted its first three choices: three seats,
one small fixture task, the same portable skills in both profiles, explicit
failure observations, and a bounded interchange exercise. No candidate runtime
or panel is implemented or activated.

## Confirmed by the user — demonstration Q1–Q3

- Use coordinator, builder and reviewer seats on the documentation-link repair
  fixture. Run unchanged portable skills in both configurations, including builder
  replacement, recovery/correction of inherited knowledge, review, duplicate
  requests, busy-seat wakes and restart recovery.
- Include a bounded local-to-local interchange exercise: paused source, inactive
  import, preservation inspection, explicit cutover and separate runtime rebinding.
  Pause before activation to exercise recovery. This does not qualify GitHub or
  GitLab translation.
- Start with a read-mostly team panel that separates occupant, runtime execution,
  task custody, pending reassessment and knowledge-review state. Initial actions
  are Open occupant, Inspect evidence and Request reassessment. Replacement and
  cutover use explicit operator flows whose outcomes appear in the panel.

## Confirmed by the user — demonstration Q4–Q5

- Minimal baseline: Git, Python standard library and one model harness with its
  own declared runtime dependencies; a foreground tick loop, without a separate
  team database, cron installation, tmux or flock package.
- Paseo baseline: researched kit pin 0.15.0 with exact package versions recorded.
  The installed 0.12.0 host does not qualify as that baseline. Use identical
  role/skill files and the same model/settings in both runs; qualify one OS first.
- Per profile: three seats, one builder replacement, one fixture task, one pass
  through failure scenarios, and at most 30 minutes. Include one migration
  exercise. A hard model-spend cap must be chosen before launch.
- Capture actual revisions, operation results, check output, knowledge corrections,
  review markers and cutover observations. Every required behavior needs evidence;
  missing capabilities/timeouts are blocked or incomplete, not passes.

## Answer

Resolved by explicit user acceptance of demonstration Q1–Q5. The linked sketch
and confirmed constraints define the future experiment. No runtime, dependency
upgrade, migration or model-spend budget has been activated by this decision.
The proposal must make adoption/decoupling/replacement/amendment of Maintainers
recognizable to Will; this is tracked in
[Assemble the recognizable Maintainers proposal](08-proposal-synthesis.md).
