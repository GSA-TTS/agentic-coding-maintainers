#!/usr/bin/env python3
"""Fixture-only observer of one public CLI invocation; never retries a request.

The fixture's python3 shim passes through the public run.sh entrypoint here.
Observe the exception caught by main in that same process. Emit only on an
unexpected exit: no exception messages, task values, paths, stdout or stderr.
"""

import json
import runpy
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
TARGET = BIN / "foreground-delivery.py"
KINDS = {"Unverified", "UnknownError", "BusyError", "InputError", "ValueError",
         "TypeError", "KeyError", "OSError", "FileNotFoundError", "PermissionError",
         "TimeoutExpired", "JSONDecodeError", "AssertionError"}


def summarize(exception, traceback):
    frames = []
    while traceback is not None:
        code = traceback.tb_frame.f_code
        path = Path(code.co_filename)
        if path.parent == BIN:
            # Labels come from installed code, never exception or task text.
            frames.append({"file": path.name, "function": code.co_name,
                           "line": traceback.tb_lineno})
        traceback = traceback.tb_next
    kind = type(exception).__name__
    return {"exception": kind if kind in KINDS else "OtherException", "frames": frames[-8:]}


def main():
    expected = int(sys.argv[1])
    # The public shell entrypoint supplied these exact isolated Python arguments.
    if sys.argv[2:5] != ["-I", "-B", str(TARGET)]:
        raise SystemExit("diagnostic launcher only accepts the foreground fixture CLI")
    sys.argv = sys.argv[4:]
    captured = None

    def trace(frame, event, arg):
        nonlocal captured
        if frame.f_code.co_filename != str(TARGET) or frame.f_code.co_name != "main":
            return None
        if event == "exception" and isinstance(arg[1], Exception):
            captured = summarize(arg[1], arg[2])
            if "worker" in frame.f_locals and "live" in frame.f_locals:
                worker = frame.f_locals["worker"]
                if isinstance(worker, dict):
                    captured["worker_observation"] = {
                        "alive": frame.f_locals["live"] == "alive",
                        "start_matches": frame.f_locals.get("start") == worker.get("process_start")}
        return trace

    sys.settrace(trace)
    code = 0
    try:
        runpy.run_path(str(TARGET), run_name="__main__")
    except SystemExit as exc:
        code = exc.code if type(exc.code) is int else 1
    finally:
        sys.settrace(None)
    if code != expected:
        diagnostic = {"expected_exit": expected, "actual_exit": code,
                      "caught_exception": captured, "source": "same-invocation"}
        # Bounded JSON of structural labels only; never print a raw exception.
        encoded = json.dumps(diagnostic, sort_keys=True)
        if len(encoded) > 3000:
            encoded = '{"diagnostic":"exceeded structural bound"}'
        print("FOREGROUND_FIXTURE_DIAGNOSTIC " + encoded, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
