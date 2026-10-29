#!/usr/bin/env python3
"""Replay operator-captured normalized PR data in an isolated environment.

This makes no network calls and does not qualify live GitHub transport. Input
is a map of repositories to the exact normalized material PR fields captured by
the operator. A fresh private output directory is required.
"""

import argparse
import importlib.util
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(mode=0o700, exist_ok=False)
    path = Path(__file__).resolve().parents[1] / "bin" / "monitor-journal.py"
    spec = importlib.util.spec_from_file_location("journal", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    capture = json.loads(args.capture.read_bytes())
    results = {"repo:" + repo: {"status":"OBSERVED", "items":items, "digest":None, "reason":None} for repo,items in capture.items()}
    sources = list(results)
    config = module.fingerprint(sources)
    first = module.open_store(args.output, writable=True)
    seq = module.begin(first, "capture-first", config, "isolated-replay", sources, "capture-replay")
    result1 = module.finish(first, seq, results, "capture-replay")
    before = module.status(first, sources)
    first.close()
    second = module.open_store(args.output, writable=True)
    seq = module.begin(second, "capture-restarted", config, "isolated-replay", sources, "capture-replay")
    result2 = module.finish(second, seq, results, "capture-replay")
    after = module.status(second, sources)
    assert result2["status"] == "CURRENT" and result2["changes"] == []
    assert [item["reference"] for item in before["candidates"]] == [item["reference"] for item in after["candidates"]]
    second.close()
    outcome = {"qualification":"actual host-fetched material fields replayed offline; no live candidate transport", "first":result1,
               "restart":result2, "status":after, "stable_candidate_references":True}
    (args.output / "outcome.json").write_text(json.dumps(outcome, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"repositories":len(sources), "candidates":len(after["candidates"]), "restart":result2["status"], "stable_references":True}))


if __name__ == "__main__":
    main()
