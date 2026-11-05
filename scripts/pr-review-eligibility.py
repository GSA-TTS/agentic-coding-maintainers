#!/usr/bin/env python3
"""Offline, advisory classification of operator-supplied PR observations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, NoReturn, TypedDict

MAX_BYTES = 65536
MAX_DEPTH = 16
MAX_RULES = 32
MAX_ID = 9007199254740991
MAX_AGE = 3600
MAX_POLICY_LIFETIME = 30 * 86400
Status = Literal["ELIGIBLE", "WAIT", "EXCLUDED", "DEFERRED"]
EXIT_CODES = {"ELIGIBLE": 0, "WAIT": 1, "EXCLUDED": 2, "DEFERRED": 3}
REASONS = {
    "ORDINARY_USER": "Open, non-draft PR has a validated User identity.",
    "DRAFT": "Draft PR must be observed again after it becomes ready.",
    "CLOSED": "PR is closed; no review candidate remains.",
    "RELEASE_AUTOMATION": "All supplied trusted release-automation rule fields match.",
    "BOT_UNCONFIGURED": "No rule matches the exact Bot ID, login and type.",
    "AUTOMATION_MISMATCH": "Configured Bot does not match the full release rule.",
    "AUTHOR_TYPE_UNSUPPORTED": "Author type is not User or Bot.",
    "AUTHOR_IDENTITY_CONFLICT": "User identity conflicts with a Bot login or configured Bot identity.",
    "METADATA_INVALID": "Normalized PR metadata is missing or malformed.",
    "POLICY_INVALID": "Operator policy is missing, malformed or ambiguous.",
    "REPOSITORY_MISMATCH": "PR base repository does not match the policy repository.",
    "POLICY_FUTURE": "Policy issuance is after evaluation time.",
    "POLICY_EXPIRED": "Policy has expired.",
    "OBSERVATION_FUTURE": "Observation is after evaluation time.",
    "OBSERVATION_EXPIRED": "Observation expired or exceeds policy maximum age.",
    "TIME_INVALID": "Evaluation time is malformed.",
    "INPUT_UNAVAILABLE": "Input could not be read as a bounded regular file.",
    "JSON_INVALID": "Input is not bounded, strict UTF-8 JSON.",
    "ARGUMENTS_INVALID": "CLI arguments are invalid or incomplete.",
    "UNSAFE_RUNTIME": "Run the CLI with python3 -I -B.",
}


class Result(TypedDict):
    schema_version: int
    status: Status
    reason: str
    authority: str


class Invalid(Exception):
    """Only fixed reason codes, never input text, cross this boundary."""


def result(status: Status, reason: str) -> Result:
    return {"schema_version": 1, "status": status, "reason": reason,
            "authority": "ADVISORY_ONLY"}


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise Invalid(reason)


def fields(value: Any, names: str, reason: str) -> dict[str, Any]:
    require(type(value) is dict and set(value) == set(names.split()), reason)
    return value


def integer(value: Any, maximum: int = MAX_ID) -> bool:
    return type(value) is int and 1 <= value <= maximum


def matches(value: Any, pattern: str) -> bool:
    return type(value) is str and re.fullmatch(pattern, value, flags=re.ASCII) is not None


def utc(value: Any, reason: str) -> datetime:
    require(matches(value, r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"), reason)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Invalid(reason) from exc


def ref(value: Any) -> bool:
    if not matches(value, r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}"):
        return False
    return all(part and not part.startswith(".") and not part.endswith((".", ".lock"))
               and ".." not in part for part in value.split("/"))


def config_path(value: Any) -> bool:
    return (matches(value, r"[A-Za-z0-9_.-][A-Za-z0-9_./-]{0,199}")
            and all(part not in ("", ".", "..") for part in value.split("/")))


def actor(value: Any, reason: str) -> dict[str, Any]:
    value = fields(value, "id login type", reason)
    require(integer(value["id"]) and matches(value["login"], r"[A-Za-z0-9-]{1,100}(?:\[bot\])?")
            and matches(value["type"], r"[A-Za-z]{1,32}"), reason)
    return value


def policy_data(value: Any) -> dict[str, Any]:
    reason = "POLICY_INVALID"
    value = fields(value, "schema_version repository_id issued_at expires_at max_observation_age_seconds release_automation", reason)
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and integer(value["repository_id"])
            and integer(value["max_observation_age_seconds"], MAX_AGE), reason)
    issued, expires = utc(value["issued_at"], reason), utc(value["expires_at"], reason)
    require(0 < (expires - issued).total_seconds() <= MAX_POLICY_LIFETIME, reason)
    rules = value["release_automation"]
    require(type(rules) is list and len(rules) <= MAX_RULES, reason)
    seen: set[tuple[Any, ...]] = set()
    identities: dict[int, tuple[str, str]] = {}
    logins: dict[str, int] = {}
    for rule in rules:
        rule = fields(rule, "actor head_ref base_ref config_path config_sha256", reason)
        who = actor(rule["actor"], reason)
        require(who["type"] == "Bot" and ref(rule["head_ref"]) and ref(rule["base_ref"])
                and config_path(rule["config_path"])
                and matches(rule["config_sha256"], r"[0-9a-f]{64}"), reason)
        identity = (who["login"], who["type"])
        require(identities.get(who["id"], identity) == identity
                and logins.get(who["login"], who["id"]) == who["id"], reason)
        identities[who["id"]], logins[who["login"]] = identity, who["id"]
        key = (who["id"], rule["head_ref"], rule["base_ref"])
        require(key not in seen, reason)
        seen.add(key)
    return value


def metadata_data(value: Any) -> dict[str, Any]:
    reason = "METADATA_INVALID"
    value = fields(value, "schema_version repository_id number state draft author head base provenance base_config", reason)
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and integer(value["repository_id"]) and integer(value["number"])
            and type(value["state"]) is str and value["state"] in ("open", "closed")
            and type(value["draft"]) is bool, reason)
    actor(value["author"], reason)
    for name in ("head", "base"):
        branch = fields(value[name], "repository_id ref sha", reason)
        require(integer(branch["repository_id"]) and ref(branch["ref"])
                and matches(branch["sha"], r"[0-9a-f]{40}"), reason)
    require(value["base"]["repository_id"] == value["repository_id"], reason)
    provenance = fields(value["provenance"], "source observed_at expires_at", reason)
    require(provenance["source"] == "github_pull_request", reason)
    observed = utc(provenance["observed_at"], reason)
    expires = utc(provenance["expires_at"], reason)
    require(0 < (expires - observed).total_seconds() <= MAX_AGE, reason)
    config = value["base_config"]
    if config is not None:
        config = fields(config, "base_sha path sha256", reason)
        require(matches(config["base_sha"], r"[0-9a-f]{40}")
                and config["base_sha"] == value["base"]["sha"]
                and config_path(config["path"]) and matches(config["sha256"], r"[0-9a-f]{64}"), reason)
    return value


def classify(metadata: Any, policy: Any, *, now: str) -> Result:
    """Pure classifier; supplied provenance/policy are assertions, not attestations."""
    try:
        instant = utc(now, "TIME_INVALID")
        p = policy_data(policy)
        m = metadata_data(metadata)
        require(m["repository_id"] == p["repository_id"], "REPOSITORY_MISMATCH")
        require(utc(p["issued_at"], "POLICY_INVALID") <= instant, "POLICY_FUTURE")
        require(instant < utc(p["expires_at"], "POLICY_INVALID"), "POLICY_EXPIRED")
        provenance = m["provenance"]
        observed = utc(provenance["observed_at"], "METADATA_INVALID")
        require(observed <= instant, "OBSERVATION_FUTURE")
        require(instant < utc(provenance["expires_at"], "METADATA_INVALID")
                and (instant - observed).total_seconds() < p["max_observation_age_seconds"],
                "OBSERVATION_EXPIRED")
        if m["state"] == "closed":
            return result("EXCLUDED", "CLOSED")
        if m["draft"]:
            return result("WAIT", "DRAFT")
        who = m["author"]
        if who["type"] == "User":
            if (who["login"].endswith("[bot]") or any(
                    rule["actor"]["id"] == who["id"] or rule["actor"]["login"] == who["login"]
                    for rule in p["release_automation"])):
                return result("DEFERRED", "AUTHOR_IDENTITY_CONFLICT")
            return result("ELIGIBLE", "ORDINARY_USER")
        if who["type"] != "Bot":
            return result("DEFERRED", "AUTHOR_TYPE_UNSUPPORTED")
        rules = [rule for rule in p["release_automation"] if rule["actor"] == who]
        if not rules:
            return result("DEFERRED", "BOT_UNCONFIGURED")
        config = m["base_config"]
        for rule in rules:
            if (m["head"]["repository_id"] == m["repository_id"]
                    and m["head"]["ref"] == rule["head_ref"]
                    and m["base"]["ref"] == rule["base_ref"] and config is not None
                    and config["path"] == rule["config_path"]
                    and config["sha256"] == rule["config_sha256"]):
                return result("EXCLUDED", "RELEASE_AUTOMATION")
        return result("DEFERRED", "AUTOMATION_MISMATCH")
    except Invalid as exc:
        return result("DEFERRED", str(exc))


def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in out, "JSON_INVALID")
        out[key] = value
    return out


def reject_number(value: str) -> Any:
    raise Invalid("JSON_INVALID")


def parse_integer(value: str) -> int:
    require(len(value.lstrip("-")) <= 16, "JSON_INVALID")
    return int(value)


def parse_json(raw: bytes) -> Any:
    require(0 < len(raw) <= MAX_BYTES, "JSON_INVALID")
    # Bound nesting before invoking the recursive stdlib parser. String contents
    # never count as delimiters; json.loads still checks all JSON syntax.
    depth, quoted, escaped = 0, False, False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == 92:
                escaped = True
            elif char == 34:
                quoted = False
        elif char == 34:
            quoted = True
        elif char in (91, 123):
            depth += 1
            require(depth <= MAX_DEPTH, "JSON_INVALID")
        elif char in (93, 125):
            depth -= 1
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields,
                          parse_int=parse_integer, parse_float=reject_number,
                          parse_constant=reject_number)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Invalid("JSON_INVALID") from exc


def read_input(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_BYTES, "INPUT_UNAVAILABLE")
            with os.fdopen(fd, "rb") as stream:
                fd = -1
                raw = stream.read(MAX_BYTES + 1)
            require(0 < len(raw) <= MAX_BYTES, "INPUT_UNAVAILABLE")
            return raw
        finally:
            if fd >= 0:
                os.close(fd)
    except (OSError, ValueError) as exc:
        raise Invalid("INPUT_UNAVAILABLE") from exc


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise Invalid("ARGUMENTS_INVALID")


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--as-of", help="UTC evaluation time; default: current UTC")
    parser.add_argument("--explain", action="store_true", help="include a fixed reason explanation")
    parser.add_argument("--audit", action="store_true", help="include input byte hashes and evaluation time")
    output: dict[str, Any]
    try:
        require(bool(sys.flags.isolated and sys.dont_write_bytecode), "UNSAFE_RUNTIME")
        args = parser.parse_args(argv)
        now = args.as_of if args.as_of is not None else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        utc(now, "TIME_INVALID")
        metadata, policy = read_input(args.metadata), read_input(args.policy)
        decision = classify(parse_json(metadata), parse_json(policy), now=now)
        output = dict(decision)
        if args.explain:
            output["explanation"] = REASONS[decision["reason"]]
        if args.audit:
            output["audit"] = {"as_of": now, "metadata_sha256": hashlib.sha256(metadata).hexdigest(),
                               "policy_sha256": hashlib.sha256(policy).hexdigest(),
                               "coverage": "SUPPLIED_INPUTS_ONLY"}
    except Invalid as exc:
        output = dict(result("DEFERRED", str(exc)))
    print(json.dumps(output, sort_keys=True, ensure_ascii=True))
    return EXIT_CODES[output["status"]]


if __name__ == "__main__":
    sys.exit(main())
