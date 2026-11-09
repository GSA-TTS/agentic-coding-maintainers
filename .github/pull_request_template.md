[PR/MR description guidance](https://github.com/GSA-TTS/agentic-coding-maintainers/blob/main/docs/PR-DESCRIPTIONS.md)

## Summary

Describe the problem, change and resulting behavior in 1–3 sentences.

- Context: verified issue/ADR reference or required context.
- Plan: mapping to the approved plan and any remaining dependency.
- Rollback: reversal/migration, or why not applicable.
- Security: authentication, authorization, data handling and attack-surface impact,
  or why not applicable.

## Validation

Actual commands, environment, tested revision, observed outputs and pass/fail
status; sanitized transcript in the body or attached artifact, and any gaps with
owner/next action. Re-verify after changes.

- [ ] `make check` passes
- [ ] Behavior changes include offline fixture coverage
- [ ] Executable modes and provenance are preserved where applicable
- [ ] No secrets, sensitive state, CA bundles, handoffs, issue drafts, Nexus
      records, or engagement artifacts are included
- [ ] AI assistance is disclosed when it materially contributed

## Sync Impact

Describe any source import or downstream agentic workspace sync. Include the
source or canonical revision, as applicable.

## AI assistance

Tools and contribution: describe material assistance; preserve existing credits.

<!-- For material AI assistance, replace the fallback below only with the actual
harness verified from trusted runtime/kit metadata (not the model/provider).
Preserve other credits above it; keep one final harness credit, preceded by a
blank line. For human-only work, remove inapplicable AI prompts and credit. -->

Co-authored-by: AI assistant (harness unknown)
