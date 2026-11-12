#!/usr/bin/env python3
"""Fixture-only observer of one public CLI invocation; never retries a request.

The fixture's python3 shim passes through the public run.sh entrypoint here.
Observe the exception caught by main in that same process. Emit only on an
unexpected exit: no exception messages, task values, paths, stdout or stderr.
"""

from contextlib import contextmanager
from importlib.machinery import SourceFileLoader
import json
import runpy
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
TARGET = BIN / "foreground-delivery.py"
COMPILE_ONLY_TARGETS = {name: str(BIN / (name + ".py")) for name in
                        ("review-evidence", "review-collect", "repair-proposal", "repair-apply")}
KINDS = {"Unverified", "UnknownError", "BusyError", "InputError", "ValueError",
         "TypeError", "KeyError", "OSError", "FileNotFoundError", "PermissionError",
          "TimeoutExpired", "JSONDecodeError", "AssertionError"}


@contextmanager
def compiled_installed_sources():
    """Test-process-only compile reuse; each import still reads and executes source.

    No module instances, file metadata, policy digests, task evidence or Git facts
    are cached. Compare actual bytes, not mtime/size: same-length edits must miss.
    Keep only the latest source per path/options and bound memory. Nothing is
    written to disk; the normal loader is restored even on an exception.
    """
    original = SourceFileLoader.source_to_code
    compiled = {}

    def source_to_code(loader, data, path, *, _optimize=-1):
        if Path(path).parent != BIN or len(data) > 1_000_000:
            return original(loader, data, path, _optimize=_optimize)
        key = (path, _optimize)
        previous = compiled.get(key)
        if previous is not None and previous[0] == data:
            return previous[1]
        code = original(loader, data, path, _optimize=_optimize)
        if key in compiled or len(compiled) < 32:
            compiled[key] = (bytes(data), code)
        return code

    SourceFileLoader.source_to_code = source_to_code
    try:
        yield
    finally:
        SourceFileLoader.source_to_code = original


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


@contextmanager
def exception_observer(capture):
    """Observe caught main exceptions, not every Python call/line on 3.12+.

    One private monitoring slot, no instruction/line instrumentation. Older
    interpreters or an occupied slot retain the original trace observation.
    Unexpected monitoring errors propagate; they must not silently lose evidence.
    """
    target = str(TARGET)
    monitoring = getattr(sys, "monitoring", None)
    tool = 5
    if monitoring is not None:
        try:
            monitoring.use_tool_id(tool, "foreground-fixture-diagnostic")
        except ValueError:
            monitoring = None  # Another observer owns the slot; never take it.
    if monitoring is not None:
        event = monitoring.events.EXCEPTION_HANDLED

        def handled(code, offset, exception):
            if code.co_filename == target and code.co_name == "main" and isinstance(exception, Exception):
                frame = sys._getframe(1)
                if frame.f_code is not code:
                    raise RuntimeError("diagnostic monitoring frame differs")
                capture(frame, exception, exception.__traceback__)

        try:
            monitoring.register_callback(tool, event, handled)
            monitoring.set_events(tool, event)
            yield "monitoring"
        finally:
            monitoring.set_events(tool, 0)
            monitoring.register_callback(tool, event, None)
            monitoring.free_tool_id(tool)
        return

    previous = sys.gettrace()

    def trace(frame, event, arg):
        if frame.f_code.co_filename != target or frame.f_code.co_name != "main":
            return None
        frame.f_trace_lines = False
        if event == "exception" and isinstance(arg[1], Exception):
            capture(frame, arg[1], arg[2])
        return trace

    sys.settrace(trace)
    try:
        yield "trace"
    finally:
        sys.settrace(previous)


def compile_only(argv):
    """Run one allowlisted domain CLI with compile reuse and no observer."""
    if len(argv) < 3 or argv[:2] != ["-I", "-B"] or argv[2] not in COMPILE_ONLY_TARGETS.values():
        raise SystemExit("compile-only launcher requires an allowlisted fixture CLI and exact -I -B flags")
    previous = sys.argv
    sys.argv = argv[2:]
    try:
        with compiled_installed_sources():
            # Let SystemExit (including None/string codes) propagate unchanged.
            runpy.run_path(sys.argv[0], run_name="__main__")
    finally:
        sys.argv = previous


def main():
    if sys.argv[1:2] == ["--compile-only"]:
        return compile_only(sys.argv[2:])
    expected = int(sys.argv[1])
    # The public shell entrypoint supplied these exact isolated Python arguments.
    if sys.argv[2:5] != ["-I", "-B", str(TARGET)]:
        raise SystemExit("diagnostic launcher only accepts the foreground fixture CLI")
    sys.argv = sys.argv[4:]
    captured = None

    def capture(frame, exception, traceback):
        nonlocal captured
        captured = summarize(exception, traceback)
        if "worker" in frame.f_locals and "live" in frame.f_locals:
            worker = frame.f_locals["worker"]
            if isinstance(worker, dict):
                captured["worker_observation"] = {
                    "alive": frame.f_locals["live"] == "alive",
                    "start_matches": frame.f_locals.get("start") == worker.get("process_start")}

    code = 0
    try:
        with exception_observer(capture), compiled_installed_sources():
            runpy.run_path(str(TARGET), run_name="__main__")
    except SystemExit as exc:
        code = exc.code if type(exc.code) is int else 1
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
