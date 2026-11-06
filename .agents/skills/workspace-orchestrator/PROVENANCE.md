# Provenance

This skill was copied with the source author's authorization from the
`review_things` repository on 2026-10-16.

- Source base commit: `c9248ac748ee3835df5b837ae8009fce4c3a389b`
- Source author: William Zujkowski
- Source state: orchestration files were uncommitted at import; the commit above
  is the recorded base revision and `SOURCE-SHA256SUMS` binds every imported file
- Original capability: host-local multi-agent task ownership, bounded worker
  admission, foreground GitHub monitoring, OpenCode role profiles, recovery,
  and independent review gates
- Destination adaptations: self-contained dispatcher; explicit consumer
  workspace root; generic validated repository/project monitor config; GSA
  Project 120 as an example only; reusable OpenCode v1 profile pack; canonical
  maintainer-repository ownership after import

The source author and accountable contributor explicitly authorized this copied
material and the listed destination adaptations for release under this
repository's CC0-1.0 dedication. This statement does not change the license of
other content in the source repository.

## Canonical adaptation: cooperative lifecycle binding pilot

Bounded issue #116 pilot based on canonical maintainer revision `00091f99`
(approved 2026-11-05): opt-in schema-3 cooperative task/worker session and retained
generation, explicit lock-held lifecycle comparisons, complete capacity metadata
checks, and fail-closed reconciliation. Schema 2 remains default; schema-1
migration and the imported source history above are preserved. Public core
readers/writers reject bound tasks unless explicitly opted in by the core CLI.
This is declared local correlation, not native authentication. The standalone
monitor now refuses schema 3 before poll configuration/state effects, and execution
observation refuses before definition/runtime work and runtime-config creation.
Full bound domain dispatch and interrupted-bound-intent recovery remain pending.
The canonical
repository adds `tests/cooperative-session-binding-test.py` and registers it in
`Makefile`; copied-skill consumers must separately carry/run that fixture when
validating this pilot. `CANONICAL-SHA256SUMS` binds the adapted skill assets.

Independent-review correction: validate the complete prospective bound record
and exact legacy scope metadata under lock before opt-in reserves capacity or
persists a claim. Schema 3 allows only base task fields, cooperative binding,
and the core legacy-finding disposition ledger; unsupported retained domain or
unknown extensions are refused on opt-in and subsequent reads without coercion.
