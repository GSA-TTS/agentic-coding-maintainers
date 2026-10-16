# Contributing

## Before You Start

- Open an issue for material behavior or governance changes.
- Do not include secrets, sensitive state, private infrastructure details, or
  engagement artifacts.
- Preserve the provenance of imported tools and runbooks.

## Make A Change

1. Create a focused branch.
2. Make the smallest correct change.
3. Add or update offline fixtures for behavior changes.
4. Run `make check`.
5. Use a Conventional Commit message with a verified contributor identity.
6. Open a pull request and complete the template.

At least one applicable CODEOWNER must review the change. Do not merge when CI
is failing or required evidence is missing.

For a new imported skill, include `SKILL.md`, `PROVENANCE.md`, offline tests,
and any config schema/examples needed to keep consumer-specific values out of
the reusable core. Do not package trusted host-control functionality as a guest
sandbox kit.

## Sync Changes

This repository is canonical after the initial import. Review any later source
change before applying it here. Update the selected skill's `PROVENANCE.md` with
the source revision and material adaptations. A downstream copy in
`agentic/.agents/skills/<skill-name>` must record this repository's canonical
commit in its `PROVENANCE.md` and pass all applicable local fixture suites for
that skill.
