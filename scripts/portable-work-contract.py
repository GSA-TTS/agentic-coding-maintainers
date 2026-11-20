"""Inert portable-work-bundle/version1 validation; no CLI or runtime binding.

Only internal consistency is checked. Success is not authority, freshness,
accepted evidence, admission, or permission to execute anything in the document.
"""

import json
import re

MAX_BYTES = 262144
MAX_DEPTH = 16
MAX_NODES = 16384
MAX_ITEMS = 128
MAX_STRING = 4096
MAX_INTEGER = 9007199254740991
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}", re.ASCII)
_UNITS = {
    "cpu": "millicores", "memory": "bytes", "storage": "bytes",
    "workers": "count", "provider_concurrent": "count",
}


class ContractError(ValueError):
    """A fixed diagnostic code, without untrusted document text."""


def _require(condition, code="SHAPE"):
    if not condition:
        raise ContractError(code)


def _bounded(value):
    # Iterative, exact built-in types only: no user hooks, cycles, or coercion.
    stack = [(value, 0)]
    count = 0
    string_bytes = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        _require(count <= MAX_NODES and depth <= MAX_DEPTH, "LIMIT")
        if type(item) is dict:
            _require(len(item) <= MAX_ITEMS, "LIMIT")
            for key, child in item.items():
                _require(type(key) is str)
                stack.extend(((key, depth + 1), (child, depth + 1)))
        elif type(item) is list:
            _require(len(item) <= MAX_ITEMS, "LIMIT")
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            _require(len(item) <= MAX_STRING, "LIMIT")
            _require(not any(0xD800 <= ord(char) <= 0xDFFF for char in item), "JSON")
            string_bytes += len(item.encode("utf-8"))
            _require(string_bytes <= MAX_BYTES, "LIMIT")
        elif type(item) is int:
            _require(0 <= item <= MAX_INTEGER, "INTEGER")
        else:
            raise ContractError("TYPE")


def _object(value, required, optional=()):
    _require(type(value) is dict)
    _require(set(required) <= value.keys() <= set(required) | set(optional))


def _text(value):
    _require(type(value) is str and 1 <= len(value) <= MAX_STRING)


def _id(value):
    _require(type(value) is str and _ID.fullmatch(value) is not None, "IDENTITY")


def _integer(value, minimum=0):
    _require(type(value) is int and minimum <= value <= MAX_INTEGER, "INTEGER")


def _revision(value):
    _object(value, ("kind", "value"))
    _require(value["kind"] == "exact")
    _id(value["value"])


def _ref(value):
    _object(value, ("id", "revision"))
    _id(value["id"])
    _revision(value["revision"])


def _list(value, minimum=0):
    _require(type(value) is list and minimum <= len(value) <= MAX_ITEMS)


def _ids(value, minimum=0):
    _list(value, minimum)
    for item in value:
        _id(item)
    _require(len(set(value)) == len(value), "DUPLICATE_ID")


def _index(values, minimum=0):
    _list(values, minimum)
    result = {}
    for value in values:
        _require(type(value) is dict and "id" in value)
        _id(value["id"])
        _require(value["id"] not in result, "DUPLICATE_ID")
        result[value["id"]] = value
    return result


def _refs(values, minimum=0):
    result = _index(values, minimum)
    for value in values:
        _ref(value)
    return result


def _lookup(index, key):
    _id(key)
    _require(key in index, "REFERENCE")
    return index[key]


def _subset(actual, expected, code="DEPENDENCY"):
    for key, value in actual.items():
        _require(key in expected and value == expected[key], code)


def _binding(value):
    _require(type(value) is dict and "schema" in value)
    _require(type(value["schema"]) is int and value["schema"] in (2, 3), "BINDING")
    fields = ("schema", "task_id", "task_revision", "task_digest")
    if value["schema"] == 3:
        fields += ("session_id", "generation")
    _object(value, fields)
    _id(value["task_id"])
    _revision(value["task_revision"])
    _id(value["task_digest"])
    if value["schema"] == 3:
        _id(value["session_id"])
        _integer(value["generation"], 1)


def _capacity(value, attempt, run, work):
    _object(value, ("kind", "work_id", "run_id", "operation_id", "attempt_id",
                    "domain_id", "class", "policy_revision", "config_revision",
                    "resources", "max_fanout", "duration_seconds", "max_retries"))
    _require(value["kind"] == "request")
    for field, expected in (("work_id", work["id"]), ("run_id", run["id"]),
                            ("operation_id", attempt["operation_id"]),
                            ("attempt_id", attempt["id"])):
        _require(value[field] == expected, "REFERENCE")
    _id(value["domain_id"])
    _require(value["class"] in ("remote_static", "implementation",
                               "heavy_validation", "vm_start_provision"))
    _revision(value["policy_revision"])
    _revision(value["config_revision"])
    for field in ("max_fanout", "duration_seconds", "max_retries"):
        _integer(value[field])
    _object(value["resources"], (), tuple(_UNITS))
    _require(bool(value["resources"]))
    for resource, quantity in value["resources"].items():
        _object(quantity, ("quantity", "unit"))
        _integer(quantity["quantity"])
        _require(quantity["unit"] == _UNITS[resource], "UNIT")


