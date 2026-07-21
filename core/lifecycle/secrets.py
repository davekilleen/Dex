"""Hard-deny redaction shared by every lifecycle report."""

from __future__ import annotations

import copy
from collections.abc import Mapping

from core import portable_contract

SENSITIVE_METADATA_FIELDS = frozenset(
    {"bytes", "content", "digest", "hash", "sha", "sha256", "size"}
)
PATH_FIELDS = ("path", "actual_path", "canonical_path")


class RedactionViolation(ValueError):
    """A report exposes metadata for a hard-denied path."""


def _denied_record(value: Mapping[str, object]) -> bool:
    for field in PATH_FIELDS:
        path = value.get(field)
        if isinstance(path, str):
            try:
                if portable_contract.is_denied(path):
                    return True
            except portable_contract.ContractViolation:
                continue
    return False


def redact_document(value: object) -> object:
    """Deep-copy a JSON-like value and scrub denied-path metadata."""
    if isinstance(value, Mapping):
        denied = _denied_record(value)
        result: dict[str, object] = {}
        for key, child in value.items():
            if denied and str(key).casefold() in SENSITIVE_METADATA_FIELDS:
                continue
            result[str(key)] = redact_document(child)
        if denied:
            result["redacted"] = True
        return result
    if isinstance(value, (list, tuple)):
        return [redact_document(child) for child in value]
    return copy.deepcopy(value)


def assert_no_denied_metadata(value: object) -> None:
    """E1 output gate: fail if a denied record carries size/hash/content."""
    if isinstance(value, Mapping):
        if _denied_record(value):
            exposed = SENSITIVE_METADATA_FIELDS.intersection(str(key).casefold() for key in value)
            if exposed:
                raise RedactionViolation(
                    "hard-denied path exposes forbidden metadata: " + ", ".join(sorted(exposed))
                )
            if value.get("redacted") is not True:
                raise RedactionViolation("hard-denied path is not marked redacted")
        for child in value.values():
            assert_no_denied_metadata(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            assert_no_denied_metadata(child)


__all__ = [
    "RedactionViolation",
    "SENSITIVE_METADATA_FIELDS",
    "assert_no_denied_metadata",
    "redact_document",
]
