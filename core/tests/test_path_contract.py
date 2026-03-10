"""Tests for shared path contract package generation."""

import json
from pathlib import Path

from core.path_contract import build_relative_paths_contract, write_contract_package


def test_relative_contract_shape():
    contract = build_relative_paths_contract()

    assert contract["contract_version"] == 1
    assert contract["source"] == "core/paths.py"
    assert isinstance(contract["vault_relative_paths"], dict)
    assert contract["vault_relative_paths"]["VAULT_ROOT"] == "."


def test_relative_contract_values_are_not_absolute_paths():
    rel_map = build_relative_paths_contract()["vault_relative_paths"]

    absolute = [
        f"{key}={value}"
        for key, value in rel_map.items()
        if isinstance(value, str) and value.startswith("/")
    ]
    assert not absolute, f"Expected vault-relative paths, got absolutes: {absolute}"


def test_write_contract_package_outputs_expected_files(tmp_path: Path):
    contract = write_contract_package(tmp_path)

    contract_json = tmp_path / "paths.contract.json"
    schema_json = tmp_path / "paths.schema.json"
    index_js = tmp_path / "index.js"
    index_dts = tmp_path / "index.d.ts"

    assert contract_json.is_file()
    assert schema_json.is_file()
    assert index_js.is_file()
    assert index_dts.is_file()

    loaded = json.loads(contract_json.read_text(encoding="utf-8"))
    assert loaded["vault_relative_paths"] == contract["vault_relative_paths"]
