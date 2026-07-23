"""JSON batch command-line adapter for the canonical entity write engine."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from typing import Any

from .write import (
    Result,
    create_page_if_absent,
    fingerprint_page,
    mutate_page,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class InvalidBatch(ValueError):
    """Raised when the complete request cannot be validated safely."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise InvalidBatch(f"{label} must be an object")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise InvalidBatch(f"{label} must be a string")
    return value


def _optional_mapping(
    value: Any,
    label: str,
) -> Mapping[str, Any] | None:
    if value is None:
        return None
    return _mapping(value, label)


def _optional_strings(value: Any, label: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise InvalidBatch(f"{label} must be an array of strings")
    return value


def _validate_op(candidate: Any, index: int) -> dict[str, Any]:
    label = f"ops[{index}]"
    operation = dict(_mapping(candidate, label))
    kind = _string(operation.get("op"), f"{label}.op")
    operation["path"] = _string(operation.get("path"), f"{label}.path")
    if kind == "create":
        operation["content"] = _string(
            operation.get("content"), f"{label}.content"
        )
        allowed_root = operation.get("allowed_root")
        if allowed_root is not None:
            operation["allowed_root"] = _string(
                allowed_root, f"{label}.allowed_root"
            )
        return operation
    if kind != "mutate":
        raise InvalidBatch(f"{label}.op must be create or mutate")

    base_fingerprint = operation.get("base_fingerprint")
    if not isinstance(base_fingerprint, str) or not _SHA256_RE.fullmatch(
        base_fingerprint
    ):
        raise InvalidBatch(
            f"{label}.base_fingerprint must be a SHA-256 hex string"
        )
    operation["field_changes"] = _optional_mapping(
        operation.get("field_changes"), f"{label}.field_changes"
    )
    replacement_content = operation.get("replacement_content")
    if replacement_content is not None:
        operation["replacement_content"] = _string(
            replacement_content, f"{label}.replacement_content"
        )
    operation["ensure_regions"] = _optional_strings(
        operation.get("ensure_regions"), f"{label}.ensure_regions"
    )
    operation["region_projections"] = _optional_mapping(
        operation.get("region_projections"), f"{label}.region_projections"
    )
    return operation


def _validate_request(candidate: Any) -> list[dict[str, Any]]:
    request = _mapping(candidate, "request")
    operations = request.get("ops")
    if not isinstance(operations, list):
        raise InvalidBatch("request.ops must be an array")
    return [
        _validate_op(operation, index)
        for index, operation in enumerate(operations)
    ]


def _apply(operation: Mapping[str, Any]) -> Result:
    if operation["op"] == "create":
        result = create_page_if_absent(
            operation["path"],
            operation["content"],
            allowed_root=operation.get("allowed_root"),
        )
        if result.status == "exists":
            try:
                return Result("exists", False, fingerprint_page(operation["path"]))
            except OSError:
                return result
        return result
    return mutate_page(
        operation["path"],
        operation["base_fingerprint"],
        replacement_content=operation.get("replacement_content"),
        field_changes=operation.get("field_changes"),
        ensure_regions=operation.get("ensure_regions"),
        region_projections=operation.get("region_projections"),
    )


def run(payload: Any) -> dict[str, Any]:
    """Validate the whole batch, then apply its operations in request order."""
    operations = _validate_request(payload)
    results = []
    for operation in operations:
        result = _apply(operation)
        results.append(
            {
                "path": operation["path"],
                "status": result.status,
                "fingerprint": result.fingerprint,
            }
        )
    return {"results": results}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        response = run(payload)
    except (InvalidBatch, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "invalid_batch",
                        "message": str(error),
                    }
                },
                sort_keys=True,
            )
        )
        return 2
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        print(
            json.dumps(
                {
                    "error": {
                        "code": "engine_failure",
                        "message": str(error),
                    }
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(response, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
