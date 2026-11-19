"""Cheap structural presence detection only; no imports, I/O or cached evidence.

False means the reservation extension is absent, never that a task is valid.
Malformed containers and orphan actions/references must reach strict validation.
Shared by the foreground dispatcher and coordinator before loading the extension.
"""


def has_reservation_history(record):
    if not isinstance(record, dict):
        return True
    if "review_reservations" in record or "review_reservations_initialized" in record:
        return True
    control = record.get("foreground_control", {})
    if not isinstance(control, dict):
        return True
    receipts = control.get("receipts", {})
    if not isinstance(receipts, dict):
        return True
    for receipt in receipts.values():
        if not isinstance(receipt, dict) or not isinstance(receipt.get("request"), dict):
            return True
        action = receipt["request"].get("action")
        reference = receipt.get("reference")
        if not isinstance(action, str) or action in {"reserve-review-attempt", "cancel-review-reservation"}:
            return True
        if reference is not None and (not isinstance(reference, dict)
                or reference.get("table") == "review_reservations.admissions"):
            return True
    return False
