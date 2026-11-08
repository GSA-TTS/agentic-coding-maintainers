---
title: "Upstream binding watch evidence"
description: "Dated source and maintainer observations affecting portable-team reuse."
status: draft
tier: 2
last_updated: "2026-11-06"
---

# Upstream binding watch evidence

AI-maintained evidence for [Track upstream authority and session-binding changes](../issues/07-upstream-binding-watch.md).

## Maintainer clarification

2026-11-06: the user reports direct confirmation from Will that GitHub issues
are authoritative and local issue metadata is an optimization cache, with
decoupling in flight. Treat this as maintainer-confirmed architecture, not as a
source experiment. The earlier report's inference from operational `task.json`
to all task/issue authority was too broad. Local claim, execution and receipt
records can coexist with authoritative issue metadata; inspect those facts
separately when evaluating the future interface.

## Foreground checkpoint — 2026-11-06T20:00:47Z

GitHub main: `568125c3d33572eb64d681b857439d81c10adbe7`.
The research checkout remains at its original baseline; no branch update needed
to inspect pinned remote source.

### Material changes since the original research

- [Pilot cooperative session-bound lifecycle](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/128)
  merged at `aeaa68ce36ab515d76640205326be0e4df8142ad`: opt-in schema 3 adds
  session correlation and claim generation; mutations compare session, worker,
  generation and revision under the coordinator lock. This supersedes the earlier
  blanket statement that the current core has no session/generation comparison.
- [Recover interrupted bound tasks explicitly](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/133)
  merged at `6a63c14c40d9770826c7d2687c400811f2957901`: explicit guarded recovery
  checkpoints supported interrupted transitions to Blocked, retaining receipts.
- [Qualify acknowledged cooperative handoff](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/135)
  OPEN at head `4ca03cca49a26298adf9150f64e91446321ddf68`. Documentation and
  fixtures describe release, independently observed stop, and new-generation
  claim. Both returned checks were SUCCESS. This is observation, not merge
  approval or independent review of that head.
- [Release 0.2.0](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/130)
  OPEN at head `6779319be7cfe23e222f092ed44c80961a1b9327`; release packaging is
  not evidence of additional binding capability.

The [current native-ownership documentation](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/568125c3d33572eb64d681b857439d81c10adbe7/docs/NATIVE-OWNERSHIP.md)
was read in full. It explicitly limits the pilot to the core CLI: opaque session
labels are cooperative comparisons, not native authentication; PID observations
remain required; unsupported monitor/execution/domain paths reject schema 3.
Thus this is relevant progress, not a demonstrated general runtime/persistence
decoupling. The document still calls coordinator task JSON authoritative, and
the journal issue below does too. This terminology must not be conflated with
Will's clarification about authoritative GitHub issues and cached metadata.
The precise cache-to-coordination mapping remains to be verified in source.

### Open watchlist

All listed items were returned OPEN in the bounded open-issue scan:

- [Session-aware native ownership and root reconciliation](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/116): broad effort remains open after the pilot.
- [Mirror admitted GitHub ownership](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/117): ownership publication path.
- [Guard PR branch updates by admitted session ownership](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/118): action-boundary ownership.
- [GitLab native ownership parity](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/119): future forge parity.
- [Authority ADR and capability inventory](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/66): capability authority, distinct from issue data authority.
- [Durable reconciliation journal and operation replay](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/67): body read; operational task JSON, receipt-before-journal ordering.
- [Restricted GitHub effects and durable outbox](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/68): effect delivery.
- [Supervised lifecycle and recovery controls](https://github.com/GSA-TTS/agentic-coding-maintainers/issues/74): recovery integration.

### Query evidence and coverage

`gh pr list --state open --limit 100` returned 2 PRs;
`gh issue list --state open --limit 200` returned 26 issues;
`gh pr list --state merged --limit 20` supplied recent merge discovery, not full
history. Read main commit metadata, detailed merged PRs above, the current
handoff PR head/checks/files, issue bodies for authority/journal, and pinned
native-ownership documentation. All commands completed successfully. No candidate
code or tests ran. Subsequent changes require a new observation.

## Foreground checkpoint — 2026-11-06T20:06:46Z

Main advanced to `b2d052fa74e8f1e7ba316677786c6ca882ece77a`.
[Qualify acknowledged cooperative handoff](https://github.com/GSA-TTS/agentic-coding-maintainers/pull/135)
is now MERGED, with merge commit matching main and `mergedAt`
`2026-11-06T20:03:20Z`. The one remaining open PR is Release 0.2.0 at the same
previously recorded head. The open-issue scan again returned 26 issues; the
focused authority/session/forge/recovery watchlist remains open.

Queries: open PRs (limit 100), open issues (limit 200), main commit metadata,
and the handoff PR's state/merge commit/time. All succeeded. This updates merge
status, not live-runtime qualification or an independent code review. The
contract decision can use the observed handoff progress without assuming the
broader decoupling work is complete.

## Proposal checkpoint — 2026-11-06T20:51:23Z

Main remains `b2d052fa74e8f1e7ba316677786c6ca882ece77a`; the one open PR remains
Release 0.2.0 at its previously recorded head. The open-issue scan returned the
same 26 issues with unchanged update timestamps. No newly published decoupling
PR was present in this bounded scan.

For proposal accuracy, primary additionally read current source spans for
`validate_cooperative_binding` (394–424), `read_task/write_task` (615–626),
`command_claim` and cooperative mutation guards (863–967), and recovery gates
(1450–1466). These confirm per-task generation/session comparisons, direct JSON
persistence, continued PID-dependent admission/recovery, and explicit operator
recovery. Compared the original research baseline to current main to identify
which consumer files changed. This is static source verification, not runtime
qualification. The proposal adopts the new pilot semantics and identifies the
additional stable-seat/runtime seams instead of repeating the obsolete finding
that no generation checks exist.
