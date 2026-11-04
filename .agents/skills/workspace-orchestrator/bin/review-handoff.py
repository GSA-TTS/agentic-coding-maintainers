#!/usr/bin/env python3
"""Strict, bounded selected-source transport. Export is a lock-held read only.

The guest validator is pure: no Git, subprocess, network, or candidate imports.
Only export_admitted imports controller dependencies, after foreground validation.
"""

import base64
import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path, PurePosixPath

MAX_BUNDLE = 8_000_000
MAX_CONTEXT = 50_000
BASELINE = {"correctness", "acceptance", "test-adequacy", "maintainability", "baseline-security"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fields(value, names):
    require(isinstance(value, dict) and set(value) == set(names), "unexpected or missing fields")


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("ascii")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def decode(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_BUNDLE, "bundle byte bound exceeded")
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: require(False, "nonfinite JSON"))
    validate(value)
    return value


def text(value, maximum=2000):
    require(isinstance(value, str) and value.strip() and len(value) <= maximum
            and not any(ord(c) < 32 and c not in "\n\t\r" for c in value), "invalid bounded text")


def token(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value), "invalid token")


def hash_value(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "invalid SHA256")


def number(value, minimum=0):
    require(type(value) is int and minimum <= value < 2**53, "invalid integer")


def encoded(value):
    require(isinstance(value, str), "base64 string required")
    raw = base64.b64decode(value, validate=True)
    require(base64.b64encode(raw).decode("ascii") == value, "noncanonical base64")
    return raw


def guest_path(value):
    require(isinstance(value, str) and len(value) <= 1024, "invalid source destination")
    path = PurePosixPath(value)
    require(str(path) == value and value.startswith("/candidate/") and ".." not in path.parts
            and len(path.parts) <= 32 and all(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", p)
            and p not in {".", "..", ".git"} and not discovery_name(p)
            for p in path.parts[2:]), "unexportable source destination")
    return value


def discovery_name(component):
    """Bounded layout denial, not an assertion that runtime discovery is disabled."""
    name = component.casefold()
    return (name in {".git", ".agent", "agent.md", "gemini.md", ".gemini", ".cursor", ".cursorrules",
                     ".github", ".mcp.json", "mcp.json"}
            or name.startswith((".opencode", ".agents", ".claude"))
            or any(name == stem or name.startswith(stem + ".") for stem in ("opencode", "agents", "claude")))


def obligations(value):
    require(isinstance(value, list) and 5 <= len(value) <= 32, "invalid obligations")
    for item in value:
        token(item)
    require(len(set(value)) == len(value) and BASELINE <= set(value), "missing or duplicate obligations")


def context(value):
    fields(value, {"acceptance_criteria", "obligations", "finding_history"})
    require(len(canonical(value)) <= MAX_CONTEXT, "context exceeds bound; no truncation")
    criteria = value["acceptance_criteria"]
    require(isinstance(criteria, list) and 1 <= len(criteria) <= 100, "invalid acceptance criteria")
    for criterion in criteria:
        text(criterion)
    obligations(value["obligations"])
    history = value["finding_history"]
    require(isinstance(history, dict) and len(history) <= 800, "invalid finding history")
    for key, item in history.items():
        token(key)
        fields(item, {"finding", "generation", "run_id", "dispositions"})
        number(item["generation"], 1)
        token(item["run_id"])
        finding = item["finding"]
        fields(finding, {"id", "invariant", "trigger", "path", "impact", "evidence"})
        require(finding["id"] == key, "finding identity differs")
        for name in ("invariant", "trigger", "path", "impact", "evidence"):
            text(finding[name])
        require(isinstance(item["dispositions"], list) and len(item["dispositions"]) <= 800,
                "invalid disposition history")
        for disposition in item["dispositions"]:
            fields(disposition, {"finding_id", "resolution", "counterevidence", "generation", "run_id"})
            require(disposition["finding_id"] == key and disposition["resolution"] in {"fixed", "refuted", "persists"},
                    "invalid disposition")
            text(disposition["counterevidence"])
            number(disposition["generation"], 1)
            token(disposition["run_id"])


