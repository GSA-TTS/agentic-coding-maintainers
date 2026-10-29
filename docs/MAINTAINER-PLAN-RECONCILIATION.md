# Automated maintainer plan reconciliation

Observation date: 2026-10-28. AI-assisted implementation work in progress.

## Refreshed ecosystem

| Repository | Observed main | Latest release |
|---|---|---|
| Maintainers | `7485c686d70a871c73ab0db3101ae70a9da8a200` | No releases returned |
| Quickstart | `ef2496532fdd6ff643b7d67d44b1701c35bd2d22` | 4.1.1 |
| Patterns | `78154ec691103d907489d6b34b1ccf88887edd38` | 1.17.0 |
| Playbook | `9c4cf524bc3eea4d0cfbfe259e986248bf80ea8d` | 0.15.0 |

Quickstart advanced twice beyond the plan snapshot: provider-adoption validation
preparation and host-authoritative built-in kit healing with MSB forged-marker
and legacy-sandbox coverage. Preserve these interfaces. The other three main
revisions match the plan snapshot. Maintainers had no open PR at either refresh.

Quickstart release 4.1.1 consumes Patterns
`d2674db8b424402e912e95254d6b194a062deb73` (1.16.1); main consumes
`a1206c52ec82ae7ce080ad44a6e6ac6f951e6d20` (1.17.0). The inspected 1.17.0 kits
select OpenCode 2.0.30 and Playbook 0.14.0. These are consumed pins, not the
installed runtime or latest Playbook release.

Effective branch rules were queried through `rules/branches/main`. All four
require CODEOWNER approval and squash integration. Maintainers requires one
approval, stale-review dismissal, resolved threads and strict `Repository
checks`; CODEOWNERS still names only `@wz-gsa`. Its legacy protection API returns
404 despite the active ruleset. Patterns and Quickstart have merge queues;
Quickstart binds its Bash 3.2 required check to integration ID 15368. No native
rules were changed.

Project 120 returned 22 epic candidates across the other three repositories
and none for Maintainers. Parent/progress fields were unavailable from that
query. This is a board coverage gap, not evidence that Maintainers has no work.

## Deduplicated tracker mapping

All issue numbers in this table refer to `GSA-TTS/agentic-coding-maintainers`.

| Proposal | Tracker | Scope |
|---|---|---|
| E00 | #61 | Review and repair foundation |
| R01–R06, R10–R12 | #63 | Integrated first review/repair slice; full acceptance remains open |
| R07 | #64 | Frozen corpus and semantic comparison |
| R08 | #65 | Runtime, migration, synchronization and rollout |
| R09 | #21 | Existing outcome/cohort owner; no duplicate |
| M00 | #62 | Automated-maintainer initiative |
| M01 | #66 | Authority/service ADR and capability inventory |
| M02 | #67 and existing #29 | Operational journal; retain #29 source enumeration ownership |
| M03 | #68 | Typed GitHub effects/outbox |
| M04 | #69 | Continuous current-revision review |
| M05 | #70 | Legitimate approval/integration |
| M06 | #71 | Grooming/prioritization |
| M07 | #72 | Design/dependency scheduler |
| M08 | #73 | Polyrepo delivery |
| M09 | #74 | Service lifecycle/recovery |
| M10 | #75 | Governance activation/dogfood |

Existing #22 retains outage and follow-up maturity; #30 retains classification
corrections. #23 already has disposal improvements but still requires explicit
active-path cleanup and failed-disposal tests, per its current maintainer
comment. #14/#15 remain administration/governance work. The new graph is expressed
in tracker bodies; native sub-issue/dependency edges have not been written.

## Qualification and upstream reuse

- Session OpenCode: 1.19.3; Ubuntu VM OpenCode: 2.0.32, found through a login
  shell. Neither version observation proves review-runner qualification.
- MSB: 0.7.11. Network-off, restricted, non-root execution of the source and
  evidence protocol suites passed after a native digest-pinned image pull.
- Docker: repository tests run through the existing isolated harness. Initial
  full checks exposed missing rsync/jq and executable-fixture placement under
  noexec `/tmp`; installing disposable dependencies and using guest `/work`
  scratch allowed `make check` to pass for the source-capture increment.
- Ubuntu ARM64 Multipass guests lack `/dev/kvm`; nested MSB is not qualified.
  Docker validation remains available there.
- MSB loaded-image digest resolution matches open upstream
  `superradcompany/microsandbox#1764`; no local cache workaround was added.
- Upstream MSB nested-virtualization PR #823 merged after release 0.7.11. Its
  documented support excludes Linux ARM64; do not infer capability from merge
  status or silently replace the installed runtime.
- The installed acq checkout has preserved local installer edits whose behavior
  and test already landed in Quickstart PR #534. Reconcile that work rather than
  reimplementing or deleting it automatically.

## Current deliverable boundary

Implemented source capture and retained review-claim operations are foundations,
not the completed vertical slice. Real harness dispatch, corroborated source
access/execution receipts, owner patch transport, current readiness, continuous
monitoring and GitHub effect authorization remain unqualified or unimplemented.
No GitHub App, machine eligibility check, service supervisor or new approval/
merge permission was activated. No semantic outcome improvement is measured.