def _operation(operations, operation_id, content):
    _id(operation_id)
    _require(operation_id not in operations or operations[operation_id] == content,
             "OPERATION_CONFLICT")
    operations[operation_id] = content


def _work_and_workflow(bundle):
    work, workflow = bundle["work"], bundle["workflow"]
    _object(work, ("id", "revision", "outcome", "authority", "inputs",
                   "constraints", "acceptance", "profile"))
    _id(work["id"])
    _revision(work["revision"])
    _text(work["outcome"])
    _ref(work["authority"])
    inputs = _refs(work["inputs"], 1)
    _list(work["constraints"])
    for constraint in work["constraints"]:
        _text(constraint)
    acceptance = _index(work["acceptance"], 1)
    for item in acceptance.values():
        _object(item, ("id", "description"))
        _text(item["description"])
    profile = work["profile"]
    _require(type(profile) is dict and "kind" in profile)
    if profile["kind"] == "coding":
        _object(profile, ("kind", "repository", "source"))
        _id(profile["repository"])
        source = profile["source"]
        if not isinstance(source, dict):
            raise ContractError("SHAPE")
        _ref(source)
        _subset({source["id"]: source}, inputs)
    else:
        _object(profile, ("kind",))
        _require(profile["kind"] == "documents")
    _object(workflow, ("id", "revision", "steps"))
    _id(workflow["id"])
    _revision(workflow["revision"])
    steps = _index(workflow["steps"], 1)
    for step in steps.values():
        _object(step, ("id", "description"))
        _text(step["description"])
    return work, workflow, inputs, acceptance, steps


def _runs_and_attempts(bundle, work, steps):
    runs = _index(bundle["runs"], 1)
    for run in runs.values():
        _object(run, ("id", "work_id", "work_revision", "workflow_revision",
                      "inputs", "configurations", "budget"), ("coordinator",))
        _require(run["work_id"] == work["id"], "REFERENCE")
        _revision(run["work_revision"])
        _revision(run["workflow_revision"])
        _refs(run["inputs"], 1)
        _refs(run["configurations"])
        _object(run["budget"], ("duration_seconds", "model_calls", "currency_micros"))
        for quantity in run["budget"].values():
            _integer(quantity)
        if "coordinator" in run:
            _binding(run["coordinator"])
    attempts = _index(bundle["attempts"], 1)
    operations = {}
    for attempt in attempts.values():
        _object(attempt, ("id", "run_id", "operation_id", "step_id"),
                ("parent_attempt_id", "coordinator", "capacity"))
        run = _lookup(runs, attempt["run_id"])
        _lookup(steps, attempt["step_id"])
        if "coordinator" in attempt:
            _binding(attempt["coordinator"])
        _require(attempt.get("coordinator") == run.get("coordinator"), "BINDING")
        capacity = attempt.get("capacity")
        if capacity is not None:
            _capacity(capacity, attempt, run, work)
            capacity = {key: value for key, value in capacity.items()
                        if key not in ("run_id", "attempt_id")}
        # Context labels do not reset logical identity. Reference order is inert.
        content = ("attempt", work["id"], run["work_revision"],
                   bundle["workflow"]["id"], run["workflow_revision"],
                   _refs(run["inputs"]), _refs(run["configurations"]),
                   run["budget"], attempt["step_id"], capacity,
                   run.get("coordinator"))
        _operation(operations, attempt["operation_id"], content)
    for attempt in attempts.values():
        seen = {attempt["id"]}
        current = attempt
        while "parent_attempt_id" in current:
            parent = _lookup(attempts, current["parent_attempt_id"])
            _require(parent["operation_id"] == attempt["operation_id"], "REFERENCE")
            _require(parent["id"] not in seen, "REFERENCE")
            seen.add(parent["id"])
            current = parent
    return runs, attempts, operations


def _artifacts_and_evidence(bundle, runs, attempts, acceptance):
    artifacts = _index(bundle["artifacts"], 1)
    for artifact in artifacts.values():
        _object(artifact, ("id", "revision", "kind", "producer_attempt_id", "provenance"))
        _revision(artifact["revision"])
        _require(artifact["kind"] in ("patch", "report", "verification"))
        attempt = _lookup(attempts, artifact["producer_attempt_id"])
        run = runs[attempt["run_id"]]
        _subset(_refs(artifact["provenance"], 1), _refs(run["inputs"]))
    evidence = _index(bundle["evidence"])
    for record in evidence.values():
        _object(record, ("id", "producer_attempt_id", "artifact", "subject",
                         "acceptance_id", "inputs", "configurations", "workflow_revision"))
        producer = _lookup(attempts, record["producer_attempt_id"])
        run = runs[producer["run_id"]]
        _lookup(acceptance, record["acceptance_id"])
        for field in ("artifact", "subject"):
            _ref(record[field])
            artifact = _lookup(artifacts, record[field]["id"])
            _require(record[field]["revision"] == artifact["revision"], "REVISION")
            other = attempts[artifact["producer_attempt_id"]]
            _require(other["run_id"] == producer["run_id"], "CROSS_RUN")
            if field == "artifact":
                _require(artifact["kind"] == "verification")
                _require(artifact["producer_attempt_id"] == producer["id"], "REFERENCE")
        _subset(_refs(record["inputs"], 1), _refs(run["inputs"]))
        for field in ("artifact", "subject"):
            _subset(_refs(artifacts[record[field]["id"]]["provenance"]),
                    _refs(record["inputs"]), "DEPENDENCY")
        _subset(_refs(record["configurations"]), _refs(run["configurations"]))
        _revision(record["workflow_revision"])
        _require(record["workflow_revision"] == run["workflow_revision"], "REVISION")
    return artifacts, evidence


