---
title: "Track upstream authority and session-binding changes"
description: "Foreground tracking of Maintainers work that changes portable-team reuse decisions."
status: draft
tier: 2
labels: ["wayfinder:task"]
last_updated: "2026-11-06"
---

# Track upstream authority and session-binding changes

Type: task
Status: claimed
Assignee: primary AI Wayfinder
Blocked by: none
Parent: [Portable team-as-code](../map.md)

## Question

What published authority, cache, session-binding and recovery changes must the
design account for before its reuse proposal is frozen?

User requested this watch on 2026-11-06 after confirming with Will that GitHub
issues are authoritative, local issue metadata is cached, and decoupling is in
flight. Refresh open issues/PRs and relevant recent merges at foreground session
resumption and before a reuse/contract freeze. Discover new linked work, inspect
relevant current source, and append dated deltas to the
[upstream evidence record](../research/upstream-binding-watch.md).

No unattended monitor or schedule is active. A checkpoint proves its observation
time only. Remote reads are authorized; remote edits are not. Keep operational
coordination state distinct from cached issue metadata. Do not assume either
that unpublished work is absent or that a merged partial pilot is a full adapter.

Completion: the final design cites a refreshed upstream snapshot and identifies
which concrete interfaces are available, in flight, or unverified at that point.
This task stays open during the design; it does not block independent decisions.
