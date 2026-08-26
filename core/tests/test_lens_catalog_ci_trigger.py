"""Behavioral checks for the PR/dispatch Lens release dry-run decision."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/lens-catalog-release-path.py"


def _decide(tmp_path: Path, event: str, *paths: str) -> subprocess.CompletedProcess[str]:
    changed = tmp_path / "changed-files.txt"
    changed.write_text("\n".join(paths) + ("\n" if paths else ""), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--event-name",
            event,
            "--changed-files",
            str(changed),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "path",
    (
        ".github/workflows/ci.yml",
        "scripts/generate-dex-lens-catalog.py",
        "scripts/lens-catalog-release-path.py",
        "core/lens_catalog_discovery.py",
        "core/lens_catalog_sources.py",
        "core/lens-catalog/registry.json",
        "core/lifecycle/catalog/official-capabilities.json",
        "core/portable_contract.py",
        "core/capabilities.py",
        "packages/dex-contracts/dist/portable-vault.contract.json",
        ".claude/skills/daily-plan/SKILL.md",
        ".claude/skills/_available/sales/account-plan/SKILL.md",
        "package.json",
        "CHANGELOG.md",
    ),
)
def test_pull_request_runs_for_every_catalogue_release_dependency(tmp_path: Path, path: str) -> None:
    result = _decide(tmp_path, "pull_request", path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "should_run=true\n"


def test_pull_request_skips_an_unrelated_change(tmp_path: Path) -> None:
    result = _decide(tmp_path, "pull_request", "docs/unrelated-note.md")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "should_run=false\n"


def test_workflow_dispatch_runs_even_with_no_changed_files(tmp_path: Path) -> None:
    result = _decide(tmp_path, "workflow_dispatch")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "should_run=true\n"


def test_unknown_event_fails_closed(tmp_path: Path) -> None:
    result = _decide(tmp_path, "push", "docs/unrelated-note.md")

    assert result.returncode != 0
    assert "unsupported event" in result.stderr
