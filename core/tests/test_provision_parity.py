"""Parity guard between the canonical Node provisioner and onboarding seeds."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core.mcp.onboarding_server import (
    create_initial_files,
    create_para_structure,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_node_provisioner_matches_onboarding_para_and_seed_output(tmp_path: Path) -> None:
    node_vault = tmp_path / "node-vault"
    python_vault = tmp_path / "python-vault"
    for vault in (node_vault, python_vault):
        (vault / "System").mkdir(parents=True)
        (vault / "core").mkdir()
        (vault / ".scripts").mkdir()
        shutil.copy(REPO_ROOT / "System/.mcp.json.example", vault / "System/.mcp.json.example")
        shutil.copy(
            REPO_ROOT / "System/user-profile-template.yaml",
            vault / "System/user-profile-template.yaml",
        )
        shutil.copy(REPO_ROOT / "core/paths.py", vault / "core/paths.py")
        shutil.copy(REPO_ROOT / "package.json", vault / "package.json")

    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps({"pillars": [{"name": "Build"}, {"name": "Learn Fast"}]}),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            "node",
            str(REPO_ROOT / "core/provision.cjs"),
            "--path",
            str(node_vault),
            "--profile",
            str(profile),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

    session = {"data": {"pillars": ["Build", "Learn Fast"]}}
    created_directories = create_para_structure(python_vault)
    created_files = create_initial_files(python_vault, session)

    contract = json.loads((REPO_ROOT / "core/provision-contract.json").read_text())
    assert created_directories == contract["para_directories"]
    assert created_files == list(contract["seed_files"].values())
    for relative in [*created_directories, *created_files]:
        node_path = node_vault / relative
        python_path = python_vault / relative
        assert node_path.is_dir() == python_path.is_dir(), relative
        if node_path.is_file():
            assert node_path.read_bytes() == python_path.read_bytes(), relative
