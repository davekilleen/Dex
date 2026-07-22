"""Tests for the generated architecture inventory and its drift gate."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core import portable_contract

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts/generate-architecture-inventory.py"
GATE = REPO_ROOT / "scripts/check-architecture-inventory.sh"
INVENTORY = REPO_ROOT / "docs/architecture/INVENTORY.md"


def _generate(output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(output)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_generator_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"

    first_run = _generate(first)
    second_run = _generate(second)

    assert first_run.returncode == 0, first_run.stdout + first_run.stderr
    assert second_run.returncode == 0, second_run.stdout + second_run.stderr
    assert first.read_bytes() == second.read_bytes()
    assert first.read_text(encoding="utf-8").startswith(
        "<!-- GENERATED FILE — DO NOT EDIT BY HAND. -->\n"
    )


def test_inventory_detects_known_tool_and_skill(tmp_path: Path) -> None:
    output = tmp_path / "inventory.md"
    result = _generate(output)

    assert result.returncode == 0, result.stdout + result.stderr
    inventory = output.read_text(encoding="utf-8")
    assert "`dex-work-mcp`" in inventory
    assert "`create_task`" in inventory
    assert "`daily-plan`" in inventory
    assert "Generate context-aware daily plan" in inventory


def test_drift_gate_fails_when_inventory_copy_is_stale(tmp_path: Path) -> None:
    stale_inventory = tmp_path / "INVENTORY.md"
    stale_inventory.write_bytes(INVENTORY.read_bytes())
    with stale_inventory.open("a", encoding="utf-8") as file:
        file.write("\nintentional test drift\n")

    env = os.environ.copy()
    env["ARCHITECTURE_INVENTORY_PATH"] = str(stale_inventory)
    result = subprocess.run(
        ["bash", str(GATE)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "run scripts/generate-architecture-inventory.py and commit" in (
        result.stdout + result.stderr
    )


def test_inventory_is_generated_but_its_generators_are_brain() -> None:
    assert (
        portable_contract.resolve("docs/architecture/INVENTORY.md").ownership
        == "generated"
    )
    assert (
        portable_contract.resolve("scripts/generate-architecture-inventory.py").ownership
        == "brain"
    )
    assert (
        portable_contract.resolve("scripts/check-architecture-inventory.sh").ownership
        == "brain"
    )
