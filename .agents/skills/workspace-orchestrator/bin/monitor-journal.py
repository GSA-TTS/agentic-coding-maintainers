#!/usr/bin/env python3
"""Private durable observations, not task admission or GitHub effect authority."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_POLLS = 10_000
MAX_EVENTS = 50_000
MAX_CANDIDATES = 10_000
MAX_DB = 64_000_000
SOURCE = re.compile(r"^(?:repo:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|project:[A-Za-z0-9_.-]+/[1-9][0-9]*)$")
TABLES = {"meta", "polls", "sources", "coverage", "events", "candidates"}
MAX_CLAIM_INTENTS = 1000
MAX_INTENT_BYTES = 16_384
MAX_CLAIM_OBSERVATIONS = 1000
OBSERVATION_COLUMNS = [("observation_id", "TEXT", 1, None, 1),
                       ("operation_id", "TEXT", 1, None, 0),
                       ("request_sha256", "TEXT", 1, None, 0),
                       ("receipt", "TEXT", 1, None, 0),
                       ("receipt_sha256", "TEXT", 1, None, 0)]


class StoreConnection(sqlite3.Connection):
    """Retain the physical file identity selected when SQLite opened the store."""

    file_identity: tuple[int, int]


class JournalError(Exception):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def check_path(root: Path) -> Path:
    for part in (root, *root.parents):
        if part.is_symlink():
            raise JournalError("journal path contains symlink")
    if not root.is_dir() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise JournalError("journal directory must be private and current-user owned")
    path = root / "history.sqlite3"
    for name in (path, Path(str(path) + "-journal"), Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if name.exists() or name.is_symlink():
            info = name.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > MAX_DB:
                raise JournalError("journal or sidecar is unsafe or oversized")
    return path


def open_store(root: Path, writable: bool = False) -> sqlite3.Connection:
    path = check_path(root)
    existed = path.exists()
    if not existed and not writable:
        raise JournalError("no durable observation history")
    if not existed:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or info.st_mode & 0o077 or info.st_size > MAX_DB):
            raise JournalError("unsafe selected database")
        identity = (info.st_dev, info.st_ino)
        connection = sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro"),
                                     uri=True, timeout=2, factory=StoreConnection)
        selected = path.lstat()
        if identity != (selected.st_dev, selected.st_ino):
            connection.close()
            raise JournalError("database identity changed during open")
        connection.file_identity = identity
    finally:
        os.close(fd)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA foreign_keys=ON")
        if writable:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            # Bound actual database growth, not only record counts.
            size = connection.execute("PRAGMA page_size").fetchone()[0]
            connection.execute(f"PRAGMA max_page_count={MAX_DB // size}")
        else:
            connection.execute("PRAGMA query_only=ON")
        if not existed:
            with connection:
                connection.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE meta (version INTEGER NOT NULL, store_id TEXT NOT NULL);
                    CREATE TABLE polls (seq INTEGER PRIMARY KEY, attempt TEXT UNIQUE NOT NULL,
                      config TEXT NOT NULL, task TEXT NOT NULL, started TEXT NOT NULL, finished TEXT,
                      status TEXT NOT NULL, digest TEXT, response TEXT);
                    CREATE TABLE sources (source TEXT PRIMARY KEY, applied_seq INTEGER NOT NULL);
                    CREATE TABLE coverage (seq INTEGER NOT NULL REFERENCES polls(seq), source TEXT NOT NULL,
                      status TEXT NOT NULL, count INTEGER, digest TEXT, reason TEXT,
                      PRIMARY KEY(seq,source));
                    CREATE TABLE events (id INTEGER PRIMARY KEY, repo TEXT NOT NULL, number INTEGER NOT NULL,
                      generation INTEGER NOT NULL, seq INTEGER NOT NULL REFERENCES polls(seq),
                      payload TEXT NOT NULL, fingerprint TEXT NOT NULL, UNIQUE(repo,number,generation));
                    CREATE TABLE candidates (repo TEXT NOT NULL, number INTEGER NOT NULL,
                      event_id INTEGER NOT NULL REFERENCES events(id), first_seq INTEGER NOT NULL REFERENCES polls(seq),
                      last_seen_seq INTEGER NOT NULL REFERENCES polls(seq), PRIMARY KEY(repo,number));
                """)
                connection.execute("INSERT INTO meta VALUES (1, ?)", (uuid.uuid4().hex,))
            fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        connection.execute("BEGIN")
        try:
            validate_store(connection)
        finally:
            connection.rollback()
        selected = check_path(root).lstat()
        if connection.file_identity != (selected.st_dev, selected.st_ino):
            raise JournalError("database identity changed during validation")
        return connection
    except Exception:
        connection.close()
        raise


