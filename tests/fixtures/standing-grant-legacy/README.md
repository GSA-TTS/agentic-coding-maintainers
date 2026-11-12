# Pinned legacy reader fixtures

These inert `.py.txt` files are byte-exact source from canonical commit
`5d2c0a2b58ea7ba725ec0ce61044b523652482ff` in
`GSA-TTS/agentic-coding-maintainers`. `manifest.json` records each original path,
SHA-256 and byte length. They preserve the production pre-standing-grant readers
for compatibility refusal tests; they are not current implementation code.

The sandbox-only test verifies the manifest, then copies the bytes to `.py` files
in its private temporary fixture directory. No Git history or network fetch is
needed, including in shallow CI. Never execute these fixtures on the host.
