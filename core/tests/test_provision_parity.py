"""Parity guard between the canonical Node provisioner and onboarding seeds."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_installer_routes_bootstrap_config_to_sanctioned_provision_contract() -> None:
    installer = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")

    assert "--install-config-only" in installer
    assert "System/.mcp.json.example > .mcp.json" not in installer
    assert "mcp_path.write_text" not in installer


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_adopt_preserves_existing_content_while_routing_lifecycle(tmp_path: Path) -> None:
    vault = tmp_path / "existing-vault"
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
    shutil.copy(REPO_ROOT / "CLAUDE.md", vault / "CLAUDE.md")
    (vault / "System/user-profile.yaml").write_text(
        "name: Existing User\ncustom: keep\n",
        encoding="utf-8",
    )
    (vault / "03-Tasks").mkdir()
    tasks = vault / "03-Tasks/Tasks.md"
    tasks.write_text("# My tasks\n", encoding="utf-8")

    completed = subprocess.run(
        [
            "node",
            str(REPO_ROOT / "core/provision.cjs"),
            "--path",
            str(vault),
            "--adopt",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["lifecycle_executor"]["api_version"] == "1.0.0"
    assert summary["lifecycle_executor"]["skipped"] == "no-release-catalog"
    assert "name: Existing User" in (vault / "System/user-profile.yaml").read_text()
    assert "custom: keep" in (vault / "System/user-profile.yaml").read_text()
    assert tasks.read_text(encoding="utf-8") == "# My tasks\n"
