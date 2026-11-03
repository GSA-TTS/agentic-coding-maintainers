#!/usr/bin/env python3
"""Bounded offline fixture timings/profile; run only in the approved sandbox.

Three fresh processes per case, alternating cases. A separate profile pass
instruments the parent and the same foreground diagnostic interpreter invocations,
never retries a request. Other CLI subprocesses are counted but not profiled.
No production code, state, Git facts or assertion results are cached.
"""

import argparse
import cProfile
import importlib.util
import json
import os
import pstats
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

TEST = Path(__file__).with_name("foreground-delivery-test.py")
CASES = ("test_admission_changed_binding_and_owner_session_refused",
         "test_admission_later_report_replay_uses_historical_context")


def profile_case(case):
    spec = importlib.util.spec_from_file_location("foreground_benchmark_fixture", TEST)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    original = subprocess.run
    commands = Counter()
    with tempfile.TemporaryDirectory(prefix="foreground-profile-") as temporary:
        directory, profiles = Path(temporary), []

        def run(args, *positional, **kwargs):
            commands[args[2] if len(args) > 2 and args[:2] == ["bash", str(fixture.ROOT / "run.sh")] else args[0]] += 1
            if len(args) > 2 and args[:3] == ["bash", str(fixture.ROOT / "run.sh"), "foreground-delivery"]:
                # cli() just wrote this private fixture shim. Only instrument its
                # interpreter, keeping run.sh, isolation flags and argv intact.
                shim = Path(kwargs["env"]["PATH"].split(os.pathsep)[0]) / "python3"
                source = shim.read_text()
                assert source.count(" -I -B ") == 1
                profile = directory / (str(len(profiles)) + ".prof")
                shim.write_text(source.replace(" -I -B ", " -I -B " + shlex.quote(__file__)
                                + " --profile-cli " + shlex.quote(str(profile)) + " ", 1))
                profiles.append(profile)
            return original(args, *positional, **kwargs)

        loader = unittest.TestLoader()
        loader.testNamePatterns = ["*" + case + "*"]
        parent = cProfile.Profile()
        with mock.patch.object(subprocess, "run", side_effect=run):
            parent.enable()
            try:
                result = unittest.TextTestRunner(verbosity=2).run(loader.loadTestsFromModule(fixture))
            finally:
                parent.disable()
        if not result.wasSuccessful() or not profiles:
            raise SystemExit("profile fixture failed or no CLI profiles captured")
        for scope, stats in (("parent", pstats.Stats(parent)),
                             ("foreground_children", pstats.Stats(*(str(path) for path in profiles)))):
            rows = []
            hottest = set(sorted(stats.stats, key=lambda key: -stats.stats[key][2])[:20])
            for (filename, line, function), (primitive, calls, own, cumulative, _) in stats.stats.items():
                if ((filename, line, function) in hottest or Path(filename).name in {"foreground-cli-diagnostic.py", "linecache.py"}
                        or function in {"<built-in method builtins.compile>", "source_to_code", "get_data",
                                        "exec_module", "_path_stat", "_path_isfile"}):
                    rows.append({"file": Path(filename).name, "line": line, "function": function,
                                 "calls": calls, "self_seconds": round(own, 6), "cumulative_seconds": round(cumulative, 6)})
            print(json.dumps({"scope": scope, "case": case, "tests_run": result.testsRun,
                              "commands": dict(commands), "profile_cli_count": len(profiles), "total_calls": stats.total_calls,
                              "linecache_calls": sum(value[1] for key, value in stats.stats.items()
                                                     if Path(key[0]).name == "linecache.py"),
                              "total_seconds": round(stats.total_tt, 6), "rows": sorted(rows, key=lambda r: -r["self_seconds"])}, sort_keys=True, indent=2), flush=True)


def main():
    if sys.argv[1:2] == ["--profile-cli"]:
        # cProfile's CLI swallows SystemExit. Preserve the real CLI exit instead.
        import cProfile
        import runpy
        output = sys.argv[2]
        sys.argv = sys.argv[3:]
        profiler = cProfile.Profile()
        profiler.enable()
        try:
            runpy.run_path(sys.argv[0], run_name="__main__")
        finally:
            profiler.disable()
            profiler.dump_stats(output)
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", action="store_true", help="separate parent/foreground-child profiles instead of timings")
    parser.add_argument("--case", action="append", help="exact test method (repeat for interleaved cases)")
    args = parser.parse_args()
    if args.profile:
        for case in args.case or [CASES[1]]:
            profile_case(case)
        return
    for sample in range(1, 4):
        for case in args.case or CASES:
            start = time.monotonic()
            process = subprocess.run([sys.executable, "-I", "-B", str(TEST), "-k", case, "-v"], timeout=120)
            elapsed = time.monotonic() - start
            print(json.dumps({"sample": sample, "case": case, "elapsed_seconds": round(elapsed, 6),
                              "returncode": process.returncode}), flush=True)
            if process.returncode:
                raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