def validate(value):
    fields(value, {"schema_version", "kind", "binding", "runtime", "context", "context_sha256", "sources"})
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and value["kind"] == "admitted-review-handoff", "unsupported handoff")
    require(len(canonical(value)) <= MAX_BUNDLE, "bundle byte bound exceeded")
    binding = value["binding"]
    fields(binding, {"task_id", "incarnation", "export_revision", "admission_revision", "admission_id",
                     "admit_operation_id", "generation", "material_epoch", "base", "head", "packet", "policy"})
    for name in ("task_id", "admit_operation_id"):
        token(binding[name])
    for name in ("incarnation", "admission_id", "packet", "policy"):
        hash_value(binding[name])
    for name in ("export_revision", "admission_revision", "material_epoch"):
        number(binding[name])
    number(binding["generation"], 1)
    require(binding["admission_revision"] < binding["export_revision"], "admission revision unavailable")
    for name in ("base", "head"):
        require(isinstance(binding[name], str) and re.fullmatch(r"[0-9a-f]{40}", binding[name]), "invalid commit")
    runtime = value["runtime"]
    fields(runtime, {"run_id", "reviewer", "session", "profile_sha256", "binary_sha256", "model", "agent", "cwd"})
    for name in ("run_id", "reviewer", "agent"):
        token(runtime[name])
    text(runtime["session"], 256)
    require(re.fullmatch(r"ses_[A-Za-z0-9_-]{1,100}", runtime["session"]), "unexportable runner session")
    text(runtime["model"], 200)
    for name in ("profile_sha256", "binary_sha256"):
        hash_value(runtime[name])
    require(runtime["cwd"] in {"/candidate", "/review"}, "unexportable admitted cwd")
    context(value["context"])
    hash_value(value["context_sha256"])
    require(digest(canonical(value["context"])) == value["context_sha256"], "context hash differs")
    sources = value["sources"]
    require(isinstance(sources, list) and 1 <= len(sources) <= 20, "one to twenty sources required")
    destinations = set()
    for source in sources:
        fields(source, {"guest_path", "path_base64", "side", "bytes", "sha256", "content_base64"})
        dest = guest_path(source["guest_path"])
        require(dest not in destinations, "duplicate destination")
        destinations.add(dest)
        path = encoded(source["path_base64"])
        require(path and len(path) <= 4096 and not path.startswith(b"/") and b"\0" not in path
                and all(p not in {b"", b".", b"..", b".git"} for p in path.split(b"/")), "invalid packet path")
        require(source["side"] in {"before", "after"}, "invalid selected side")
        raw = encoded(source["content_base64"])
        number(source["bytes"])
        hash_value(source["sha256"])
        require(len(raw) == source["bytes"] and digest(raw) == source["sha256"], "source bytes differ")
    require(not any(str(parent) in destinations for dest in destinations
                    for parent in PurePosixPath(dest).parents), "source file/directory collision")
    return value


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def export_admitted(record, request, root):
    """Caller validates retained state, revision, live worker and holds coordinator lock."""
    e, c, review = load("review-evidence"), load("review-collect"), load("foreground-review")
    key = request["payload"]["admission_id"]
    receipts = record["foreground_control"]["receipts"]
    matches = [r for r in receipts.values() if r["request"]["action"] == "admit-prepared-review"
               and r["result"]["domain_result"]["admission_id"] == key]
    require(len(matches) == 1, "exact foreground prepared admission required")
    receipt = matches[0]
    prepare, generation, payload = e.prepared_admission(record, receipt["request"])
    require(e.current(record) == generation, "admission generation superseded")
    review.fresh_guard(record, prepare["request"], root, generation["number"])
    retained = record["runtime_collections"]
    admitted = retained["admissions"][key]
    require(key not in retained["collections"] and admitted["run_id"] not in generation["reports"],
            "attempt already collected or reported")
    packet = review.read_packet(root, generation["packet"])
    historical = {**record, "revision": admitted["admission_revision"]}
    require(c.admission(historical, payload, c.canonical(packet), e) == admitted
            and c.digest(c.canonical(admitted)) == key, "exact admitted context differs")
    lookup = {entry["path_base64"]: entry for entry in packet["files"]}
    sources = []
    for guest, selection in sorted(admitted["sources"].items()):
        side = lookup[selection["path_base64"]][selection["side"]]
        require(side["kind"] == "blob" and side["mode"] in {"100644", "100755"}, "regular packet blob required")
        raw = side["content"].encode("utf-8") if side["encoding"] == "utf-8" else encoded(side["content"])
        require(digest(raw) == admitted["source_sha256"][guest] == side["sha256"]
                and len(raw) == side["bytes"], "admitted source differs")
        sources.append({"guest_path": guest, "path_base64": selection["path_base64"], "side": selection["side"],
                        "bytes": len(raw), "sha256": digest(raw), "content_base64": base64.b64encode(raw).decode("ascii")})
    binding = {name: admitted[name] for name in ("task_id", "admission_revision", "generation", "material_epoch", "base", "head", "packet", "policy")}
    binding.update(incarnation=request["incarnation"], export_revision=record["revision"], admission_id=key,
                   admit_operation_id=receipt["request"]["operation_id"])
    runtime = {name: admitted[name] for name in ("run_id", "binary_sha256", "model", "agent", "cwd")}
    runtime.update({name: admitted["assignment"][name] for name in ("reviewer", "session")})
    runtime["profile_sha256"] = admitted["assignment"]["profile"]
    value = {"schema_version": 1, "kind": "admitted-review-handoff", "binding": binding, "runtime": runtime,
             "context": copy.deepcopy(admitted["context"]), "context_sha256": digest(canonical(admitted["context"])), "sources": sources}
    validate(value)
    # Recheck source/owner/scope after construction, while the caller still holds the lock.
    review.fresh_guard(record, prepare["request"], root, generation["number"])
    return {"status": "REVIEW_HANDOFF_EXPORTED", "bundle": value, "bundle_sha256": digest(canonical(value)),
            "candidate_ready": False, "execution_credit": False, "delivery_credit": False}
