"""Tests for the generated architecture inventory and its drift gate."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from core import portable_contract

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts/generate-architecture-inventory.py"
GATE = REPO_ROOT / "scripts/check-architecture-inventory.sh"
INVENTORY = REPO_ROOT / "docs/architecture/INVENTORY.md"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "dex_architecture_inventory_generator",
        GENERATOR,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def test_architecture_inventory_uses_lens_mcp_discovery(monkeypatch) -> None:
    generator = _load_generator()
    candidate = SimpleNamespace(
        source_path="core/integrations/example/example_server.py",
        server_name="dex-example-mcp",
        tools=("example_tool",),
        has_feature_status=True,
    )
    monkeypatch.setattr(
        generator,
        "discover_mcp_servers",
        lambda _repo_root: (candidate,),
        raising=False,
    )

    assert generator.discover_engines(REPO_ROOT) == [
        generator.Engine(
            source=candidate.source_path,
            server_name=candidate.server_name,
            tools=candidate.tools,
            has_feature_status=True,
        )
    ]


def test_inventory_detects_known_tool_and_skill(tmp_path: Path) -> None:
    output = tmp_path / "inventory.md"
    result = _generate(output)

    assert result.returncode == 0, result.stdout + result.stderr
    inventory = output.read_text(encoding="utf-8")
    assert "`dex-work-mcp`" in inventory
    assert "`create_task`" in inventory
    assert "`boot_today`" in inventory
    assert "`get_person_context`" in inventory
    assert "`check_safety_gate`" in inventory
    assert "`daily-plan`" in inventory
    assert "Build today's plan from calendar" in inventory


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
