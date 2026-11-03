#!/usr/bin/env python3
"""Bounded offline fixture timings/profile; run only in the approved sandbox.

Three fresh processes per case, alternating cases. A separate profile pass
instruments the same diagnostic interpreter invocation, never retries a request.
No production code, state, Git facts or assertion results are cached.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import pstats
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TEST = Path(__file__).with_name("foreground-delivery-test.py")
CASES = ("test_admission_changed_binding_and_owner_session_refused",
         "test_admission_later_report_replay_uses_historical_context")


def profile_case():
    spec = importlib.util.spec_from_file_location("foreground_benchmark_fixture", TEST)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    original = subprocess.run
    with tempfile.TemporaryDirectory(prefix="foreground-profile-") as temporary:
        directory, profiles = Path(temporary), []

        def run(args, *positional, **kwargs):
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
        loader.testNamePatterns = ["*" + CASES[1] + "*"]
        with mock.patch.object(subprocess, "run", side_effect=run):
            result = unittest.TextTestRunner(verbosity=2).run(loader.loadTestsFromModule(fixture))
        if not result.wasSuccessful() or not profiles:
            raise SystemExit("profile fixture failed or no CLI profiles captured")
        stats = pstats.Stats(*(str(path) for path in profiles))
        rows = []
        for (filename, line, function), (primitive, calls, own, cumulative, _) in stats.stats.items():
            if (Path(filename).name == "foreground-cli-diagnostic.py"
                    or function in {"<built-in method builtins.compile>", "source_to_code", "_path_stat", "_path_isfile"}):
                rows.append({"file": Path(filename).name, "line": line, "function": function,
                             "calls": calls, "self_seconds": round(own, 6), "cumulative_seconds": round(cumulative, 6)})
        print(json.dumps({"profile_cli_count": len(profiles), "total_calls": stats.total_calls,
                          "total_seconds": round(stats.total_tt, 6), "rows": sorted(rows, key=lambda r: -r["self_seconds"])}, sort_keys=True))


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
    parser.add_argument("--profile", action="store_true", help="one separate profiled replay case instead of timings")
    args = parser.parse_args()
    if args.profile:
        profile_case()
        return
    for sample in range(1, 4):
        for case in CASES:
            start = time.monotonic()
            process = subprocess.run([sys.executable, "-I", "-B", str(TEST), "-k", case, "-v"], timeout=120)
            elapsed = time.monotonic() - start
            print(json.dumps({"sample": sample, "case": case, "elapsed_seconds": round(elapsed, 6),
                              "returncode": process.returncode}), flush=True)
            if process.returncode:
                raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
