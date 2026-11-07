---
title: "Portable team-as-code: scale down, scale up"
description: "Wayfinder map for portable team skills, minimal local bindings, and a Paseo team experience."
status: draft
tier: 2
labels: ["wayfinder:map"]
last_updated: "2026-11-06"
---

# Portable team-as-code: scale down, scale up

## Destination

An evidence-backed design proposal for the collaborators to review: portable
team-operating skills, binding contracts, a minimal local configuration, and a
Paseo configuration with a team panel. Define a bounded demonstration that can
show the same skills operating across those configurations.

## Notes

- This is a local Markdown decision tracker, not a set of drafts for GitHub
  issues. Its scope is this research effort; it does not replace the repository's
  implementation tracker or running coordinator.
- The user approved charting on `research/portable-team-as-code`. The effort is
  planning and research, not production implementation or service activation.
- Agreed direction: preserve the team-as-code pattern; unchanged execution of
  arbitrary OpenRig bundles is not required. Assess RigSpec import separately.
- Agreed direction: demonstrate scale-down defaults with as little installed
  infrastructure as practical, and scale-up UX through Paseo and a team panel.
- The default task binding should be authoritative local Markdown, using local
  Git for conditional publication as the current design candidate. No forge
  account or database should be required. Model access is a separate concern.
- Confirmed by the user after conversation with Will: GitHub issues are
  authoritative in Maintainers; locally cached issue metadata is an optimization.
  Keep issue authority distinct from local coordination/claim/receipt state.
  GitLab native-issue authority remains the portable design target.
- Will reports decoupling in flight. Follow the
  [upstream binding watch](issues/07-upstream-binding-watch.md) during foreground
  design sessions and before freezing reuse choices; date and pin observations.
- Default wakes should use a cron-compatible command or a simple recurring loop.
  Paseo scheduling is a richer binding. The accepted contract defines coalesced
  seat reassessment; concrete implementation remains to be qualified.
- Explicitly address stable team ownership, replaceable runtime occupants, and
  host-specific execution observation. Specify missing binding interfaces.
- Consider Markdown as a migration interchange format. Moving task data and
  transferring active execution are separate questions.
- Ongoing team memory is a first-class binding and operating discipline, not
  just an occupant recap. Cover team, seat, task, and occupant scopes; sources,
  freshness, correction, retrieval, shared updates, and selective preservation.
  The minimal default is structured Markdown with Git history. Richer retrieval
  should not require different team skills.
- The demonstration must replace a builder occupant, recover relevant decisions
  and failed approaches, and verify consequential inherited claims before work
  continues. Memory export and migration are part of the migration decision.
- Consult wayfinder and codebase-design; use grilling and domain-modeling for
  human decisions, and research for evidence investigations.
- AI-assisted research must distinguish observed implementation, documented
  plans, user-approved direction, and recommendations. Pin source revisions.
- Initial source baseline: Maintainers `f21052d6097cd40164d7f7c42a0e6f7bf361701b`.
  Earlier OpenRig and Paseo findings need source verification in the research
  tickets, particularly version-sensitive runtime behavior.
- Research was completed in two separate Maintainers project workspaces. The
  [research admission record](research/research-admission.md) records ownership,
  the user's research-only session-backed admission exception, source freshness,
  and the observed PID/session mismatch. This effort evaluates Maintainers from
  outside; its existing implementation does not predetermine the design.

## Decisions so far

- [Locate reusable coordination and missing binding interfaces](issues/01-maintainers-binding-surfaces.md): baseline coordination records are coupled to storage/runtime; Will confirms GitHub issue authority with local caching, and published session-binding work is advancing. Revalidate reuse against the upstream watch.
- [Compare minimal local operation with the Paseo experience](issues/02-minimal-and-paseo-bindings.md): shared skills are plausible, but runtime delivery, replacement and memory need explicit contracts; Paseo guarantees vary between installed 0.12.0 and kit-pinned 0.15.0.
- [Agree on the portable team and binding contracts](issues/03-team-and-binding-contract.md): seat custody survives occupant changes; conditional operations, replayable results, coalesced seat wakes and explicit capabilities form a cooperative, runtime-independent contract.
- [Define ongoing team memory and continuity](issues/06-team-memory.md): scoped authored knowledge, indexed orientation, linked corrections and revision-specific review preserve learning through abrupt occupant loss; both configurations must demonstrate the same recovery sequence.
- [Define what a binding migration preserves](issues/04-migration-contract.md): versioned interchange preserves identity, knowledge and operation evidence; supervised single-authority cutover has explicit loss reporting and recovery, with runtime rebinding separate.
- [Design the scale-down and scale-up demonstration](issues/05-demonstration-design.md): three seats repair one fixture in both profiles, exercise continuity and local cutover, and expose distinct states in a read-mostly panel under fixed time/spend bounds.

## Not yet specified

The agreed route is now assembled through
[Assemble the recognizable Maintainers proposal](issues/08-proposal-synthesis.md).
The [proposal for the user and Will](proposal.md) contains the concrete module
change map, proposed interfaces/configuration and accepted demonstration bounds.
Concrete extraction scope depends on matching Will's in-flight interfaces to
the proposal; the upstream watch remains active during foreground review.

## Out of scope

- Building or deploying the production coordinator during this map.
- Full compatibility with every OpenRig runtime resource or bundled command.
- Installing cron jobs, starting unattended agents, or activating remote writes.
- Multi-host active-active coordination in the first demonstration.

## Local tracker operations

Child tickets live in `issues/`, one file per decision. Frontmatter supplies
document metadata; `Type`, `Status`, `Assignee`, and `Blocked by` lines supply
tracker state. Only `wayfinder:` labels are used.

The frontier is the numerically ordered set of open, unclaimed tickets whose
blockers are resolved. Claim by recording the assignee and setting `Status:
claimed` before work. Append a resolution under `## Answer`, mark resolved, and
add a named link with a one-line gist to Decisions so far. Dependencies use local
ticket numbers because this tracker has no native blocking relationship.

Research assets belong in `research/`, linked from their ticket. Maintain one
writer per artifact. Agent dispatch also requires the repository's worker-slot
and identity procedures, subject to the user's scoped research-only exception
in the [research admission record](research/research-admission.md); a ticket
claim alone does not reserve runtime capacity.

Do not push research branches without the required pre-push adversarial review.
