---
title: "Portable team demonstration: walkthrough and panel sketch"
description: "Written prototype for choosing a bounded scale-down and Paseo demonstration."
status: draft
tier: 2
last_updated: "2026-11-06"
---

# Portable team demonstration

AI-authored written prototype for
[Design the scale-down and scale-up demonstration](../issues/05-demonstration-design.md).
The user accepted the fixture, local migration exercise and read-mostly panel
(demonstration Q1–Q5), including the dependency/version and run-budget constraints below.
This document is not execution evidence.

## Question this prototype answers

Would the same three-seat team, doing one small observable task through two
runtime profiles, convincingly demonstrate portability and memory continuity?

## Proposed fixture

Three seats: coordinator, builder, reviewer. The human remains the operator.
One synthetic documentation-repair task: fix a broken relative link in a tiny
fixture repository and demonstrate that its local link check passes.
The fixture includes two similarly named targets, a recorded failed approach,
and a prior decision explaining the correct target. A previously recorded
check result applies to an older revision, so the successor must verify rather
than inherit a current-success claim. This makes recovery measurable without
requiring a large application or external account.

The fixture repository and any future checks execute only in the separately
approved demonstration environment. This research creates no executable fixture.

## Two runs, one portable team

| Surface | Minimal profile | Paseo profile |
| --- | --- | --- |
| Team skills and role instructions | Same versioned files | Same versioned files |
| Task and authored-knowledge binding | Markdown/Git | Same Markdown/Git binding |
| Agent launch/resume | Harness CLI with its declared runtime requirements | Paseo agents and launch settings |
| Recurrence | One bounded tick command, foreground loop or cron where available | Paseo timer invokes the same semantic wake operation |
| Occupant binding | Explicit seat/generation mapping | Explicit mapping to Paseo agent/session references |
| Operator view | Readable records and command results | Team panel reading those records and runtime observations |

Paseo's native heartbeat alone does not implement agreed coalesced seat wakes.
Both profiles need the binding operation that retains pending reassessment intent.
Keep role/skill content identical; record hashes and the profile-specific config
diff. Model choice is recorded separately from portable behavior.

## Proposed walkthrough and required evidence

| Step | Event | Observable evidence |
| --- | --- | --- |
| 1 | Coordinator assigns the fixture task to builder | Stable task/seat IDs, authority revision, accepted operation result |
| 2 | Builder A records its decision, failed approach and sourced finding | Task/seat knowledge revisions linked from the orientation index |
| 3 | Repeat an accepted operation after withholding its response | Identical request returns original result; changed request using that ID is refused |
| 4 | Send two routine wakes for the same purpose while builder is busy | One pending seat reassessment; delivery attempts distinct from completion |
| 5 | Builder A's conversation becomes unavailable before final handoff | Retained checkpoint; execution observation distinguishes stopped from unknown |
| 6 | Bind Builder B as a new occupant generation | Seat custody unchanged; stale-generation team mutation refused; no inherited execution permission |
| 7 | Builder B orients without A's transcript and rechecks the stale claim | Sources read, current check output, correction linked to previous evidence |
| 8 | Reviewer examines the correction and the resulting repair | Reviewer occupant/generation and reviewed knowledge/artifact revisions |
| 9 | Share a useful discovery and consume the pending reassessment | Shared knowledge revision; relevant seats' review markers; no replay of every tick |
| 10 | Restart the tick runner or controller with pending intent | Current authority and pending purpose recovered; no duplicate semantic mutation |

Run the sequence independently in each profile from equivalent initial fixtures.
Controlled failure injection must be recorded as such. Real operations and actual
output in a later demonstration are required for behavior claims; a simulated
walkthrough establishes only whether the design makes sense.

If execution remains unknown at step 5, B may orient but conflicting writes must
stay blocked until stop or independent prevention is evidenced. Include this as
a visible branch, not an automatic success path.

## Proposed bounded migration exercise

Use the accepted versioned interchange to move a paused local authority A into
an inactive local authority B, then explicitly cut over and rebind runtime.
This exercises preservation and cutover with one task adapter; it does not
qualify GitHub/GitLab translation or prove heterogeneous storage portability.

Capture: source revision, manifest, identity mappings, knowledge/supersession,
operation outcomes, pending reassessment purpose, original review markers,
preservation report, cutover record, and one writable authority at activation.
Pause once after import and before activation to demonstrate that recovery
observes an inactive destination instead of assuming success.
Required semantic loss must visibly block activation. This exercise is included
in the accepted first demonstration; omission requires an explicit scope change.

## Proposed Paseo team panel — information first

```text
Portable team: Documentation repair     Task authority: local / revision r12
Runtime profile: Paseo                  Knowledge revision: k8

Seat          Occupant       Execution          Work
Coordinator   C / gen 1      idle               Coordinate repair
Builder       B / gen 2      unknown            Repair link [WRITES BLOCKED]
Reviewer      R / gen 1      idle               Review repair

Attention
  Builder: predecessor stop unverified — orientation allowed
  Reviewer: correction k8 published — last reviewed k7
  Builder: reassess repair pending — 2 wake requests combined

Selected task
  Decision / failed approach / evidence / correction / operation history

[Open occupant] [Inspect evidence] [Request reassessment]
```

All identifiers above are fictional display values. Execution, custody, knowledge
review and pending intent are separate fields. Unknown is visible. The panel
reads authoritative revisions and routes requests through existing binding
operations; it does not invent a second lifecycle or infer success from a button.
Recommend a read-mostly first panel with navigation and reassessment only;
replacement, cutover and other consequential actions use the explicit operator
flow, with their results visible in the panel.

## Confirmed demonstration shape

1. Three seats and the documentation-repair fixture, run with unchanged skills
   in both profiles.
2. Include the small local-to-local interchange/cutover exercise in the first
   demonstration, with its limited evidence claim.
3. Read-mostly first panel, with evidence/navigation/reassessment and distinct
   custody, execution and knowledge state.

## Accepted baseline and bounds

Minimal: Git, Python standard library, one model harness and its declared
dependencies; foreground tick loop, no separate team database, cron installation,
tmux or flock package. Paseo: 0.15.0 kit target with exact versions retained.
Installed 0.12.0 does not count. Both runs use the same model/settings and identical
role/skill files. Qualify one OS first; others remain untested.

Each profile has three seats, one builder replacement, one task, one pass through
failure cases and a 30-minute limit. Include one migration exercise. A hard
model-spend cap is set before launch. Required evidence comprises actual revisions,
operation results, verification output, corrections, review markers and cutover
observations. Missing evidence or timeouts are blocked/incomplete, never passes.
Exact OS/harness/model versions, numeric spend limit and launch authorization are
execution prerequisites tracked in the [proposal synthesis ticket](../issues/08-proposal-synthesis.md).
