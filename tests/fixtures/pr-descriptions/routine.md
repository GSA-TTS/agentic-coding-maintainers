## Summary

Ambiguous retry guidance delayed recovery. Clarify when an operator can retry;
runtime behavior is unchanged.

- Context: Closes https://example.invalid/fixture/repository/issues/12.
- Plan: document the existing retry decision.
- Rollback: revert the documentation change; no migration.
- Security: no permission or data-flow change.

## Validation

Isolated fixture guest, revision `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`:
`make check` and `pre-commit run --all-files` passed (exit 0).
[Sanitized transcript](https://example.invalid/fixture/evidence/12).
Human review remains required before merge.

- [x] `make check` passes
- [x] Behavior changes include offline fixture coverage
- [x] Executable modes and provenance are preserved where applicable
- [x] No secrets, sensitive state, CA bundles, handoffs, issue drafts, Nexus
      records, or engagement artifacts are included
- [x] AI assistance is disclosed when it materially contributed

## Sync Impact

No source import or downstream sync. Behavior-fixture and mode/provenance
assertions are satisfied by nonapplicability for this documentation-only change.

## AI assistance

OpenCode drafted the clarification and checked its consistency with the source.

Co-authored-by: OpenCode
