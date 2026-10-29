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
from pathlib import Path
from typing import Any

MAX_POLLS = 10_000
MAX_EVENTS = 50_000
MAX_CANDIDATES = 10_000
MAX_DB = 64_000_000
SOURCE = re.compile(r"^(?:repo:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+|project:[A-Za-z0-9_.-]+/[1-9][0-9]*)$")
TABLES = {"meta", "polls", "sources", "coverage", "events", "candidates"}


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
    connection = sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro"), uri=True, timeout=2)
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
        return connection
    except Exception:
        connection.close()
        raise


def validate_store(db: sqlite3.Connection) -> None:
    objects = db.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    names = {row["name"] for row in objects}
    if names not in (TABLES, TABLES | {"binding_acks"}) or any(row["type"] != "table" for row in objects):
        raise JournalError("unsupported journal schema")
    meta = db.execute("SELECT * FROM meta").fetchall()
    if (len(meta) != 1 or meta[0]["version"] not in {1,2} or not re.fullmatch(r"[0-9a-f]{32}", meta[0]["store_id"])
            or (meta[0]["version"] == 2) != ("binding_acks" in names)):
        raise JournalError("unsupported journal version/identity")
    if "binding_acks" in names:
        columns = [row[1] for row in db.execute("PRAGMA table_info(binding_acks)")]
        if columns != ["incarnation","task_id","operation_id","receipt","receipt_sha256"]:
            raise JournalError("unsupported acknowledgment schema")
        if db.execute("SELECT count(*) FROM binding_acks").fetchone()[0] > 10_000:
            raise JournalError("acknowledgment capacity exceeded")
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
