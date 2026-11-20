# Pinned pre-dual-format operational readers

Source: `GSA-TTS/agentic-coding-maintainers`, exact commit
`638763a521d2c86f8d453b603d3bdcb983eba116` (the integration base).
These are repository-owned CC0-1.0 sources, not reconstructed validators.

`manifest.json` version 1 records the full `source_revision` and exactly eight
`files`, each with `source_path`, inert `file` basename, exact byte `size`, and
lowercase SHA-256 `sha256`. The `.py.txt` files must be byte-for-byte Git blobs
from that revision; no newline normalization, fixes, or current-module fallbacks.
The primary materializes the reviewed baseline blobs and manifest before testing.
Missing files or mismatched manifest contents are test failures, never skips.

`tests/dual-format-integration-test.py` verifies the complete manifest inventory,
hashes and sizes before copying these bytes into a temporary sibling-preserving
source tree **inside the independently isolated validation guest**. Only there
are the historical readers imported and exercised. Do not execute these files
on the host. The fixture tree includes the core's runtime/reservation-history
dependencies and both journal families; it never imports current implementations
as historical reader dependencies.

The operational checks cover native task 4/5 (including null-worker records),
native weak/declared intents 3/4, request 3, publisher binding 3 before opening a
TTY, and refusal of mixed history at existing SQLite metadata versions 6 and 7. State
bytes are compared across refusal. The positive control is the current reader
accepting real producer output, not an assumption that every old refusal proves
a valid input. Other unsupported consumer execution paths are separately fenced;
this inventory is not a claim to have executed every historical controller.