def _target(bundle, inputs, workflow, artifacts, evidence):
    target = bundle["target"]
    _object(target, ("subject", "inputs", "configurations", "workflow_revision", "support"))
    _ref(target["subject"])
    subject = _lookup(artifacts, target["subject"]["id"])
    _require(subject["revision"] == target["subject"]["revision"], "REVISION")
    _require(_refs(target["inputs"], 1) == inputs, "DEPENDENCY")
    configurations = _refs(target["configurations"])
    _revision(target["workflow_revision"])
    _require(target["workflow_revision"] == workflow["revision"], "REVISION")
    _ids(target["support"])
    for evidence_id in target["support"]:
        record = _lookup(evidence, evidence_id)
        _require(record["subject"] == target["subject"], "APPLICABILITY")
        _require(record["workflow_revision"] == target["workflow_revision"], "APPLICABILITY")
        _subset(_refs(record["inputs"]), inputs, "APPLICABILITY")
        _subset(_refs(record["configurations"]), configurations, "APPLICABILITY")


def _effects(bundle, attempts, runs, artifacts, operations):
    effects = bundle.get("effects", [])
    _list(effects)
    for effect in effects:
        _object(effect, ("kind", "operation_id", "attempt_id", "artifact", "target",
                         "authority", "precondition", "observation"))
        _require(effect["kind"] in ("export-artifact", "publish-artifact"))
        attempt = _lookup(attempts, effect["attempt_id"])
        _ref(effect["artifact"])
        artifact = _lookup(artifacts, effect["artifact"]["id"])
        _require(effect["artifact"]["revision"] == artifact["revision"], "REVISION")
        _require(attempts[artifact["producer_attempt_id"]]["run_id"] == attempt["run_id"],
                 "CROSS_RUN")
        _ref(effect["authority"])
        _id(effect["target"])
        _revision(effect["precondition"])
        _require(effect["observation"] in ("unobserved", "unknown", "reported"))
        content = {key: value for key, value in effect.items()
                   if key not in ("attempt_id", "observation")}
        content["work_id"] = runs[attempt["run_id"]]["work_id"]
        _operation(operations, effect["operation_id"], ("effect", content))


def validate_bundle(value):
    """Return None for internal consistency, otherwise raise ContractError.

    Accept only bounded built-in JSON values; leave the caller's value unchanged.
    No external references are resolved, and no completion/admission is decided.
    """
    _bounded(value)
    # Same compact UTF-8 size bound for direct values and decoded JSON values.
    _require(len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
             <= MAX_BYTES, "LIMIT")
    _object(value, ("kind", "version", "work", "workflow", "runs", "attempts",
                    "artifacts", "evidence", "target"), ("effects",))
    _require(value["kind"] == "portable-work-bundle" and
             type(value["version"]) is int and value["version"] == 1, "VERSION")
    work, workflow, inputs, acceptance, steps = _work_and_workflow(value)
    runs, attempts, operations = _runs_and_attempts(value, work, steps)
    artifacts, evidence = _artifacts_and_evidence(value, runs, attempts, acceptance)
    _target(value, inputs, workflow, artifacts, evidence)
    _effects(value, attempts, runs, artifacts, operations)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "DUPLICATE_KEY")
        result[key] = value
    return result


def _parse_int(text):
    _require(len(text) <= 16 and not text.startswith("-"), "INTEGER")
    value = int(text)
    _integer(value)
    return value


def _no_number(_text):
    raise ContractError("INTEGER")


def decode_bundle(data):
    """Decode bounded UTF-8 JSON bytes and validate; return the decoded bundle."""
    _require(type(data) is bytes, "TYPE")
    _require(len(data) <= MAX_BYTES, "LIMIT")
    try:
        text = data.decode("utf-8")
        # Reject excessive nesting before the recursive standard-library parser.
        depth, quoted, escaped = 0, False, False
        for char in text:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                _require(depth <= MAX_DEPTH, "LIMIT")
            elif char in "]}":
                depth -= 1
        value = json.loads(text, object_pairs_hook=_pairs, parse_int=_parse_int,
                           parse_float=_no_number, parse_constant=_no_number)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ContractError("JSON") from None
    validate_bundle(value)
    return value
