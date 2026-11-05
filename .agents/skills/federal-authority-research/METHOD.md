# Research method

## Question and source selection

Start with a concrete rule ID and affected audience, document types, jurisdiction,
agency, and period. Separate these authority kinds in each claim:

| Kind | Evidence to inspect |
| --- | --- |
| `legal` | Official enacted law and applicable codified law or regulation; verify amendment history and the operative provision, not just a search summary. |
| `eo` | Official executive order text and publication in the Federal Register; check amendments, revocation, and operative dates. |
| `policy` | Official OMB issuance or issuing agency policy, including attachments, scope and replacement notices. |
| `owner_style` | Identified owner's approved style guide and dated revision; owner preferences are not automatically legal obligations. |
| `heuristic` | Explicit editorial judgment with rationale; never elevate model recommendations into authority. |

Use official law publishers (for example govinfo.gov and uscode.house.gov), the
Federal Register and official codified regulations (federalregister.gov and
ecfr.gov), official EO publications, official OMB publications, and the responsible
agency/owner's approved guide as appropriate. These are discovery starting points,
not blanket authenticity or applicability endorsements. Confirm the publisher,
document identity, version and exact provision. Secondary sources can locate
primary sources but cannot substitute for unavailable operative text. Search
hits, cached snippets, model output and votes are leads only.

## Evidence and interpretation

Preserve the reviewed artifact's exact bytes in an approved evidence location,
outside this skill when private or otherwise unsuitable for source control.
Compute its SHA-256 independently; record URI, publisher, locator, exact quote,
version, UTC retrieval and review timestamps, review-notes reference, effective
interval, and review due date. Keep publication/issuance (`published_on`, optional),
retrieval, review, and effective dates distinct; use `version` to identify the
publication/issuance revision. Re-review unchanged bytes by updating review
metadata and notes, not by fabricating a newer retrieval. A locator
must allow a second reviewer to find the quote. Quote exactly; put paraphrase,
scope reasoning and uncertainty outside quotation marks. If excerpting, record
omissions explicitly and inspect surrounding definitions and exceptions.

For every claim record the affected rule, source IDs, authority kind,
applicability, exceptions (including explicitly reviewed absence of exceptions),
and status. Inspect mandatory versus advisory language, responsible parties,
document/audience exclusions, transition periods and owner approval. Do not infer
universal applicability from a federal publisher or from a plain-language theme.

Review supersession/revocation links and current operative versions. Retain old
evidence as superseded, linking to a known replacement where available; do not
silently overwrite history. A superseded source without a known successor stays
unverified for current use. Compare potentially conflicting obligations by scope,
issuing authority, dates, and exceptions. Do not mechanically rank every EO above
every policy, or let a newer style preference displace law. Escalate unresolved
legal conflicts to a qualified reviewer; mark claims unverified in the meantime.

`verified` is the researcher's declaration that evidence has been inspected and
its interpretation reviewed, not a machine-proven fact. Keep reviewer identity,
review time, conflict decisions and reasoning in approved research notes. The
bundle validator checks only required metadata and internal consistency; a
fabricated quote and invented digest could satisfy it. Neither model unanimity
nor metadata exit 0 constitutes legal truth or independent human approval.

## Freshness and review

Use an explicit inclusive UTC calendar-day cutoff. No retrieval later than that
day is accepted. Review due equals cutoff is current; due before cutoff is stale.
Effective interval endpoints are inclusive for this metadata contract, not a
claim about legal temporal semantics. Resolve legally different boundaries in
notes and application logic before implementing a rule. An unknown start is
represented by `effective_from: null` and always makes a selected source
unverified operationally; do not invent a date. A null end means no declared end,
not unknown end: unknown end requires unverified source status and explicit
uncertainty in review notes, never a verified no-end declaration.

Version 1 selects a nonempty `active_claim_ids` view explicitly. Retain predecessor
sources/claims as history; do not delete them to obtain a current verdict. All
records must be structurally valid, but inactive stale/superseded/unknown history
does not degrade an otherwise current selected replacement. Selecting an old
superseded claim/source does degrade it. Links never silently switch selection.

For historical assessment explicitly select claims and an as-of cutoff in a
separate assessment bundle. No implicit historical mode exists; retrieval/review
after that cutoff is invalid. Record the document period separately in review
notes, including how the source's operative period applies to that document.
Do not equate present review freshness with historical legal applicability.

Re-review in a foreground session on publication/amendment/revocation events,
relevant owner changes, retrieval failures, or at the monthly checkpoint. Record
the event, reviewer, exact artifacts inspected, as-of date, changed claims,
unresolved questions and next review due. A link remaining reachable is not proof
that its bytes or authority are unchanged. No background daemon, auto-refresh,
automatic rule edit, or automatic GitHub write is provided or authorized here.
