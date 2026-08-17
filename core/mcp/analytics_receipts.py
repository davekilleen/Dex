"""One safe way for MCP callers to surface a failed analytics receipt."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping

_SAFE_RECEIPT_FAILURE = {
    "written": False,
    "reason": "receipt_write_failed",
}


def unavailable_analytics_delivery() -> dict[str, object]:
    """Return the fixed outcome when the shared analytics helper is unavailable."""
    return {
        "fired": False,
        "receipt_written": False,
        "receipt_reason": "receipt_write_failed",
    }


def receipt_failure_status(delivery: object) -> dict[str, object] | None:
    """Expose a receipt failure without carrying delivery or exception details."""
    if (
        isinstance(delivery, Mapping)
        and delivery.get("receipt_written") is False
        and delivery.get("receipt_reason") == "receipt_write_failed"
    ):
        return dict(_SAFE_RECEIPT_FAILURE)
    return None


def surface_analytics_attempt(
    result: MutableMapping[str, object],
    fire_event: Callable[[str, object], object],
    event_name: str,
    properties: object = None,
) -> dict[str, object] | None:
    """Record one attempt and attach only a fixed receipt failure to its result."""
    try:
        delivery = fire_event(event_name, properties)
    except Exception:
        delivery = unavailable_analytics_delivery()
    receipt_failure = receipt_failure_status(delivery)
    if receipt_failure is not None:
        result["analytics_receipt"] = receipt_failure
    return receipt_failure
