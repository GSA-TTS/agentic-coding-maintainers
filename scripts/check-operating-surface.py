#!/usr/bin/env python3
"""Check byte parity for shipped canonical command examples without loading them."""

import argparse
import os
import stat
import sys
from pathlib import Path


class Mismatch(ValueError):
    pass


def read_regular(path: Path) -> bytes:
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("command path contains a symlink")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("command is not a regular file")
        data = handle.read(100_001)
    if not data or len(data) > 100_000:
        raise ValueError("command is empty or oversized")
    return data


def check(root: Path) -> int:
    canonical = root / ".agents/skills/workspace-orchestrator/examples/commands"
    installed = root / ".opencode/commands"
    for directory in (canonical, installed):
        if any(item.is_symlink() for item in (directory, *directory.parents)) or not directory.is_dir():
            raise ValueError("command directory missing or symlinked")
    # Only explicitly shipped examples participate: consumers may have additional
    # project-specific commands with no corresponding orchestrator example.
    sources = sorted(canonical.glob("*.md"))
    if not sources or not any(path.name == "orchestrate-start.md" for path in sources):
        raise ValueError("required canonical orchestrate-start command missing")
    for source in sources:
        if read_regular(source) != read_regular(installed / source.name):
            raise Mismatch(f"installed command differs: {source.name}")
    return len(sources)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, nargs="?", default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        count = check(args.root.absolute())
        print(f"command parity: PASS ({count} canonical commands)")
        return 0
    except Mismatch as exc:
        print(f"command parity: FINDINGS ({exc})", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("command parity: UNVERIFIED (missing, mismatched or unsupported command input)", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
