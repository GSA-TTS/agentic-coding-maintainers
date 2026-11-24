"""Pure, bounded Linux text-profile parser; no collection or admission authority."""

U64_MAX = (1 << 64) - 1
METRICS = (
    "cpu.max", "memory.max", "memory.current",
    "cpu.pressure", "memory.pressure", "io.pressure",
)
REASONS = (
    "not_collected", "not_visible", "permission_denied", "unsupported",
    "inapplicable", "read_failed",
)
IDENTITY_FIELDS = (
    "producer_id", "producer_version", "collector_instance_id", "domain_id",
    "boot_id", "clock_domain_id",
)
CONTEXT_FIELDS = IDENTITY_FIELDS + (
    "backing", "start_ns", "end_ns", "sequence", "policy_digest", "config_digest",
)
PSI_FIELDS = ("avg10", "avg60", "avg300", "total")
ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


class ParseError(ValueError):
    """Refusal with a fixed code/message, never interpolated source data."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _record(value, fields):
    # Check exact types before key comparisons, lookup or value operations.
    if type(value) is not dict:
        raise ParseError("SHAPE")
    if len(value) > len(fields):
        raise ParseError("UNKNOWN_FIELD")
    for key in value:
        if type(key) is not str:
            raise ParseError("SHAPE")
        if key not in fields:
            raise ParseError("UNKNOWN_FIELD")
    if len(value) != len(fields):
        raise ParseError("SHAPE")


def _opaque(value):
    if type(value) is not str:
        raise ParseError("SHAPE")
    if len(value) > 256:
        raise ParseError("LIMIT")
    if not value or value[0] not in ALNUM:
        raise ParseError("SHAPE")
    if any(char not in ALNUM + "._:/@+-" for char in value):
        raise ParseError("SHAPE")
    return value


def _u64(value):
    if type(value) is not int:
        raise ParseError("SHAPE")
    if not 0 <= value <= U64_MAX:
        raise ParseError("RANGE")
    return value


def _digest(value):
    if type(value) is not str:
        raise ParseError("SHAPE")
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ParseError("SHAPE")
    return value


def _context(context):
    _record(context, CONTEXT_FIELDS)
    copied: dict = {key: _opaque(context[key]) for key in IDENTITY_FIELDS}
    backing = context["backing"]
    # Validate the discriminator without invoking subclass equality methods.
    if type(backing) is not dict:
        raise ParseError("SHAPE")
    if len(backing) > 2:
        raise ParseError("UNKNOWN_FIELD")
    for key in backing:
        if type(key) is not str:
            raise ParseError("SHAPE")
    kind = backing.get("kind")
    if type(kind) is not str:
        raise ParseError("SHAPE")
    if kind == "declared":
        _record(backing, ("kind", "domain_id"))
        copied["backing"] = {"kind": "declared", "domain_id": _opaque(backing["domain_id"])}
    elif kind == "unavailable":
        _record(backing, ("kind",))
        copied["backing"] = {"kind": "unavailable"}
    else:
        raise ParseError("SHAPE")
    for key in ("start_ns", "end_ns", "sequence"):
        copied[key] = _u64(context[key])
    if copied["start_ns"] > copied["end_ns"]:
        raise ParseError("RANGE")
    for key in ("policy_digest", "config_digest"):
        copied[key] = _digest(context[key])
    return copied


def _decimal(token):
    if len(token) > 20:
        raise ParseError("LIMIT")
    if not token or any(char not in "0123456789" for char in token):
        raise ParseError("DECIMAL")
    if len(token) > 1 and token[0] == "0":
        raise ParseError("DECIMAL")
    value = int(token)
    if value > U64_MAX:
        raise ParseError("RANGE")
    return value


def _average(token):
    parts = token.split(".")
    if len(parts) != 2 or len(parts[1]) != 2:
        raise ParseError("DECIMAL")
    whole, fraction = parts
    if any(char not in "0123456789" for char in fraction):
        raise ParseError("DECIMAL")
    value = _decimal(whole) * 100 + int(fraction)
    if value > 10000:
        raise ParseError("RANGE")
    return value


def _text(source, metric):
    _record(source, ("kind", "text", "complete"))
    text = source["text"]
    if type(text) is not str or type(source["complete"]) is not bool:
        raise ParseError("SHAPE")
    limit = 1024 if metric.endswith(".pressure") else 128
    # No encode, split, strip, or numeric conversion before this raw-size gate.
    # ASCII is one byte per character; overlong non-ASCII also refuses here.
    if len(text) > limit:
        raise ParseError("LIMIT")
    if not text.isascii() or any(
        char not in "\t\n" and not " " <= char <= "~" for char in text
    ):
        raise ParseError("ENCODING")
    if not source["complete"] or not text.endswith("\n"):
        raise ParseError("INCOMPLETE")
    return text[:-1]


def _scalar(metric, text):
    if "\n" in text:
        raise ParseError("SHAPE")
    tokens = text.split()
    if not tokens:
        raise ParseError("INCOMPLETE")
    expected = 2 if metric == "cpu.max" else 1
    if len(tokens) < expected:
        raise ParseError("INCOMPLETE")
    if len(tokens) > expected:
        raise ParseError("SHAPE")
    if metric == "cpu.max":
        period = _decimal(tokens[1])
        if not 1000 <= period <= 1000000:
            raise ParseError("RANGE")
        quota: dict = {"kind": "unlimited"}
        if tokens[0] != "max":
            value = _decimal(tokens[0])
            if value < 1000:
                raise ParseError("RANGE")
            quota = {"kind": "finite", "value": value}
        return {"kind": "cpu_quota", "unit": "microseconds", "quota": quota, "period": period}
    if metric == "memory.max" and tokens[0] == "max":
        return {"kind": "unlimited", "unit": "bytes"}
    return {"kind": "finite", "unit": "bytes", "value": _decimal(tokens[0])}


def _pressure(text):
    if not text.strip(" \t"):
        raise ParseError("INCOMPLETE")
    rows = {}
    incomplete = False
    for line in text.split("\n"):
        tokens = line.split()
        if not tokens:
            raise ParseError("SHAPE")
        row = tokens[0]
        if row not in ("some", "full"):
            raise ParseError("UNKNOWN_FIELD")
        if row in rows:
            raise ParseError("DUPLICATE_FIELD")
        fields = {}
        for token in tokens[1:]:
            if token.count("=") != 1:
                raise ParseError("SHAPE")
            key, value = token.split("=")
            if key not in PSI_FIELDS:
                raise ParseError("UNKNOWN_FIELD")
            if key in fields:
                raise ParseError("DUPLICATE_FIELD")
            fields[key] = _decimal(value) if key == "total" else _average(value)
        if len(fields) != len(PSI_FIELDS):
            incomplete = True
        rows[row] = fields
    if len(rows) != 2 or incomplete:
        raise ParseError("INCOMPLETE")
    return {
        "kind": "pressure",
        "average_unit": "percent_hundredths",
        "total_unit": "microseconds",
        "rows": rows,
    }


def parse_sample(metric, source, context):
    """Return a fresh inert observation or raise ParseError with a fixed code.

    Caller-supplied context is asserted, not verified. See CAPACITY-LINUX-PARSER.md
    for the closed profile; this function does not establish freshness or health.
    """
    if type(metric) is not str or metric not in METRICS:
        raise ParseError("SHAPE")
    copied = _context(context)
    if type(source) is not dict:
        raise ParseError("SHAPE")
    if len(source) > 3:
        raise ParseError("UNKNOWN_FIELD")
    for key in source:
        if type(key) is not str:
            raise ParseError("SHAPE")
    kind = source.get("kind")
    if type(kind) is not str:
        raise ParseError("SHAPE")
    if kind == "unavailable":
        _record(source, ("kind", "reason"))
        reason = source["reason"]
        if type(reason) is not str or reason not in REASONS:
            raise ParseError("SHAPE")
        result = {"kind": "unavailable", "reason": reason}
    elif kind == "text":
        text = _text(source, metric)
        result = _pressure(text) if metric.endswith(".pressure") else _scalar(metric, text)
    else:
        raise ParseError("SHAPE")
    return {
        "format": "capacity-linux-observation",
        "version": 1,
        "metric": metric,
        "context": copied,
        "duration_ns": copied["end_ns"] - copied["start_ns"],
        "result": result,
    }
