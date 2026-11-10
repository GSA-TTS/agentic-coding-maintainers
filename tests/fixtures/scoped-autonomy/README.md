# Scoped autonomy documentation fixtures

These are synthetic contract examples, not active grants, issue drafts, approval
records or executor inputs. `scenarios.json` maps concrete review cases to the
canonical policy's action IDs and normative passages. Its expected dispositions
are authored review expectations, not results computed by a test-only policy
resolver. `grant-example.json` illustrates the required field groups using only
synthetic identities and inert values; no existing command accepts this shape.

`tests/scoped-autonomy-contract-test.py` checks matrix completeness/classification,
scenario coverage and references, grant group completeness, local guidance links,
consumer neutrality and installed command parity. Deliberately removed rows,
changed classes, broken rule references and missing grant groups must be detected.
It neither authenticates approvals nor proves budgets, revocation, race handling,
TTY interaction or remote refusal. The actual future executor must test those
behaviors in independent isolation before each endpoint is enabled.
