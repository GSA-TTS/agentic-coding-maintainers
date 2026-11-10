"""Bounded local process observation for the coordination core.

`process_identity` reports whether one PID is visible to `ps` and its start time.
It is evidence about that single process only: it is not proof that descendants
stopped, that a worker's conversation or session is live, or that the task may be
released. Callers decide what an observation permits. Extracted unchanged from
`orchestrator-state.py`, which keeps a compatibility wrapper.
"""

from __future__ import annotations

import subprocess


def process_identity(pid: int, *, environment: dict[str, str] | None = None) -> tuple[str, str | None]:
    try:
        value = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="], check=False,
            capture_output=True, text=True, timeout=3, env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown", None
    if value.returncode == 1 and value.stderr.strip():
        return "unknown", None
    if value.returncode not in (0, 1):
        return "unknown", None
    text = value.stdout.strip()
    return ("alive", text) if text else ("absent", None)
