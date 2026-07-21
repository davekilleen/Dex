"""Schema-backed loading and identity verification for release catalogs."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

from core.lifecycle.model import CatalogError, CatalogModelError, ReleaseCatalog

SCHEMA_PATH = Path(__file__).with_name("schemas") / "release-catalog-v1.schema.json"
SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://dex/contracts/release-catalog-v1.schema.json"
_SUPPORTED_SCHEMA_KEYWORDS = {
    "$id",
    "$schema",
    "additionalProperties",
    "const",
    "enum",
    "items",
    "maxItems",
    "minItems",
    "minLength",
    "pattern",
    "properties",
    "required",
    "title",
    "type",
    "uniqueItems",
}


class CatalogSchemaError(CatalogError):
    """The document does not satisfy the committed schema."""


class CatalogParseError(CatalogError):
    """The document is not valid JSON or cannot be modeled."""


class CatalogIdentityError(CatalogError):
    """A hash or release identity cannot be proved."""


def _fail(error_type: type[CatalogError], message: str) -> None:
    raise error_type(f"catalog state is UNKNOWN: {message}")


def _strict_json_loads(
    text: str, *, error_type: type[CatalogError], context: str
) -> object:
    def closed_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for field, value in pairs:
            if field in result:
                _fail(error_type, f"{context} repeats JSON field {field!r}")
            result[field] = value
        return result

    def reject_nonfinite(value: str) -> None:
        _fail(error_type, f"{context} contains non-finite JSON number {value}")

    try:
        return json.loads(
            text,
            object_pairs_hook=closed_object,
            parse_constant=reject_nonfinite,
        )
    except (TypeError, json.JSONDecodeError) as error:
        _fail(error_type, f"{context} JSON cannot be parsed: {error}")


def _type_matches(value: object, expected: str) -> bool:
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "boolean": type(value) is bool,
        "null": value is None,
    }.get(expected, False)


def _validate_schema_node(value: object, schema: object, location: str) -> None:
    if not isinstance(schema, Mapping):
        _fail(CatalogSchemaError, f"schema node at {location} is not an object")
    unknown_keywords = set(schema) - _SUPPORTED_SCHEMA_KEYWORDS
    if unknown_keywords:
        _fail(
            CatalogSchemaError,
            f"schema node at {location} uses unsupported keywords: "
            + ", ".join(sorted(unknown_keywords)),
        )
    expected_type = schema.get("type")
    if expected_type is not None:
        if not isinstance(expected_type, str) or not _type_matches(value, expected_type):
            _fail(CatalogSchemaError, f"{location} must have JSON type {expected_type}")
    if "const" in schema and value != schema["const"]:
        _fail(CatalogSchemaError, f"{location} must equal {schema['const']!r}")
    if "enum" in schema:
        choices = schema["enum"]
        if not isinstance(choices, list) or value not in choices:
            _fail(CatalogSchemaError, f"{location} has an unknown value")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            _fail(CatalogSchemaError, f"{location} is too short")
        if "pattern" in schema:
            pattern = schema["pattern"]
            if not isinstance(pattern, str) or re.search(pattern, value) is None:
                _fail(CatalogSchemaError, f"{location} does not match its closed pattern")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            _fail(CatalogSchemaError, f"{location} has too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            _fail(CatalogSchemaError, f"{location} has too many items")
        if schema.get("uniqueItems") is True:
            encoded = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(set(encoded)) != len(encoded):
                _fail(CatalogSchemaError, f"{location} contains duplicate items")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                _validate_schema_node(item, item_schema, f"{location}[{index}]")

    if isinstance(value, Mapping):
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(field, str) for field in required):
            _fail(CatalogSchemaError, f"schema required list at {location} is malformed")
        for field in required:
            if field not in value:
                _fail(CatalogSchemaError, f"{location} is missing required field {field!r}")
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            _fail(CatalogSchemaError, f"schema properties at {location} is malformed")
        additional = schema.get("additionalProperties", True)
        for field, child in value.items():
            if field in properties:
                _validate_schema_node(child, properties[field], f"{location}.{field}")
            elif additional is False:
                _fail(CatalogSchemaError, f"{location} has unknown field {field!r}")
            elif isinstance(additional, Mapping):
                _validate_schema_node(child, additional, f"{location}.{field}")


def load_catalog_schema(schema_path: Path = SCHEMA_PATH) -> dict[str, object]:
    try:
        text = Path(schema_path).read_text(encoding="utf-8")
    except OSError as error:
        _fail(CatalogSchemaError, f"cannot load the catalog schema: {error}")
    raw = _strict_json_loads(text, error_type=CatalogSchemaError, context="catalog schema")
    if not isinstance(raw, dict):
        _fail(CatalogSchemaError, "catalog schema root is not an object")
    if raw.get("$schema") != SCHEMA_DRAFT or raw.get("$id") != SCHEMA_ID:
        _fail(CatalogSchemaError, "catalog schema identity or draft is unknown")
    return raw


def validate_catalog_document(
    document: object, *, schema_path: Path = SCHEMA_PATH
) -> None:
    """Validate a JSON-like value against the committed schema using stdlib."""
    _validate_schema_node(document, load_catalog_schema(schema_path), "catalog")


def _canonical_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        _fail(CatalogParseError, f"catalog cannot be serialized canonically: {error}")


def canonical_identity_bytes(document: Mapping[str, object]) -> bytes:
    """Canonical bytes covered by catalog_sha256 (integrity envelope excluded)."""
    payload = {key: value for key, value in document.items() if key != "integrity"}
    return _canonical_bytes(payload)


def compute_catalog_sha256(document: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_identity_bytes(document)).hexdigest()


def with_catalog_identity(document: Mapping[str, object]) -> dict[str, object]:
    """Return a copy with catalog_sha256 bound to its canonical payload."""
    result = copy.deepcopy(dict(document))
    integrity = result.get("integrity")
    if not isinstance(integrity, dict):
        _fail(CatalogParseError, "catalog integrity envelope is missing")
    integrity["catalog_sha256"] = compute_catalog_sha256(result)
    signatures = integrity.get("signatures")
    if isinstance(signatures, list):
        for signature in signatures:
            if isinstance(signature, dict):
                signature["signed_sha256"] = integrity["catalog_sha256"]
    return result


def canonical_catalog_bytes(catalog: ReleaseCatalog | Mapping[str, object]) -> bytes:
    document = catalog.to_dict() if isinstance(catalog, ReleaseCatalog) else dict(catalog)
    return _canonical_bytes(document)


def _verify_identity(catalog: ReleaseCatalog, document: Mapping[str, object], manifest_bytes: bytes) -> None:
    expected = compute_catalog_sha256(document)
    if catalog.integrity.catalog_sha256 != expected:
        _fail(
            CatalogIdentityError,
            "catalog_sha256 does not match the exact canonical catalog payload",
        )
    if not isinstance(manifest_bytes, bytes):
        _fail(CatalogIdentityError, "release manifest bytes were not supplied as bytes")
    actual_manifest = hashlib.sha256(manifest_bytes).hexdigest()
    if catalog.release.manifest.sha256 != actual_manifest:
        _fail(CatalogIdentityError, "release manifest bytes do not match the catalog binding")


def loads_catalog(text: str, *, manifest_bytes: bytes) -> ReleaseCatalog:
    """Parse, schema-check, model, and identity-check one catalog document."""
    document = _strict_json_loads(text, error_type=CatalogParseError, context="catalog")
    validate_catalog_document(document)
    try:
        catalog = ReleaseCatalog.from_dict(document)
    except CatalogModelError:
        raise
    from core.lifecycle.handlers import DEFAULT_REGISTRY

    for item in catalog.items:
        DEFAULT_REGISTRY.resolve(item.kind)
    assert isinstance(document, Mapping)
    _verify_identity(catalog, document, manifest_bytes)
    return catalog


def load_catalog(path: Path, *, release_root: Path) -> ReleaseCatalog:
    """Load a catalog and verify its bound manifest from one release tree."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        _fail(CatalogParseError, f"cannot read catalog document: {error}")
    try:
        document = _strict_json_loads(text, error_type=CatalogParseError, context="catalog")
        validate_catalog_document(document)
        modeled = ReleaseCatalog.from_dict(document)
    except CatalogModelError:
        raise
    root = Path(release_root).resolve()
    manifest_path = (root / modeled.release.manifest.path).resolve()
    if not manifest_path.is_relative_to(root):
        _fail(CatalogIdentityError, "manifest binding escapes the release root")
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as error:
        _fail(CatalogIdentityError, f"cannot verify the bound release manifest: {error}")
    return loads_catalog(text, manifest_bytes=manifest_bytes)


__all__ = [
    "CatalogError",
    "CatalogIdentityError",
    "CatalogParseError",
    "CatalogSchemaError",
    "canonical_catalog_bytes",
    "canonical_identity_bytes",
    "compute_catalog_sha256",
    "load_catalog",
    "load_catalog_schema",
    "loads_catalog",
    "validate_catalog_document",
    "with_catalog_identity",
]
