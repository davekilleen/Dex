"""Frozen lifecycle-service API contract coverage."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from core.lifecycle import service
from core.lifecycle.bridge import ACTIVATION_RELATIVE
from core.lifecycle.engine import rewind_acknowledgement_token
from core.tests.test_adoption_transaction import _setup
from core.tests.test_lifecycle_bridge import _write_bridge_release

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "lifecycle"
    / "contracts"
    / "api.schema.json"
)


def _json_type(value: object, expected: str) -> bool:
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "boolean": type(value) is bool,
        "null": value is None,
    }[expected]


def _validate(schema: dict[str, object], node: object, value: object, path: str = "$") -> None:
    assert isinstance(node, Mapping), f"{path}: schema node is not an object"
    if "$ref" in node:
        reference = node["$ref"]
        assert isinstance(reference, str) and reference.startswith("#/$defs/")
        _validate(schema, schema["$defs"][reference.removeprefix("#/$defs/")], value, path)
        return
    for child in node.get("allOf", []):
        _validate(schema, child, value, path)
    if "anyOf" in node:
        failures = []
        for child in node["anyOf"]:
            try:
                _validate(schema, child, value, path)
                break
            except AssertionError as error:
                failures.append(str(error))
        else:
            raise AssertionError(f"{path}: no anyOf branch matched: {failures}")
    expected_type = node.get("type")
    if expected_type is not None:
        assert isinstance(expected_type, str) and _json_type(value, expected_type), (
            f"{path}: expected {expected_type}, found {type(value).__name__}"
        )
    if "const" in node:
        assert value == node["const"], f"{path}: expected constant {node['const']!r}"
    if isinstance(value, str):
        assert len(value) >= node.get("minLength", 0), f"{path}: string is too short"
        if "pattern" in node:
            assert re.search(node["pattern"], value), f"{path}: string does not match pattern"
    if type(value) is int:
        assert value >= node.get("minimum", value), f"{path}: integer is below minimum"
        assert value <= node.get("maximum", value), f"{path}: integer is above maximum"
    if isinstance(value, list):
        assert len(value) >= node.get("minItems", 0), f"{path}: array has too few items"
        if node.get("uniqueItems") is True:
            encoded = [json.dumps(item, sort_keys=True) for item in value]
            assert len(encoded) == len(set(encoded)), f"{path}: array items are not unique"
        if "items" in node:
            for index, item in enumerate(value):
                _validate(schema, node["items"], item, f"{path}[{index}]")
    if isinstance(value, Mapping):
        required = node.get("required", [])
        missing = set(required) - set(value)
        assert not missing, f"{path}: missing fields {sorted(missing)}"
        properties = node.get("properties", {})
        if node.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            assert not unknown, f"{path}: unknown fields {sorted(unknown)}"
        for field, child in properties.items():
            if field in value:
                _validate(schema, child, value[field], f"{path}.{field}")


def _assert_conforms(
    schema: dict[str, object], operation: str, request: dict[str, object], response: object
) -> None:
    operation_schema = schema["x-operations"][operation]
    _validate(schema, operation_schema["request"], request)
    _validate(schema, operation_schema["response"], response)


def test_frozen_service_inputs_and_outputs_conform_to_schema(tmp_path: Path) -> None:
    vault, _document, _catalog, _inventory, _plan, _loader = _setup(
        tmp_path, item_ids=("alpha",)
    )
    _write_bridge_release(vault)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"

    inventory_request = {"vault_root": str(vault)}
    inventory_response = service.build_inventory_and_plan(vault)
    assert (vault / ACTIVATION_RELATIVE).is_file()
    _assert_conforms(
        schema,
        "build_inventory_and_plan",
        inventory_request,
        inventory_response,
    )

    preview_request = {
        "vault_root": str(vault),
        "release_root": str(vault),
        "requested_item_ids": ["alpha"],
    }
    preview_response = service.build_and_preview_adoption(
        vault, vault, ("alpha",)
    )
    _assert_conforms(
        schema,
        "build_and_preview_adoption",
        preview_request,
        preview_response,
    )

    execute_request = {
        "vault_root": str(vault),
        "release_root": str(vault),
        "preview": preview_response["preview"],
        "approved_token": preview_response["approval_token"],
    }
    execute_response = service.execute_approved_adoption(
        vault,
        vault,
        preview_response["preview"],
        preview_response["approval_token"],
    )
    _assert_conforms(
        schema,
        "execute_approved_adoption",
        execute_request,
        execute_response,
    )

    receipt = execute_response["receipt"]
    rewind_request = {
        "vault_root": str(vault),
        "receipt": receipt,
        "acknowledgement_token": rewind_acknowledgement_token(receipt),
    }
    rewind_response = service.rewind_adoption_by_receipt(
        vault,
        receipt,
        rewind_request["acknowledgement_token"],
    )
    _assert_conforms(
        schema,
        "rewind_adoption_by_receipt",
        rewind_request,
        rewind_response,
    )

    state_request = {"vault_root": str(vault)}
    state_response = service.read_lifecycle_state(vault)
    _assert_conforms(
        schema,
        "read_lifecycle_state",
        state_request,
        state_response,
    )


def test_api_version_is_present_and_frozen_in_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert service.api_version == "1.0.0"
    assert schema["properties"]["api_version"] == {"const": service.api_version}


def test_public_surface_requires_a_version_bump_and_bridge_to_change() -> None:
    assert service.__all__ == [
        "api_version",
        "build_inventory_and_plan",
        "build_and_preview_adoption",
        "execute_approved_adoption",
        "rewind_adoption_by_receipt",
        "read_lifecycle_state",
    ]
    assert "version bump" in service.__doc__.lower()
    assert "bridge" in service.__doc__.lower()