def validate_store(db: sqlite3.Connection) -> None:
    objects = db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    names = {row["name"] for row in objects}
    versions = {1: TABLES, 2: TABLES | {"binding_acks"},
                3: TABLES | {"binding_acks", "claim_intents"},
                4: TABLES | {"binding_acks", "claim_intents", "claim_observations"},
                5: TABLES | {"binding_acks", "claim_intents", "claim_observations"}}
    if names not in versions.values() or any(row["type"] != "table" for row in objects):
        raise JournalError("unsupported journal schema")
    meta = db.execute("SELECT * FROM meta").fetchall()
    if (len(meta) != 1 or type(meta[0]["version"]) is not int or meta[0]["version"] not in versions
            or not isinstance(meta[0]["store_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", meta[0]["store_id"])
            or names != versions[meta[0]["version"]]):
        raise JournalError("unsupported journal version/identity")
    if "binding_acks" in names:
        columns = [row[1] for row in db.execute("PRAGMA table_info(binding_acks)")]
        if columns != ["incarnation","task_id","operation_id","receipt","receipt_sha256"]:
            raise JournalError("unsupported acknowledgment schema")
        if db.execute("SELECT count(*) FROM binding_acks").fetchone()[0] > 10_000:
            raise JournalError("acknowledgment capacity exceeded")
    if "claim_intents" in names:
        columns = [tuple(row)[1:6] for row in db.execute("PRAGMA table_info(claim_intents)")]
        if columns != [("operation_id", "TEXT", 1, None, 1), ("request", "TEXT", 1, None, 0),
                       ("request_sha256", "TEXT", 1, None, 0)]:
            raise JournalError("unsupported claim intent schema")
        if db.execute("SELECT count(*) FROM claim_intents").fetchone()[0] > MAX_CLAIM_INTENTS:
            raise JournalError("claim intent capacity exceeded")
        seen = set()
        for row in db.execute("SELECT * FROM claim_intents"):
            request = decode_intent(row["request"])
            validate_claim_intent(request)
            if request["schema_version"] == 2 and meta[0]["version"] != 5:
                raise JournalError("identity-bound intent requires journal version 5")
            if (row["operation_id"] != request["operation_id"] or row["operation_id"] in seen
                    or request["store_id"] != meta[0]["store_id"]
                    or row["request_sha256"] != fingerprint(request)):
                raise JournalError("claim intent identity differs")
            seen.add(row["operation_id"])
    if "claim_observations" in names:
        columns = [tuple(row)[1:6] for row in db.execute("PRAGMA table_info(claim_observations)")]
        if columns != OBSERVATION_COLUMNS:
            raise JournalError("unsupported claim observation schema")
        foreign = [tuple(row)[2:5] for row in db.execute("PRAGMA foreign_key_list(claim_observations)")]
        if foreign != [("claim_intents", "operation_id", "operation_id")]:
            raise JournalError("unsupported claim observation reference")
        if db.execute("SELECT count(*) FROM claim_observations").fetchone()[0] > MAX_CLAIM_OBSERVATIONS:
            raise JournalError("claim observation capacity exceeded")
        for row in db.execute("SELECT * FROM claim_observations"):
            receipt = decode_intent(row["receipt"])
            validate_claim_observation(db, receipt)
            if (row["observation_id"] != receipt["observation_id"]
                    or row["operation_id"] != receipt["operation_id"]
                    or row["request_sha256"] != receipt["intent_request_sha256"]
                    or row["receipt_sha256"] != fingerprint(receipt)):
                raise JournalError("claim observation identity differs")
    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise JournalError("journal integrity check failed")
    for query, limit in (("SELECT count(*) FROM polls", MAX_POLLS), ("SELECT count(*) FROM events", MAX_EVENTS), ("SELECT count(*) FROM candidates", MAX_CANDIDATES)):
        if db.execute(query).fetchone()[0] > limit:
            raise JournalError("journal history exceeds retention ceiling")
    if db.execute("SELECT 1 FROM candidates c JOIN events e ON c.event_id=e.id WHERE c.repo!=e.repo OR c.number!=e.number LIMIT 1").fetchone():
        raise JournalError("candidate identity disagrees with observation")
    if db.execute("SELECT 1 FROM candidates c JOIN events e ON c.event_id=e.id WHERE e.generation!=(SELECT max(generation) FROM events x WHERE x.repo=c.repo AND x.number=c.number) LIMIT 1").fetchone():
        raise JournalError("candidate points to superseded observation")
    if db.execute("SELECT 1 FROM events e LEFT JOIN candidates c ON c.repo=e.repo AND c.number=e.number WHERE c.repo IS NULL LIMIT 1").fetchone():
        raise JournalError("observation history lost its candidate projection")
    for row in db.execute("SELECT * FROM polls"):
        if row["status"] not in {"STARTED", "INTERRUPTED", "CHANGED", "CURRENT", "UNVERIFIED"}:
            raise JournalError("invalid retained poll state")
        if row["status"] in {"STARTED", "INTERRUPTED"}:
            if row["response"] is not None or row["digest"] is not None:
                raise JournalError("unfinished poll carries a successful receipt")
            continue
        response = json.loads(row["response"])
        expected = {}
        for coverage in db.execute("SELECT * FROM coverage WHERE seq=?", (row["seq"],)):
            expected[coverage["source"]] = {"status":coverage["status"], "digest":coverage["digest"], "reason":coverage["reason"]}
        if (response.get("status") != row["status"] or response.get("poll_seq") != row["seq"]
                or response.get("coverage") != expected or not isinstance(response.get("changes"), list)
                or not isinstance(row["digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["digest"])):
            raise JournalError("poll receipt differs from retained coverage")
        if row["status"] in {"CURRENT", "CHANGED"} and (not expected or any(value["status"] != "OBSERVED" for value in expected.values())):
            raise JournalError("poll success lacks coverage")
    for row in db.execute("SELECT * FROM coverage"):
        if not SOURCE.fullmatch(row["source"]) or row["status"] not in {"OBSERVED", "UNVERIFIED", "NOT_ATTEMPTED"}:
            raise JournalError("invalid retained source coverage")
    for row in db.execute("SELECT * FROM events"):
        value = json.loads(row["payload"])
        if not SOURCE.fullmatch("repo:"+row["repo"]) or type(row["number"]) is not int or row["number"] <= 0:
            raise JournalError("invalid retained candidate identity")
        if set(value) != {"head","draft","state","review","merge","checks","presence"} or value["presence"] not in {"OPEN_SET","NOT_IN_OPEN_SET"}:
            raise JournalError("invalid retained observation shape")
        material(value)
        if fingerprint(value) != row["fingerprint"]:
            raise JournalError("retained observation differs from fingerprint")
    if db.execute("SELECT 1 FROM sources s LEFT JOIN coverage c ON s.source=c.source AND s.applied_seq=c.seq WHERE c.status IS NULL OR c.status!='OBSERVED' LIMIT 1").fetchone():
        raise JournalError("source watermark lacks observed coverage")
    # Reconstruct each visible set from append-only transitions; a count/digest
    # cannot certify coverage independently of the observations it summarizes.
    views: dict[str, dict[int, Any]] = {}
    generations: dict[tuple[str, int], int] = {}
    events_by_seq: dict[int, list[Any]] = {}
    for event in db.execute("SELECT * FROM events ORDER BY seq,id"):
        events_by_seq.setdefault(event["seq"], []).append(event)
    last_seen: dict[tuple[str, int], int] = {}
    for poll in db.execute("SELECT * FROM polls ORDER BY seq"):
        for event in events_by_seq.get(poll["seq"], []):
            identity = (event["repo"], event["number"])
            if event["generation"] != generations.get(identity, 0) + 1:
                raise JournalError("nonconsecutive observation generation")
            generations[identity] = event["generation"]
            views.setdefault(event["repo"], {})[event["number"]] = json.loads(event["payload"])
        for coverage in db.execute("SELECT * FROM coverage WHERE seq=?", (poll["seq"],)):
            if coverage["status"] != "OBSERVED" or not coverage["source"].startswith("repo:"):
                continue
            repo = coverage["source"][5:]
            visible = [{"repo":repo, "number":number, **value} for number,value in sorted(views.get(repo, {}).items()) if value["presence"] == "OPEN_SET"]
            if coverage["count"] != len(visible) or coverage["digest"] != fingerprint(visible):
                raise JournalError("source coverage differs from reconstructed observations")
            for item in visible:
                last_seen[(repo,item["number"])] = poll["seq"]
    for candidate in db.execute("SELECT * FROM candidates"):
        first = db.execute("SELECT min(seq) FROM events WHERE repo=? AND number=?", (candidate["repo"], candidate["number"])).fetchone()[0]
        if candidate["first_seq"] != first or candidate["last_seen_seq"] != last_seen.get((candidate["repo"],candidate["number"])):
            raise JournalError("candidate observation sequence mismatch")


def decode_intent(raw: str) -> dict[str, Any]:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise JournalError("duplicate claim intent field")
            value[key] = item
        return value

    try:
        if type(raw) is not str or len(raw.encode("utf-8")) > MAX_INTENT_BYTES:
            raise JournalError("claim intent exceeds byte limit")
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(JournalError("invalid JSON constant")))
        if type(value) is not dict or canonical(value) != raw:
            raise JournalError("noncanonical claim intent")
        return value
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise JournalError("malformed claim intent") from exc


def validate_claim_intent(request: dict[str, Any]) -> None:
    """Pure, packaged publication-intent validation; no consumer imports or effects."""
    def fields(value, keys):
        if type(value) is not dict or set(value) != set(keys.split()):
            raise JournalError("unsupported claim intent fields")

    def token(value, pattern):
        if type(value) is not str or re.fullmatch(pattern, value, re.ASCII) is None:
            raise JournalError("invalid claim intent token")

    def number(value, minimum=1):
        if type(value) is not int or not minimum <= value <= 2**63 - 1:
            raise JournalError("invalid claim intent integer")

    def stamp(value):
        token(value, r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z")
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise JournalError("invalid claim intent timestamp") from exc

    if type(request) is not dict or type(request.get("schema_version")) is not int or request["schema_version"] not in {1, 2}:
        raise JournalError("unsupported claim intent version/action")
    extra = " identity_observation public_text_declaration" if request["schema_version"] == 2 else ""
    fields(request, "schema_version action operation_id store_id claim comment comment_sha256 binding" + extra)
    if request["action"] != "claim-publication":
        raise JournalError("unsupported claim intent version/action")
    token(request["operation_id"], r"[0-9a-f]{32}")
    token(request["store_id"], r"[0-9a-f]{32}")
    token(request["comment_sha256"], r"[0-9a-f]{64}")
    claim = request["claim"]
    fields(claim, "version action repo issue claim_id operation_id actor branch task_ref scope")
    if type(claim["version"]) is not int or claim["version"] != 1 or claim["action"] != "claim":
        raise JournalError("unsupported public claim")
    login = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
    token(claim["actor"], login)
    token(claim["repo"], login + r"/[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
    owner, name = claim["repo"].split("/")
    if "--" in owner or "--" in claim["actor"] or ".." in name or name.endswith("."):
        raise JournalError("invalid public claim name")
    number(claim["issue"])
    token(claim["claim_id"], r"[0-9a-f]{32}")
    if claim["operation_id"] != request["operation_id"]:
        raise JournalError("public operation differs")
    token(claim["branch"], r"[A-Za-z0-9][A-Za-z0-9/_-]{0,127}")
    if claim["branch"].endswith("/") or "//" in claim["branch"]:
        raise JournalError("invalid public branch")
    if claim["task_ref"] != f'issue:{claim["issue"]}' or type(claim["scope"]) is not str or claim["scope"] not in {"implementation", "review"}:
        raise JournalError("invalid public task reference")
    # Keep this packaged wire contract exact; consumer fixtures compare it with
    # native-claim.py's renderer. Monitor readers must not import consumer code.
    body = ("Public coordination claim proposal (v1).\n"
            "Operator review of every public field is required before posting.\n"
            "This comment does not grant admission or mutation authority.\n\n"
            "<!-- native-claim:v1 " + canonical(claim) + " -->\n")
    if request["comment"] != body or hashlib.sha256(body.encode("utf-8")).hexdigest() != request["comment_sha256"]:
        raise JournalError("claim intent public body differs")
    if request["schema_version"] == 2:
        observed = request["identity_observation"]
        fields(observed, "schema_version actor_id actor_node_id actor_login repository_id repository_node_id issue_id issue_node_id observed_at remote_coverage")
        declaration = request["public_text_declaration"]
        fields(declaration, "schema_version reviewer approved_body_sha256 public_text_approval")
        for item in (observed, declaration):
            if type(item["schema_version"]) is not int or item["schema_version"] != 1:
                raise JournalError("unsupported identity declaration version")
        for key in ("actor_id", "repository_id", "issue_id"):
            number(observed[key])
        for key in ("actor_node_id", "repository_node_id", "issue_node_id"):
            token(observed[key], r"[A-Za-z0-9_+/=-]{1,256}")
        token(observed["actor_login"], login)
        token(declaration["reviewer"], login)
        if "--" in declaration["reviewer"]:
            raise JournalError("invalid declared reviewer")
        stamp(observed["observed_at"])
        token(observed["observed_at"], r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
        if (observed["actor_login"] != claim["actor"]
                or observed["remote_coverage"] != "repeated_identity_gets"
                or declaration["public_text_approval"] != "DECLARED_UNAUTHENTICATED"
                or declaration["approved_body_sha256"] != request["comment_sha256"]):
            raise JournalError("identity declaration differs")
    binding = request["binding"]
    fields(binding, "task_id created_at task_sha256 revision generation session_id worker")
    token(binding["task_id"], r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
    stamp(binding["created_at"])
    token(binding["task_sha256"], r"[0-9a-f]{64}")
    number(binding["revision"])
    number(binding["generation"])
    token(binding["session_id"], r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
    worker = binding["worker"]
    fields(worker, "task_id owner pid process_start worker_id token hostname created_at session_id generation")
    for key in ("worker_id", "token"):
        token(worker[key], r"[0-9a-f]{32}")
    number(worker["pid"])
    stamp(worker["created_at"])
    for key in ("owner", "hostname", "process_start"):
        value = worker[key]
        if type(value) is not str or not 1 <= len(value) <= 500 or value != value.strip() or any(ord(c) < 32 for c in value):
            raise JournalError("invalid private worker metadata")
    if (type(worker["task_id"]) is not str or type(worker["session_id"]) is not str
            or worker["task_id"] != binding["task_id"] or worker["session_id"] != binding["session_id"]
            or type(worker["generation"]) is not int or worker["generation"] != binding["generation"]
            or binding["generation"] > binding["revision"]):
        raise JournalError("private claim binding differs")
    private = {binding["session_id"], worker["worker_id"], worker["token"], request["store_id"]}
    if any(value in body for value in private):
        raise JournalError("private identity reused in public body")
    if len(canonical(request).encode("utf-8")) > MAX_INTENT_BYTES:
        raise JournalError("claim intent exceeds byte limit")


def record_claim_intent(db: sqlite3.Connection, request: dict[str, Any], *, guard=None) -> str:
    """Caller holds coordinator lock and fresh ownership match; never poll business.

    Only this explicit API upgrades the shared store. A committed row is pending
    local intent, never task authority, readiness or a remote acknowledgment.
    The caller must complete filesystem durability barriers before reporting it.
    """
    validate_claim_intent(request)
    raw = canonical(request)
    if db.in_transaction:
        raise JournalError("claim intent requires independent transaction")
    with db:
        db.execute("BEGIN IMMEDIATE")
        validate_store(db)
        version, identity = db.execute("SELECT version,store_id FROM meta").fetchone()
        if identity != request["store_id"]:
            raise JournalError("claim intent store differs")
        reject_reserved_observation_ids(db, claim_intent_identifiers(request))
        if guard is not None:
            guard()
        if version in {3, 4, 5}:
            prior = db.execute("SELECT request FROM claim_intents WHERE operation_id=?", (request["operation_id"],)).fetchone()
            if prior:
                if prior[0] != raw:
                    raise JournalError("conflicting claim operation")
                return "REPLAYED_PENDING"
            if db.execute("SELECT count(*) FROM claim_intents").fetchone()[0] >= MAX_CLAIM_INTENTS:
                raise JournalError("claim intent capacity reached")
        if MAX_CLAIM_INTENTS < 1:
            raise JournalError("claim intent capacity reached")
        if version == 1:
            db.execute("CREATE TABLE binding_acks (incarnation TEXT PRIMARY KEY, task_id TEXT NOT NULL, operation_id TEXT NOT NULL, receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL)")
            db.execute("UPDATE meta SET version=2")
        if version in {1, 2}:
            db.execute("CREATE TABLE claim_intents (operation_id TEXT PRIMARY KEY NOT NULL, request TEXT NOT NULL, request_sha256 TEXT NOT NULL)")
            db.execute("UPDATE meta SET version=3")
        if request["schema_version"] == 2 and version != 5:
            if version in {1, 2, 3}:
                db.execute("CREATE TABLE claim_observations (observation_id TEXT PRIMARY KEY NOT NULL, operation_id TEXT NOT NULL REFERENCES claim_intents(operation_id), request_sha256 TEXT NOT NULL, receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL)")
            db.execute("UPDATE meta SET version=5")
        db.execute("INSERT INTO claim_intents VALUES(?,?,?)", (request["operation_id"], raw, fingerprint(request)))
        validate_store(db)
        if guard is not None:
            guard()
    return "INTENT_RECORDED"


def validate_claim_observation(db: sqlite3.Connection, receipt: dict[str, Any]) -> None:
    """Bound historical summary only; a digest never certifies source freshness."""
    if (type(receipt) is not dict or set(receipt) != {
            "schema_version", "observation_id", "operation_id", "store_id",
            "intent_request_sha256", "status", "reason", "summary", "observed_at"}
            or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1):
        raise JournalError("unsupported claim observation fields")
    for key in ("observation_id", "operation_id", "store_id", "intent_request_sha256"):
        length = 64 if key == "intent_request_sha256" else 32
        if type(receipt[key]) is not str or re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", receipt[key]) is None:
            raise JournalError("invalid claim observation identifier")
    reasons = {"VISIBLE_MATCH": "EXACT_PENDING_INTENT_VISIBLE",
               "NO_MATCH_OBSERVED": "NO_MATCH_OBSERVED", "CONFLICT": "OBSERVED_CONFLICT"}
    if type(receipt["status"]) is not str or receipt["status"] not in reasons or receipt["reason"] != reasons[receipt["status"]]:
        raise JournalError("invalid claim observation status")
    stamp = receipt["observed_at"]
    if type(stamp) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", stamp) is None:
        raise JournalError("invalid claim observation timestamp")
    try:
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JournalError("invalid claim observation timestamp") from exc
    summary = receipt["summary"]
    if type(summary) is not dict or set(summary) != {
            "remote_coverage", "repository_id", "issue_id", "issue_number", "issue_closed",
            "issue_locked", "page_count", "comment_count", "recognized_claim_count",
            "comment_id", "comment_sha256"} or summary["remote_coverage"] != "complete_pagination":
        raise JournalError("invalid claim observation summary")
    for key, minimum, maximum in (("repository_id", 1, 2**63 - 1), ("issue_id", 1, 2**63 - 1),
                                  ("issue_number", 1, 2**63 - 1), ("page_count", 1, 10),
                                  ("comment_count", 0, 1000), ("recognized_claim_count", 0, 1000)):
        if type(summary[key]) is not int or not minimum <= summary[key] <= maximum:
            raise JournalError("invalid claim observation count")
    if (type(summary["issue_closed"]) is not bool or type(summary["issue_locked"]) is not bool
            or summary["recognized_claim_count"] > summary["comment_count"]):
        raise JournalError("invalid claim observation summary")
    row = db.execute("SELECT request,request_sha256 FROM claim_intents WHERE operation_id=?",
                     (receipt["operation_id"],)).fetchone()
    if row is None:
        raise JournalError("claim observation lacks intent")
    request = decode_intent(row[0])
    validate_claim_intent(request)
    if (receipt["store_id"] != db.execute("SELECT store_id FROM meta").fetchone()[0]
            or receipt["store_id"] != request["store_id"]
            or receipt["intent_request_sha256"] != row[1] or row[1] != fingerprint(request)
            or summary["issue_number"] != request["claim"]["issue"]):
        raise JournalError("claim observation intent differs")
    if request["schema_version"] == 2 and any(
            summary[key] != request["identity_observation"][key] for key in ("repository_id", "issue_id")):
        raise JournalError("claim observation immutable target differs")
    if receipt["status"] == "VISIBLE_MATCH":
        if (type(summary["comment_id"]) is not int or not 1 <= summary["comment_id"] <= 2**63 - 1
                or summary["comment_sha256"] != request["comment_sha256"]
                or summary["recognized_claim_count"] != 1):
            raise JournalError("claim observation match differs")
    elif summary["comment_id"] is not None or summary["comment_sha256"] is not None:
        raise JournalError("nonmatch carries match identity")
    if receipt["status"] == "NO_MATCH_OBSERVED" and summary["recognized_claim_count"] != 0:
        raise JournalError("nonmatch carries recognized claim")
    if receipt["status"] == "CONFLICT" and summary["recognized_claim_count"] < 1:
        raise JournalError("conflict lacks recognized claim")
    # Check all known private and public claim/operation IDs, not substrings of
    # the body. Also check acknowledgments' private task incarnation identifiers.
    validate_observation_id(db, receipt["observation_id"])


def validate_observation_id(db: sqlite3.Connection, observation_id: str) -> None:
    if type(observation_id) is not str or re.fullmatch(r"[0-9a-f]{32}", observation_id) is None:
        raise JournalError("invalid claim observation identifier")
    forbidden = {db.execute("SELECT store_id FROM meta").fetchone()[0]}
    for intent in db.execute("SELECT request FROM claim_intents"):
        value = decode_intent(intent[0])
        forbidden.update(claim_intent_identifiers(value))
    for row in db.execute("SELECT incarnation,operation_id FROM binding_acks"):
        forbidden.update(row)
    if observation_id in forbidden:
        raise JournalError("claim observation identifier reuse")


def claim_intent_identifiers(request: dict[str, Any]) -> set[str]:
    """Exact known IDs only, never body substrings or arbitrary prose."""
    binding = request["binding"]
    worker = binding["worker"]
    return {request["store_id"], request["operation_id"], request["claim"]["claim_id"],
            binding["session_id"], worker["session_id"], worker["worker_id"], worker["token"]}


def reject_reserved_observation_ids(db: sqlite3.Connection, identifiers) -> None:
    """Symmetric pre-write reservation: future IDs cannot invalidate history.

    Caller validates the store and retains its transaction/coordinator fences.
    Legacy versions have no observation namespace and retain their behavior.
    """
    if db.execute("SELECT version FROM meta").fetchone()[0] not in {4, 5}:
        return
    reserved = {row[0] for row in db.execute("SELECT observation_id FROM claim_observations")}
    if reserved.intersection(identifiers):
        raise JournalError("reserved claim observation identifier")


def claim_observation(db: sqlite3.Connection, observation_id: str) -> dict[str, Any] | None:
    version = db.execute("SELECT version FROM meta").fetchone()[0]
    if version not in {3, 4, 5}:
        raise JournalError("claim observation requires existing intent schema")
    if version == 3:
        return None
    row = db.execute("SELECT receipt FROM claim_observations WHERE observation_id=?", (observation_id,)).fetchone()
    return decode_intent(row[0]) if row else None


def record_claim_observation(db: sqlite3.Connection, receipt: dict[str, Any], *, guard) -> str:
    """Coordinator-held append. Migration and insertion share one FULL transaction."""
    if db.in_transaction:
        raise JournalError("claim observation requires independent transaction")
    with db:
        db.execute("BEGIN IMMEDIATE")
        validate_store(db)
        version = db.execute("SELECT version FROM meta").fetchone()[0]
        if version not in {3, 4, 5}:
            raise JournalError("claim observation requires existing intent schema")
        validate_claim_observation(db, receipt)
        guard()
        prior = claim_observation(db, receipt["observation_id"])
        if prior is not None:
            if prior != receipt:
                raise JournalError("conflicting claim observation")
            return "HISTORICAL_REPLAY"
        count = db.execute("SELECT count(*) FROM claim_observations").fetchone()[0] if version in {4, 5} else 0
        if count >= MAX_CLAIM_OBSERVATIONS:
            raise JournalError("claim observation capacity reached")
        if version == 3:
            db.execute("CREATE TABLE claim_observations (observation_id TEXT PRIMARY KEY NOT NULL, operation_id TEXT NOT NULL REFERENCES claim_intents(operation_id), request_sha256 TEXT NOT NULL, receipt TEXT NOT NULL, receipt_sha256 TEXT NOT NULL)")
            db.execute("UPDATE meta SET version=4")
        db.execute("INSERT INTO claim_observations VALUES(?,?,?,?,?)",
                   (receipt["observation_id"], receipt["operation_id"], receipt["intent_request_sha256"],
                    canonical(receipt), fingerprint(receipt)))
        validate_store(db)
        guard()
    return "HISTORICAL_RECORDED"


def begin(db: sqlite3.Connection, attempt: str, config: str, task: str, sources: list[str], started: str) -> int:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", attempt) or not re.fullmatch(r"[0-9a-f]{64}", config):
        raise JournalError("invalid poll identity")
    if not sources or len(sources) > 51 or len(set(sources)) != len(sources) or any(not SOURCE.fullmatch(source) for source in sources):
        raise JournalError("invalid configured source set")
    with db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM polls WHERE attempt=?", (attempt,)).fetchone():
            raise JournalError("poll attempt already exists")
        if db.execute("SELECT count(*) FROM polls").fetchone()[0] >= MAX_POLLS:
            raise JournalError("poll history capacity reached; operator archive required")
        # Caller holds the common poll lock. A leftover STARTED row is evidence
        # of interruption, not evidence that an old host process terminated.
        db.execute("UPDATE coverage SET status='UNVERIFIED', reason='INTERRUPTED' WHERE seq IN (SELECT seq FROM polls WHERE status='STARTED')")
        db.execute("UPDATE polls SET status='INTERRUPTED',finished=? WHERE status='STARTED'", (started,))
        cursor = db.execute("INSERT INTO polls(attempt,config,task,started,status) VALUES(?,?,?,?, 'STARTED')", (attempt, config, task, started))
        seq = cursor.lastrowid
        for source in sources:
            db.execute("INSERT INTO coverage(seq,source,status) VALUES(?,?,'NOT_ATTEMPTED')", (seq, source))
    assert seq is not None
    return seq


def material(pr: dict[str, Any]) -> dict[str, Any]:
    # Deliberately excludes title/author/timestamps. These are not work triggers.
    fields = {name: pr[name] for name in ("head", "draft", "state", "review", "merge", "checks")}
    if not isinstance(fields["head"], str) or not re.fullmatch(r"[0-9a-f]{40}", fields["head"]) or type(fields["draft"]) is not bool or fields["state"] != "OPEN":
        raise JournalError("invalid open PR identity")
    for name in ("review", "merge"):
        if not isinstance(fields[name], str) or not re.fullmatch(r"[A-Z_]{1,60}", fields[name]):
            raise JournalError("invalid PR status field")
    if not isinstance(fields["checks"], list) or len(fields["checks"]) > 500 or any(not isinstance(item, str) or not re.fullmatch(r"[A-Z_]{1,60}", item) for item in fields["checks"]):
        raise JournalError("invalid check summary")
    fields["checks"] = sorted(fields["checks"])
    return {**fields, "presence": "OPEN_SET"}


def validate_results(results: dict[str, Any]) -> dict[str, Any]:
    clean = {}
    for source, result in results.items():
        if not SOURCE.fullmatch(source) or not isinstance(result, dict) or set(result) != {"status", "items", "digest", "reason"}:
            raise JournalError("invalid source result")
        if result["status"] not in {"OBSERVED", "UNVERIFIED", "NOT_ATTEMPTED"}:
            raise JournalError("invalid coverage state")
        if result["status"] != "OBSERVED":
            if result["items"] != [] or result["digest"] is not None or not isinstance(result["reason"], str) or not re.fullmatch(r"[A-Z_]{1,60}", result["reason"]):
                raise JournalError("degraded coverage has unsupported data")
            clean[source] = result
            continue
        if result["reason"] is not None or not isinstance(result["items"], list) or len(result["items"]) > 500:
            raise JournalError("invalid observed coverage")
        if source.startswith("project:"):
            if result["items"] or not isinstance(result["digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", result["digest"]):
                raise JournalError("invalid Project observation")
            clean[source] = result
            continue
        items, numbers = [], set()
        for pr in result["items"]:
            if not isinstance(pr, dict) or pr.get("repo") != source[5:] or type(pr.get("number")) is not int or pr["number"] <= 0 or pr["number"] in numbers:
                raise JournalError("duplicate/malformed PR observation")
            numbers.add(pr["number"])
            items.append({"repo": pr["repo"], "number": pr["number"], **material(pr)})
        items.sort(key=lambda item: item["number"])
        clean[source] = {"status": "OBSERVED", "items": items, "digest": fingerprint(items), "reason": None}
    return clean


def finish(db: sqlite3.Connection, seq: int, results: dict[str, Any], finished: str) -> dict[str, Any]:
    validate_store(db)
    results = validate_results(results)
    result_digest = fingerprint(results)
    with db:
        db.execute("BEGIN IMMEDIATE")
        poll = db.execute("SELECT * FROM polls WHERE seq=?", (seq,)).fetchone()
        if poll is None:
            raise JournalError("poll intent missing")
        if poll["status"] != "STARTED":
            if poll["digest"] == result_digest and poll["response"]:
                return json.loads(poll["response"])
            raise JournalError("poll is finalized, interrupted or conflicting")
        sources = {row[0] for row in db.execute("SELECT source FROM coverage WHERE seq=?", (seq,))}
        if sources != set(results):
            raise JournalError("poll source coverage incomplete")
        changed = []
        source_changed = False
        for source, result in sorted(results.items()):
            db.execute("UPDATE coverage SET status=?,count=?,digest=?,reason=? WHERE seq=? AND source=?",
                       (result["status"], len(result["items"]) if source.startswith("repo:") and result["status"] == "OBSERVED" else None,
                        result["digest"], result["reason"], seq, source))
            if result["status"] != "OBSERVED":
                continue
            previous_seq = db.execute("SELECT applied_seq FROM sources WHERE source=?", (source,)).fetchone()
            if previous_seq is not None and previous_seq[0] >= seq:
                raise JournalError("older snapshot cannot overwrite newer source state")
            old_digest = db.execute("SELECT digest FROM coverage WHERE source=? AND seq=?", (source, previous_seq[0])).fetchone() if previous_seq else None
            if old_digest is None or old_digest[0] != result["digest"]:
                source_changed = True
            if source.startswith("repo:"):
                repo = source[5:]
                current = {row["number"]: row for row in db.execute("SELECT c.*,e.generation,e.payload,e.fingerprint FROM candidates c JOIN events e ON c.event_id=e.id WHERE c.repo=?", (repo,))}
                incoming = {pr["number"]: {key:value for key,value in pr.items() if key not in {"repo", "number"}} for pr in result["items"]}
                for number in sorted(set(current) | set(incoming)):
                    old = current.get(number)
                    value = incoming.get(number)
                    if value is None:
                        value = {**json.loads(old["payload"]), "presence": "NOT_IN_OPEN_SET"}
                    hashed = fingerprint(value)
                    if old is None or old["fingerprint"] != hashed:
                        generation = 1 if old is None else old["generation"] + 1
                        if db.execute("SELECT count(*) FROM events").fetchone()[0] >= MAX_EVENTS or (old is None and db.execute("SELECT count(*) FROM candidates").fetchone()[0] >= MAX_CANDIDATES):
                            raise JournalError("observation capacity reached; preserve journal and archive explicitly")
                        event = db.execute("INSERT INTO events(repo,number,generation,seq,payload,fingerprint) VALUES(?,?,?,?,?,?)", (repo, number, generation, seq, canonical(value), hashed)).lastrowid
                        db.execute("INSERT INTO candidates VALUES(?,?,?,?,?) ON CONFLICT(repo,number) DO UPDATE SET event_id=excluded.event_id,last_seen_seq=excluded.last_seen_seq",
                                   (repo, number, event, seq if old is None else old["first_seq"], seq if number in incoming else old["last_seen_seq"]))
                        changed.append({"repo": repo, "number": number, "generation": generation, "presence": value["presence"]})
                    elif number in incoming:
                        db.execute("UPDATE candidates SET last_seen_seq=? WHERE repo=? AND number=?", (seq, repo, number))
            db.execute("INSERT INTO sources VALUES(?,?) ON CONFLICT(source) DO UPDATE SET applied_seq=excluded.applied_seq", (source, seq))
        status = "UNVERIFIED" if any(item["status"] != "OBSERVED" for item in results.values()) else "CHANGED" if changed or source_changed else "CURRENT"
        response = {"status": status, "poll_seq": seq, "changes": changed,
                    "coverage": {source: {key:value for key,value in result.items() if key != "items"} for source,result in results.items()}}
        db.execute("UPDATE polls SET finished=?,status=?,digest=?,response=? WHERE seq=?", (finished, status, result_digest, canonical(response), seq))
    return response


def status(db: sqlite3.Connection, configured: list[str]) -> dict[str, Any]:
    if db.in_transaction:
        raise JournalError("status requires an independent read snapshot")
    db.execute("BEGIN")
    try:
        return snapshot_status(db, configured)
    finally:
        db.rollback()


def snapshot_status(db: sqlite3.Connection, configured: list[str]) -> dict[str, Any]:
    validate_store(db)
    latest = db.execute("SELECT * FROM polls ORDER BY seq DESC LIMIT 1").fetchone()
    if latest is None:
        return {"status": "UNVERIFIED", "reason": "no observed poll", "candidates": []}
    store_id = db.execute("SELECT store_id FROM meta").fetchone()[0]
    coverage = {row["source"]: {key:row[key] for key in ("status", "count", "reason")} for row in db.execute("SELECT * FROM coverage WHERE seq=?", (latest["seq"],))}
    candidates = []
    for row in db.execute("SELECT c.*,e.generation,e.payload,e.fingerprint FROM candidates c JOIN events e ON c.event_id=e.id ORDER BY c.repo,c.number"):
        value = json.loads(row["payload"])
        if fingerprint(value) != row["fingerprint"]:
            raise JournalError("retained observation fingerprint mismatch")
        scope = "IN_SCOPE" if "repo:" + row["repo"] in configured else "OUT_OF_SCOPE"
        fresh = scope == "IN_SCOPE" and coverage.get("repo:" + row["repo"], {}).get("status") == "OBSERVED"
        candidates.append({"repo": row["repo"], "number": row["number"], "generation": row["generation"],
                           "reference": f"{store_id}:{row['repo']}#{row['number']}:{row['generation']}",
                           "observation": value, "scope": scope, "latest_poll_observed_source": fresh,
                           "last_seen_seq": row["last_seen_seq"], "admission": "UNMEASURED"})
    return {"status": "AS_OF_POLL" if latest["status"] in {"CURRENT", "CHANGED"} and set(coverage) == set(configured) else "UNVERIFIED",
            "store_id": store_id, "poll_seq": latest["seq"], "poll_status": latest["status"], "finished_at": latest["finished"],
            "coverage": coverage, "candidates": candidates, "continuous_monitoring": "UNMEASURED",
            "history": "bounded journal begins with first retained poll; no legacy checkpoint import"}
