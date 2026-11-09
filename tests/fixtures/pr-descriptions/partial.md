## Summary

The recovery explanation omits the retry decision. Document that decision;
the planned automation remains incomplete.

- Context: Related to https://example.invalid/fixture/repository/issues/13.
- Plan: documentation first; automation requires a follow-up change.
- Rollback: revert the documentation; no migration.
- Security: no permission or data-flow change.

## Validation

Revision `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb`: no commands executed because
the isolated runner is unavailable. The implementer must run `make check` and
`pre-commit run --all-files` in an approved guest before requesting review.
This draft is blocked; merge also awaits required review and checks.

- [ ] `make check` passes
- [ ] Behavior changes include offline fixture coverage
- [ ] Executable modes and provenance are preserved where applicable
- [ ] No secrets, sensitive state, CA bundles, handoffs, issue drafts, Nexus
      records, or engagement artifacts are included
- [x] AI assistance is disclosed when it materially contributed

The implementer must resolve remaining checklist assertions during validation.

## Sync Impact

No source import or downstream sync.

## AI assistance

OpenCode drafted the explanation; the existing editor clarified the recovery scope.
Credit: existing editor (retained synthetic credit).

Co-authored-by: OpenCode
