# Synthetic description examples

These authored examples exercise the structure in
[PR/MR description guidance](../../../docs/PR-DESCRIPTIONS.md). They are offline
fixtures, not unposted issue drafts, live references or actual validation claims.
The `example.invalid` URLs, revisions and observations are synthetic.

| Example | Assumed inputs | Review expectation |
| --- | --- | --- |
| [Routine](routine.md) | Repository template; trusted runtime identifies OpenCode; the synthetic issue's entire scope is complete; passing isolated checks | Preserve all template checkboxes and fields; final OpenCode credit; closing reference |
| [Partial](partial.md) | Repository template; trusted runtime identifies OpenCode; only part of the synthetic issue is addressed; required execution unavailable; an existing editor credit | Neutral reference; unchecked assertion and explicit gap; preserve editor credit; no readiness claim |
| [Fallback](fallback.md) | No `AGENTS.md` or optional template; no mandatory issue prerequisite; no trusted harness identity | Summary/Verification and required content; no fabricated reference; unknown-harness final credit |

Tests check document links and these examples' structure, length and credits.
Mutation cases demonstrate detection of missing sections/checklists, broken
links, overlong examples, duplicate/wrong/misplaced attribution and unresolved
template prompts. They do not infer completeness, resolve policy precedence,
authenticate evidence or evaluate an LLM's compliance. Reviewers must check
those judgments against the nine rules and the real current revision.
