"""Machine-state probes, including the E13 tracked-despite-ignored gate."""

from __future__ import annotations

import subprocess
from pathlib import Path

from core.lifecycle.filesystem import detect_case_collisions
from core.lifecycle.machine_state import probe_machine_state, probe_tracked_despite_ignored
from core.tests.lifecycle_test_helpers import write_file


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def test_e13_reports_tracked_files_that_are_also_ignored(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _git(vault, "init", "-q")
    write_file(vault, ".gitignore", b"/System/usage_log.md\n")
    write_file(vault, "System/usage_log.md", b"local runtime\n")
    _git(vault, "add", ".gitignore")
    _git(vault, "add", "-f", "System/usage_log.md")

    evidence = probe_tracked_despite_ignored(vault)

    assert evidence.state == "DETECTED"
    assert evidence.paths == ("System/usage_log.md",)


def test_machine_state_reports_projections_and_symlinks_without_following(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, ".mcp.json", b'{"secret":"not-read"}\n')
    write_file(vault, "System/.dex-sessions.db", b"not-a-real-db")
    outside = tmp_path / "outside"
    outside.mkdir()
    write_file(outside, "private.pem", b"never traverse\n")
    (vault / "linked").symlink_to(outside, target_is_directory=True)

    report = probe_machine_state(vault)

    assert report.tracked_despite_ignored.state == "UNKNOWN"
    assert report.projections_present == (".mcp.json", "System/.dex-sessions.db")
    assert report.symlinks == ("linked",)


def test_case_collision_detector_reports_both_paths_without_picking_a_winner() -> None:
    assert detect_case_collisions(("04-Projects/Client.md", "04-projects/client.md", "README.md")) == (
        ("04-Projects/Client.md", "04-projects/client.md"),
    )
