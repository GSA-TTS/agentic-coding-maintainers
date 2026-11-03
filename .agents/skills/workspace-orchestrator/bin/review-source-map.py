#!/usr/bin/env python3
"""Pure, strict source provenance shared by materializer, runner and collector."""

import importlib.util
import json
import re
from pathlib import Path

spec = importlib.util.spec_from_file_location("review_handoff", Path(__file__).with_name("review-handoff.py"))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
MAX_BYTES = 200_000


def validate(value, manifest):
    h.fields(value, {"schema_version", "base", "head", "packet", "sources"})
    h.require(type(value["schema_version"]) is int and value["schema_version"] == 1, "invalid source-map version")
    h.require(len(h.canonical(value)) <= MAX_BYTES, "source map exceeds bound")
    for name in ("base", "head"):
        h.require(isinstance(value[name], str) and re.fullmatch(r"[0-9a-f]{40}", value[name]), "invalid comparison identity")
    h.hash_value(value["packet"])
    sources = value["sources"]
    h.require(isinstance(sources, list) and 1 <= len(sources) <= 20, "invalid source-map inventory")
    observed = {}
    for item in sources:
        h.fields(item, {"guest_path", "side", "path_base64", "sha256"})
        guest = h.guest_path(item["guest_path"])
        h.require(guest not in observed, "duplicate source-map destination")
        h.require(item["side"] in {"before", "after"}, "invalid source-map side")
        raw = h.encoded(item["path_base64"])
        h.require(raw and len(raw) <= 4096 and not raw.startswith(b"/") and b"\0" not in raw
                  and all(p not in {b"", b".", b"..", b".git"} for p in raw.split(b"/")), "invalid original path bytes")
        h.hash_value(item["sha256"])
        observed[guest] = item["sha256"]
    h.require(observed == manifest, "source map must match every actual source and hash")
    return value


def decode(raw, manifest):
    h.require(0 < len(raw) <= MAX_BYTES, "source map exceeds bound")
    value = json.loads(raw, object_pairs_hook=h.unique,
                       parse_constant=lambda _: h.require(False, "nonfinite source map"))
    validate(value, manifest)
    h.require(h.canonical(value) == raw, "source map must be canonical")
    return value


def project(base, head, packet, selections, manifest):
    value = {"schema_version": 1, "base": base, "head": head, "packet": packet, "sources": [
        {"guest_path": guest, "side": selection["side"], "path_base64": selection["path_base64"],
         "sha256": manifest[guest]} for guest, selection in sorted(selections.items())]}
    return validate(value, manifest)


def from_bundle(value):
    binding = value["binding"]
    return project(binding["base"], binding["head"], binding["packet"],
                   {s["guest_path"]: s for s in value["sources"]},
                   {s["guest_path"]: s["sha256"] for s in value["sources"]})


def from_admission(admitted):
    return project(admitted["base"], admitted["head"], admitted["packet"],
                   admitted["sources"], admitted["source_sha256"])
