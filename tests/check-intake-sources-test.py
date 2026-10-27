"""Offline source registry fixtures; no GitHub call or source enumeration."""

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLI = ROOT / "scripts/check-intake-sources.py"
FIXTURE = pathlib.Path(tempfile.mkdtemp(prefix="intake-source-registry-"))
FIXTURE.chmod(0o700)
(FIXTURE / "MANIFEST.md").write_text(
    "Synthetic source registry for tests/check-intake-sources-test.py; no real requests. "
    "Safe for operator disposal; an interrupted test may leave partial synthetic data.\n", encoding="utf-8")
REGISTRY = FIXTURE / "sources.json"


def page(entry=None, exit_cursor=None, has_next=False, ids=None):
    return {"cursor_in": entry, "cursor_out": exit_cursor, "has_next": has_next,
            "request_ids": ids if ids is not None else []}


def source(name="issue-feed", coverage="complete", pages=None):
    return {"source_id": name, "source_type": "github_issues",
            "captured_at": "2026-10-27T00:00:00Z", "coverage": coverage,
            "pages": pages if pages is not None else [page(ids=["req-1"])]}


def sample(sources=None):
    return {"schema_version": 1, "window_start": "2026-10-01T00:00:00Z",
            "as_of": "2026-10-26T00:00:00Z",
            "sources": sources if sources is not None else [source()]}


def run(data, *, path=REGISTRY, required=None):
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
    path.chmod(0o600)
    pairs = required if required is not None else ["issue-feed:github_issues"]
    args = [sys.executable, "-I", "-B", str(CLI), "--registry", str(path)]
    for pair in pairs:
        args += ["--required-source", pair]
    return subprocess.run(args,
                          capture_output=True, check=False, timeout=5)


def report(data, status, exit_code, *, required=None):
    output = run(data, required=required)
    assert output.returncode == exit_code and not output.stderr, output.stderr
    value = json.loads(output.stdout)
    assert value["status"] == status and value["mode"] == "OFFLINE_SOURCE_EVIDENCE"
    assert "req-1" not in output.stdout.decode()
    assert "no live API" in value["limitation"]
    return value


def refuses(data, *, path=REGISTRY, required=None):
    output = run(data, path=path, required=required)
    assert output.returncode == 3 and b"UNVERIFIED" in output.stderr and not output.stdout, output


complete = report(sample(), "SUPPLIED_CHAIN_COHERENT", 0)
assert complete["source_count"] == 1 and complete["observed_request_count"] == 1
two_pages = report(sample(sources=[source(pages=[page(exit_cursor="cursor-1", has_next=True, ids=["req-1"]),
                                                  page(entry="cursor-1", ids=["req-2"])])]), "SUPPLIED_CHAIN_COHERENT", 0)
assert two_pages["observed_request_count"] == 2
partial = report(sample(sources=[source(coverage="partial")]), "UNVERIFIED", 3)
assert partial["incomplete_source_count"] == 1
missing = report(sample(), "UNVERIFIED", 3, required=["issue-feed:github_issues", "direct-feed:direct_requests"])
assert missing["source_count"] == 2 and missing["observed_source_count"] == 1
truncated = report(sample(sources=[source(pages=[page(exit_cursor="cursor-1", has_next=True)])]), "UNVERIFIED", 3)
assert truncated["incomplete_source_count"] == 1

refuses(sample(sources=[source(), source()]))
refuses(sample(sources=[source("rogue-feed")]))
refuses(sample(), required=["issue-feed:project_items"])
refuses(sample(), required=["issue-feed:github_issues", "issue-feed:github_issues"])
missing_even_when_capture_omits_it = report(sample(), "UNVERIFIED", 3,
                                            required=["issue-feed:github_issues", "direct-feed:direct_requests"])
assert missing_even_when_capture_omits_it["incomplete_source_count"] == 1
refuses(sample(sources=[source(pages=[page(ids=["req-1", "req-1"])])]))
refuses(sample(sources=[source(pages=[page(exit_cursor="cursor-1", has_next=True), page(entry="wrong")])]))
refuses(sample(sources=[source(pages=[page(exit_cursor="cursor-1", has_next=True),
                                     page(entry="cursor-1", exit_cursor="cursor-1", has_next=True)])]))
refuses(sample(sources=[source(pages=[page(exit_cursor="cursor-1", has_next=True),
                                     page(entry="cursor-1", exit_cursor="cursor-1", has_next=False)])]))
refuses(sample(sources=[source(pages=[])]))
refuses(sample(sources=[source(pages=[dict(page(), has_next="false")])]))
refuses(dict(sample(), schema_version=True))
refuses(sample(), required=[])
refuses(sample(sources=[dict(source(), captured_at="2020-01-01T00:00:00Z")]))
refuses(b'{"schema_version":1,"schema_version":1}')
refuses(b"x" * 65537)
LINK = FIXTURE / "linked.json"
LINK.symlink_to(REGISTRY)
refuses(sample(), path=LINK)
print("check-intake-sources tests: PASS")
print("intake_sources_fixture=" + str(FIXTURE), file=sys.stderr)
