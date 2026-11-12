#!/usr/bin/env python3
"""Bounded offline fixture timings/profile; run only in the approved sandbox.

Three fresh processes per case, alternating cases. A separate profile pass
instruments the parent and the same foreground/domain fixture interpreter invocations,
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
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

TEST = Path(__file__).with_name("foreground-delivery-test.py")
CASES = ("test_admission_changed_binding_and_owner_session_refused",
         "test_admission_later_report_replay_uses_historical_context")


def discover():
    spec = importlib.util.spec_from_file_location("foreground_benchmark_fixture", TEST)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    return fixture, unittest.TestLoader().loadTestsFromModule(fixture)


def resolve_case(suite, selector):
    """Resolve a full method name, retaining discovery's execution multiplicity."""
    def cases(items):
        for item in items:
            if isinstance(item, unittest.TestSuite):
                yield from cases(item)
            else:
                yield item

    matches = [test for test in cases(suite) if test._testMethodName == selector]
    if len(matches) != 1:
        raise ValueError(f"case must resolve to exactly one discovered test: {selector!r} ({len(matches)} matches)")
    return matches[0]


def run_selected(test):
    # Scenario output must not mix with the child measurement protocol.
    with redirect_stdout(sys.stderr):
        result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([test]))
    return {"tests_run": result.testsRun, "skipped": len(result.skipped),
            "successful": result.wasSuccessful() and not result.expectedFailures}


def measured_pass(report):
    return (type(report) is dict and type(report.get("tests_run")) is int
            and report["tests_run"] == 1 and type(report.get("skipped")) is int
            and report["skipped"] == 0 and report.get("successful") is True)


def profile_case(fixture, test, case):
    original = subprocess.run
    commands = Counter()
    with tempfile.TemporaryDirectory(prefix="foreground-profile-") as temporary:
        directory, profiles = Path(temporary), {}

        def run(args, *positional, **kwargs):
            commands[args[2] if len(args) > 2 and args[:2] == ["bash", str(fixture.ROOT / "run.sh")] else args[0]] += 1
            if (len(args) > 2 and args[:2] == ["bash", str(fixture.ROOT / "run.sh")]
                    and args[2] in {"foreground-delivery", *fixture.diagnostic.COMPILE_ONLY_TARGETS}):
                # cli() just wrote this private fixture shim. Only instrument its
                # interpreter, keeping run.sh, isolation flags and argv intact.
                shim = Path(kwargs["env"]["PATH"].split(os.pathsep)[0]) / "python3"
                source = shim.read_text()
                assert source.count(" -I -B ") == 1
                profile = directory / (str(len(profiles)) + ".prof")
                shim.write_text(source.replace(" -I -B ", " -I -B " + shlex.quote(__file__)
                                + " --profile-cli " + shlex.quote(str(profile)) + " ", 1))
                profiles[profile] = args[2]
            return original(args, *positional, **kwargs)

        parent = cProfile.Profile()
        with mock.patch.object(subprocess, "run", side_effect=run):
            parent.enable()
            try:
                report = run_selected(test)
            finally:
                parent.disable()
        if not measured_pass(report) or not profiles:
            print(json.dumps({"case": case, **report, "profile_cli_count": len(profiles)}), flush=True)
            raise SystemExit("profile fixture failed or no CLI profiles captured")
        scopes = [("parent", pstats.Stats(parent))]
        for command in sorted(set(profiles.values())):
            paths = [str(path) for path, name in profiles.items() if name == command]
            scope = "foreground_children" if command == "foreground-delivery" else command + "_children"
            scopes.append((scope, pstats.Stats(*paths)))
        for scope, stats in scopes:
            rows = []
            hottest = set(sorted(stats.stats, key=lambda key: -stats.stats[key][2])[:20])
            for (filename, line, function), (primitive, calls, own, cumulative, _) in stats.stats.items():
                if ((filename, line, function) in hottest or Path(filename).name in {"foreground-cli-diagnostic.py", "linecache.py"}
                        or function in {"<built-in method builtins.compile>", "source_to_code", "get_data",
                                        "exec_module", "_path_stat", "_path_isfile"}):
                    rows.append({"file": Path(filename).name, "line": line, "function": function,
                                 "calls": calls, "self_seconds": round(own, 6), "cumulative_seconds": round(cumulative, 6)})
            print(json.dumps({"scope": scope, "case": case, **report,
                              "commands": dict(commands), "profile_cli_count": len(profiles),
                              "profile_commands": dict(Counter(profiles.values())), "total_calls": stats.total_calls,
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
    parser.add_argument("--profile", action="store_true", help="separate parent/foreground/domain-child profiles instead of timings")
    parser.add_argument("--case", action="append", help="exact test method (repeat for interleaved cases)")
    parser.add_argument("--time-case", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.time_case is not None and (args.profile or args.case):
        parser.error("--time-case cannot be combined with --case or --profile")
    fixture, suite = discover()
    selectors = ([args.time_case] if args.time_case is not None
                 else args.case or ([CASES[1]] if args.profile else CASES))
    try:
        selected = [resolve_case(suite, case) for case in selectors]
    except ValueError as exc:
        parser.error(str(exc))
    if args.time_case is not None:
        report = run_selected(selected[0])
        print(json.dumps(report), flush=True)
        raise SystemExit(0 if measured_pass(report) else 1)
    if args.profile:
        for case, test in zip(selectors, selected):
            profile_case(fixture, test, case)
        return
    for sample in range(1, 4):
        for case in selectors:
            start = time.monotonic()
            process = subprocess.run([sys.executable, "-I", "-B", __file__, "--time-case", case],
                                     stdout=subprocess.PIPE, text=True, timeout=120)
            elapsed = time.monotonic() - start
            try:
                report = json.loads(process.stdout)
            except (ValueError, TypeError):
                raise SystemExit("timing child returned no valid measurement")
            print(json.dumps({"sample": sample, "case": case, "elapsed_seconds": round(elapsed, 6),
                              "returncode": process.returncode, "measurement": report}), flush=True)
            if process.returncode or not measured_pass(report):
                raise SystemExit(process.returncode or 1)


if __name__ == "__main__":
    main()
