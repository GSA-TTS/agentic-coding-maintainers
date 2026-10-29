#!/usr/bin/env python3
"""Foreground controller capture of a pre-provisioned network-off Docker guest.

Definitions are operator-approved inputs, not candidate instructions. This
observes transport and black-box assertions; it does not attest all guest code.
Unsettled attempts fence task reuse until exact-container stop is observed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

MAX_OUTPUT = 1_000_000
HEX = re.compile(r"^[0-9a-f]{64}$")


class Unverified(Exception):
    pass


def dependency(name: str):
    path = Path(__file__).resolve().with_name(name + ".py")
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), path)
    if spec is None or spec.loader is None:
        raise Unverified("installed controller dependency unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_definition(value: dict[str, Any]) -> None:
    required = {"schema_version", "docker_binary", "docker_sha256", "endpoint", "container_id", "created",
                "image_id", "environment", "mounts", "cases", "head", "base", "source_sha256"}
    if set(value) != required or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise Unverified("invalid execution definition fields/version")
    for name in ("docker_sha256", "container_id"):
        if not isinstance(value[name], str) or not HEX.fullmatch(value[name]):
            raise Unverified("invalid runtime/container digest")
    if not isinstance(value["image_id"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value["image_id"]):
        raise Unverified("image must be an immutable local image ID")
    for name in ("head", "base"):
        if not isinstance(value[name], str) or not re.fullmatch(r"[0-9a-f]{40}", value[name]):
            raise Unverified("explicit source commits required")
    if not isinstance(value["created"], str) or not value["created"] or len(value["created"]) > 100:
        raise Unverified("container creation identity required")
    if not isinstance(value["endpoint"], str) or not value["endpoint"].startswith("unix:///") or len(value["endpoint"]) > 4096:
        raise Unverified("explicit local Unix Docker endpoint required")
    binary = Path(value["docker_binary"])
    if not binary.is_absolute():
        raise Unverified("absolute installed Docker binary required")
    environment = value["environment"]
    if not isinstance(environment, list) or len(environment) > 50 or any(not isinstance(item, str) or len(item) > 4096 for item in environment):
        raise Unverified("invalid provisioned environment inventory")
    mounts = value["mounts"]
    if not isinstance(mounts, list) or len(mounts) > 4:
        raise Unverified("invalid mount inventory")
    for mount in mounts:
        if not isinstance(mount, dict) or set(mount) != {"Source", "Destination", "Type", "RW"} or mount["RW"] is not False or mount["Type"] != "bind":
            raise Unverified("only explicit read-only source bind mounts allowed")
        for name in ("Source", "Destination"):
            if not isinstance(mount[name], str) or not mount[name].startswith("/"):
                raise Unverified("mount paths must be absolute")
    sources = value["source_sha256"]
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 20:
        raise Unverified("explicit source inventory required")
    for path, sha in sources.items():
        if (not isinstance(path, str) or path.startswith("/") or ".." in Path(path).parts
                or not isinstance(sha, str) or not HEX.fullmatch(sha)):
            raise Unverified("invalid source binding")
    cases = value["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= 12:
        raise Unverified("1-12 independently defined cases required")
    identifiers = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "argv", "expected_stdout", "expected_exit", "timeout"}:
            raise Unverified("invalid assertion case")
        if not isinstance(case["id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", case["id"]) or case["id"] in identifiers:
            raise Unverified("invalid or duplicated case ID")
        identifiers.add(case["id"])
        argv = case["argv"]
        if (not isinstance(argv, list) or not 1 <= len(argv) <= 32 or any(not isinstance(arg, str) or "\0" in arg or len(arg) > 4096 for arg in argv)
                or not argv[0].startswith("/")):
            raise Unverified("bounded explicit guest argv required")
        if not isinstance(case["expected_stdout"], str) or len(case["expected_stdout"].encode()) > 100_000:
            raise Unverified("invalid expected output")
        if type(case["expected_exit"]) is not int or case["expected_exit"] != 0:
            raise Unverified("only zero-exit contracts supported; nonzero Docker exits are transport-ambiguous")
        if type(case["timeout"]) is not int or not 1 <= case["timeout"] <= 60:
            raise Unverified("case timeout must be 1-60 seconds")


def inspect_guest(definition: dict[str, Any], item: dict[str, Any]) -> None:
    if item.get("Id") != definition["container_id"] or item.get("Created") != definition["created"] or item.get("Image") != definition["image_id"]:
        raise Unverified("container incarnation/image mismatch")
    config, host, state = item["Config"], item["HostConfig"], item["State"]
    user = config.get("User", "")
    if not re.fullmatch(r"[1-9][0-9]*(?::[1-9][0-9]*)?", user) or config.get("Env") != definition["environment"]:
        raise Unverified("guest identity/environment mismatch")
    if (state.get("Running") is not True or state.get("Paused") or state.get("Restarting")
            or host.get("NetworkMode") != "none" or host.get("Privileged") is not False
            or host.get("ReadonlyRootfs") is not True or host.get("CapAdd")
            or "ALL" not in (host.get("CapDrop") or [])
            or not any(item in (host.get("SecurityOpt") or []) for item in ("no-new-privileges", "no-new-privileges:true"))):
        raise Unverified("guest isolation properties are not satisfied")
    if (not 0 < host.get("Memory", 0) <= 4_294_967_296 or not 0 < host.get("NanoCpus", 0) <= 4_000_000_000
            or not isinstance(host.get("PidsLimit"), int) or not 0 < host["PidsLimit"] <= 512):
        raise Unverified("guest resource bounds unavailable")
    if (host.get("PidMode") or host.get("IpcMode") not in {"private", "none"} or host.get("Devices")
            or host.get("DeviceRequests") or host.get("PortBindings") or host.get("VolumesFrom")):
        raise Unverified("guest exposes extra host resources")
    actual = [{name: mount[name] for name in ("Source", "Destination", "Type", "RW")}
              for mount in item.get("Mounts", [])]
    if actual != definition["mounts"]:
        raise Unverified("guest source mount inventory mismatch")
    # Inspected guest mount allowlist, not host file creation.
    if set(host.get("Tmpfs") or {}) - {"/tmp", "/work"}:  # nosec B108
        raise Unverified("unexpected writable guest scratch mount")


def evaluate(case: dict[str, Any], stdout: bytes, stderr: bytes, code: int | None, failure: str | None) -> dict[str, Any]:
    # The oracle is controller-owned expected bytes; candidate test counts/PASS
    # markers carry no authority. Transport errors cannot become assertion FAIL.
    verdict = "UNVERIFIED" if failure or type(code) is not int or code != 0 else (
        "PASS" if code == case["expected_exit"] and stdout == case["expected_stdout"].encode() and not stderr else "FAIL")
    return {"id": case["id"], "verdict": verdict, "returncode": code, "failure": failure,
            "stdout_sha256": digest(stdout), "stderr_sha256": digest(stderr),
            "stdout_bytes": len(stdout), "stderr_bytes": len(stderr)}


def capture(argv: list[str], env: dict[str, str], timeout: int, started, authorization=None) -> tuple[bytes, bytes, int | None, str | None]:
    out, err = bytearray(), bytearray()
    failure = None
    with authorization if authorization is not None else contextlib.nullcontext():
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=env, start_new_session=True)
        try:
            started(process.pid)
        except BaseException:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
    with process:
        assert process.stdout is not None and process.stderr is not None
        try:
            deadline = time.monotonic() + timeout
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, out)
                selector.register(process.stderr, selectors.EVENT_READ, err)
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        raise Unverified("transport timeout; guest termination unknown")
                    for key, _ in selector.select(0.1):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            key.data.extend(chunk)
                            if len(out) + len(err) > MAX_OUTPUT:
                                raise Unverified("transport output bound exceeded")
                process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except (Unverified, subprocess.TimeoutExpired) as exc:
            failure = str(exc)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    return bytes(out[:MAX_OUTPUT]), bytes(err[:MAX_OUTPUT]), process.returncode, failure


def route(definition: dict[str, Any], config: Path) -> tuple[list[str], dict[str, str]]:
    argv = [definition["docker_binary"], "--config", str(config), "--host", definition["endpoint"]]
    env = {"PATH": "/usr/bin:/bin", "HOME": str(config), "DOCKER_CONFIG": str(config)}
    return argv, env


def inspect_backend(definition: dict[str, Any], prefix: list[str], env: dict[str, str]) -> dict[str, Any]:
    out, _, code, failure = capture(prefix + ["inspect", "--type", "container", definition["container_id"]], env, 10, lambda _: None)
    if failure or code != 0:
        raise Unverified("container inspection unavailable")
    values = json.loads(out)
    if not isinstance(values, list) or len(values) != 1:
        raise Unverified("ambiguous container inspection")
    return values[0]


def source_binding(record: dict[str, Any], definition: dict[str, Any], c) -> None:
    if definition["head"] != record["head_sha"] or definition["base"] != record["base_sha"]:
        raise Unverified("definition does not bind current task commits")
    root = Path(record["worktree"])
    coordinator = dependency("orchestrator-state")
    actual_head = coordinator.git_probe(str(root), "rev-parse", "HEAD")
    if actual_head.returncode != 0 or actual_head.stdout.strip() != definition["head"]:
        raise Unverified("actual checkout HEAD differs from execution definition")
    for relative, expected in definition["source_sha256"].items():
        if digest(c.read_bytes(root / relative)) != expected:
            raise Unverified("candidate source differs from approved definition")
    for mount in definition["mounts"]:
        if Path(mount["Source"]).resolve() != root.resolve():
            raise Unverified("source mount must be the admitted worktree")


def validate_attempts(record: dict[str, Any], root: Path, c, check_streams: bool = True) -> None:
    attempts = record.get("execution_observations", {})
    if not isinstance(attempts, dict) or len(attempts) > 12:
        raise Unverified("invalid execution ledger")
    for key, attempt in attempts.items():
        required = {"request", "definition", "phase", "termination", "owner", "head", "base",
                    "controller_sha256", "cases", "launchers"}
        optional = {"result", "stop_observation", "evidence_loss"}
        if not isinstance(attempt, dict) or not required <= set(attempt) or set(attempt) - required - optional:
            raise Unverified("malformed retained attempt")
        request = attempt["request"]
        if not isinstance(request, dict) or set(request) != {"operation_id", "definition_sha256", "expected_revision"} or request["operation_id"] != key:
            raise Unverified("retained request mismatch")
        if not isinstance(request["definition_sha256"], str) or not HEX.fullmatch(request["definition_sha256"]):
            raise Unverified("invalid retained definition digest")
        if type(request["expected_revision"]) is not int or request["expected_revision"] < 0:
            raise Unverified("invalid retained admission revision")
        validate_definition(attempt["definition"])
        # Bind original approved bytes, not reserialized user JSON.
        definition_data = c.read_bytes(root / "review-artifacts" / request["definition_sha256"], 200_000)
        if digest(definition_data) != request["definition_sha256"] or c.decode(definition_data) != attempt["definition"]:
            raise Unverified("retained definition is missing or substituted")
        if attempt["head"] != attempt["definition"]["head"] or attempt["base"] != attempt["definition"]["base"]:
            raise Unverified("retained source identity differs")
        if attempt["phase"] not in {"DISPATCHING", "CAPTURED", "SETTLED", "UNKNOWN_STOPPED", "EVIDENCE_LOST_STOPPED"} or attempt["termination"] not in {"UNVERIFIED", "STOPPED_OBSERVED"}:
            raise Unverified("invalid attempt phase")
        if (attempt["phase"] in {"SETTLED", "UNKNOWN_STOPPED", "EVIDENCE_LOST_STOPPED"}) != (attempt["termination"] == "STOPPED_OBSERVED"):
            raise Unverified("termination phase mismatch")
        if attempt["termination"] == "STOPPED_OBSERVED":
            stop = attempt.get("stop_observation")
            if stop != {"container_id": attempt["definition"]["container_id"], "created": attempt["definition"]["created"], "running": False}:
                raise Unverified("termination lacks exact-container observation")
        cases = attempt["definition"]["cases"]
        if not isinstance(attempt["cases"], list) or len(attempt["cases"]) > len(cases) or not isinstance(attempt["launchers"], list) or len(attempt["launchers"]) > len(cases):
            raise Unverified("invalid observed case inventory")
        if len(attempt["launchers"]) < len(attempt["cases"]):
            raise Unverified("captured cases lack launch identity")
        for index, observed in enumerate(attempt["cases"]):
            if not isinstance(observed, dict):
                raise Unverified("invalid observed case")
            streams = []
            for field in ("stdout", "stderr"):
                sha = observed.get(field + "_sha256")
                if not isinstance(sha, str) or not HEX.fullmatch(sha):
                    raise Unverified("invalid stream reference")
                if not check_streams or attempt["phase"] == "EVIDENCE_LOST_STOPPED":
                    continue
                data = c.read_bytes(root / "review-artifacts" / sha, MAX_OUTPUT)
                if digest(data) != sha:
                    raise Unverified("observed stream changed")
                streams.append(data)
            if check_streams and attempt["phase"] != "EVIDENCE_LOST_STOPPED" and evaluate(cases[index], *streams, observed.get("returncode"), observed.get("failure")) != observed:
                raise Unverified("case verdict differs from retained stream")
        for index, launcher in enumerate(attempt["launchers"]):
            if (not isinstance(launcher, dict) or set(launcher) != {"case", "pid", "process_start", "process_status", "identity"}
                    or launcher.get("case") != cases[index]["id"] or type(launcher.get("pid")) is not int or launcher["pid"] <= 0
                    or launcher["process_status"] not in {"alive", "absent", "unknown"}
                    or (launcher["process_status"] == "alive" and not isinstance(launcher["process_start"], str))
                    or launcher["identity"] != "actual Docker CLI child, not guest PID"):
                raise Unverified("invalid launcher identity")
        if "result" in attempt:
            result = attempt["result"]
            if not isinstance(result, dict) or result.get("candidate_ready") is not False or type(result.get("applicable")) is not bool:
                raise Unverified("invalid execution result")
            expected = "UNVERIFIED" if not result["applicable"] or attempt["phase"] == "EVIDENCE_LOST_STOPPED" or len(attempt["cases"]) != len(cases) or any(item["verdict"] == "UNVERIFIED" for item in attempt["cases"]) else (
                "FAIL" if any(item["verdict"] == "FAIL" for item in attempt["cases"]) else "PASS")
            if result.get("oracle_verdict") != expected or attempt["phase"] not in {"CAPTURED", "SETTLED", "EVIDENCE_LOST_STOPPED"}:
                raise Unverified("execution result contradicts observed assertions")
        elif attempt["phase"] not in {"DISPATCHING", "UNKNOWN_STOPPED"}:
            raise Unverified("terminal execution lacks a result")


def active_execution_owner(record: dict[str, Any]) -> bool:
    return (record["state"] in {"Claimed", "Implementing", "Reviewing"}
            and isinstance(record.get("worker"), dict)
            and type(record.get("leases", {}).get("global_slot")) is int)


def applicability(record: dict[str, Any], attempt: dict[str, Any], c) -> bool:
    if (not active_execution_owner(record) or record["owner"] != attempt["owner"] or record.get("transition_intent")):
        return False
    try:
        source_binding(record, attempt["definition"], c)
    except (Unverified, OSError):
        return False
    return True


def finalize(attempt: dict[str, Any], observations: list[dict[str, Any]], applicable: bool) -> None:
    if attempt["phase"] not in {"DISPATCHING", "UNKNOWN_STOPPED"}:
        raise Unverified("attempt no longer permits capture settlement")
    verdict = "UNVERIFIED" if not applicable or len(observations) != len(attempt["definition"]["cases"]) or any(item["verdict"] == "UNVERIFIED" for item in observations) else (
        "FAIL" if any(item["verdict"] == "FAIL" for item in observations) else "PASS")
    attempt.update(phase="SETTLED" if attempt["termination"] == "STOPPED_OBSERVED" else "CAPTURED", cases=observations,
                   result={"oracle_verdict": verdict, "applicable": applicable, "candidate_ready": False,
                           "transport": "controller-captured Docker exec", "guest_descendants": attempt["termination"]})


def exit_code(attempt: dict[str, Any]) -> int:
    if attempt["phase"] != "SETTLED":
        return 3
    return {"PASS": 0, "FAIL": 1}.get(attempt.get("result", {}).get("oracle_verdict"), 3)


def reconcile_stop(record: dict[str, Any], attempt: dict[str, Any], item: dict[str, Any], root: Path, c) -> None:
    definition = attempt["definition"]
    if item.get("Id") != definition["container_id"] or item.get("Created") != definition["created"] or item.get("State", {}).get("Running") is not False:
        raise Unverified("exact container stop is not observed")
    evidence_lost = False
    try:
        validate_attempts({"execution_observations": {attempt["request"]["operation_id"]: attempt}}, root, c)
    except (Unverified, OSError):
        evidence_lost = True
    attempt["termination"] = "STOPPED_OBSERVED"
    attempt["stop_observation"] = {"container_id": definition["container_id"], "created": definition["created"], "running": False}
    if "result" in attempt:
        attempt["phase"] = "DISPATCHING"
        finalize(attempt, attempt["cases"], applicability(record, attempt, c))
        if evidence_lost:
            attempt["phase"] = "EVIDENCE_LOST_STOPPED"
            attempt["evidence_loss"] = "Referenced stream missing or corrupt; stop observation retained separately"
            attempt["result"].update(oracle_verdict="UNVERIFIED", applicable=False)
    else:
        attempt["phase"] = "UNKNOWN_STOPPED"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--definition-sha256", required=True)
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--reconcile-stopped", action="store_true")
    args = parser.parse_args()
    try:
        if not sys.flags.isolated or not sys.dont_write_bytecode or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.operation_id):
            raise Unverified("isolated interpreter and bounded operation ID required")
        c, coordinator, runner = dependency("review-collect"), dependency("orchestrator-state"), dependency("review-run")
        raw = c.read_bytes(args.definition, 200_000)
        if digest(raw) != args.definition_sha256:
            raise Unverified("definition digest mismatch")
        definition = c.decode(raw)
        validate_definition(definition)
        if runner.binary_digest(Path(definition["docker_binary"])) != definition["docker_sha256"]:
            raise Unverified("installed runtime binary mismatch")
        root = coordinator.state_root(create=False)
        config = root / "execution-docker-config"
        c.no_links(config)
        config.mkdir(mode=0o700, exist_ok=True)
        if any(config.iterdir()):
            raise Unverified("runtime config must be private and empty")
        if config.stat().st_uid != os.getuid() or config.stat().st_mode & 0o077:
            raise Unverified("runtime config permissions invalid")
        prefix, env = route(definition, config)
        request = {"operation_id": args.operation_id, "definition_sha256": args.definition_sha256,
                   "expected_revision": args.expected_revision}
        with coordinator.CoordinatorLock(root):
            record = coordinator.read_task(root, args.task_id)
            if args.definition.resolve().is_relative_to(Path(record["worktree"]).resolve()):
                raise Unverified("approved definition must be outside candidate checkout")
            attempts = record.get("execution_observations", {})
            # Reconciliation can release an actually stopped guest after stream
            # loss, but never after loss of its identity/definition binding.
            validate_attempts(record, root, c, check_streams=not args.reconcile_stopped)
            prior = attempts.get(args.operation_id)
            if prior:
                if prior["request"] != request:
                    raise Unverified("operation ID reused with changed request")
                if args.reconcile_stopped:
                    item = inspect_backend(definition, prefix, env)
                    reconcile_stop(record, prior, item, root, c)
                    coordinator.write_task(root, record)
                print(json.dumps(prior, sort_keys=True))
                return exit_code(prior)
            if args.reconcile_stopped:
                raise Unverified("no original execution to reconcile")
            if record["revision"] != args.expected_revision or not active_execution_owner(record):
                raise Unverified("task revision or admission changed")
            if record.get("transition_intent") or any(item.get("termination") != "STOPPED_OBSERVED" for item in attempts.values()) or len(attempts) >= 12:
                raise Unverified("unsettled execution or execution budget exhausted")
            coordinator.verify_reservations(root, record)
            source_binding(record, definition, c)
            inspect_guest(definition, inspect_backend(definition, prefix, env))
            for task_path in (root / "tasks").glob("*/task.json"):
                other = coordinator.read_task(root, task_path.parent.name)
                for existing in other.get("execution_observations", {}).values():
                    if existing["definition"]["container_id"] == definition["container_id"] and existing["definition"]["endpoint"] == definition["endpoint"]:
                        raise Unverified("container already reserved by an execution attempt; provision a fresh guest")
            store = c.ensure_store(root, Path(record["worktree"]))
            c.publish(store, raw)
            directory = os.open(store, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            attempt = {"request": request, "definition": definition, "phase": "DISPATCHING", "termination": "UNVERIFIED",
                       "owner": record["owner"], "head": record["head_sha"], "base": record["base_sha"],
                       "controller_sha256": digest(Path(__file__).read_bytes()), "cases": [], "launchers": []}
            record.setdefault("execution_observations", {})[args.operation_id] = attempt
            coordinator.write_task(root, record)
        # No successful preflight can prove a future backend call succeeded.
        # DISPATCHING is durable before spawn; interruption is never retried.
        observations = []
        for case in definition["cases"]:
            active = None
            @contextlib.contextmanager
            def authorize():
                nonlocal active
                with coordinator.CoordinatorLock(root):
                    active = coordinator.read_task(root, args.task_id)
                    if (active["owner"] != attempt["owner"] or active["head_sha"] != attempt["head"]
                            or active["base_sha"] != attempt["base"] or active.get("transition_intent")
                            or not active_execution_owner(active)):
                        raise Unverified("task changed before dispatch; execution remains unsettled")
                    source_binding(active, definition, c)
                    inspect_guest(definition, inspect_backend(definition, prefix, env))
                    yield
            def started(pid):
                assert active is not None
                process_status, process_start = coordinator.process_identity(pid)
                active["execution_observations"][args.operation_id]["launchers"].append(
                    {"case": case["id"], "pid": pid, "process_start": process_start, "process_status": process_status,
                     "identity": "actual Docker CLI child, not guest PID"})
                coordinator.write_task(root, active)
            out, err, code, failure = capture(prefix + ["exec", definition["container_id"], *case["argv"]], env,
                                             case["timeout"], started, authorize())
            result = evaluate(case, out, err, code, failure)
            c.publish(store, out)
            c.publish(store, err)
            observations.append(result)
            if failure:
                break
        folder = os.open(store, os.O_RDONLY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)
        with coordinator.CoordinatorLock(root):
            current = coordinator.read_task(root, args.task_id)
            retained = current["execution_observations"][args.operation_id]
            if retained["request"] != request:
                raise Unverified("attempt identity changed during capture")
            finalize(retained, observations, applicability(current, retained, c))
            coordinator.write_task(root, current)
            print(json.dumps(retained, sort_keys=True))
        return exit_code(retained)
    except Exception as exc:
        print(json.dumps({"status": "UNVERIFIED", "reason": str(exc) if isinstance(exc, Unverified) else "execution observation unavailable"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
