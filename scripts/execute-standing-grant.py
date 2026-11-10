#!/usr/bin/env python3
"""Runtime entry point: no proposal, approval file or grant-selection option."""

import importlib.util
import sys
from pathlib import Path


def main():
    spec = importlib.util.spec_from_file_location("standing_dispatch", Path(__file__).with_name("standing-grant-dispatch.py"))
    if spec is None or spec.loader is None:
        return 3
    dispatch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dispatch)
    adapter, publisher, _ = dispatch.modules()
    try:
        adapter.require(sys.flags.isolated and sys.dont_write_bytecode, "ISOLATED_PYTHON_REQUIRED")
        args = dispatch.arguments()
        output = dispatch.recover(args) if args.action == "settle" else dispatch.dispatch(args)
    except Exception as exc:
        output = publisher.public_failure(exc)
    return publisher.emit_result(output)


if __name__ == "__main__":
    sys.exit(main())
