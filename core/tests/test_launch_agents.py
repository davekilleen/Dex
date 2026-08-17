"""Direct coverage for the shared launch-agent ownership helper."""

from __future__ import annotations

import plistlib
from pathlib import Path

from core.utils import automation_ownership, launch_agents


def test_former_root_scan_skips_a_valid_solo_owned_plist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    home = tmp_path / "home"
    former = tmp_path / "former-vault"
    breadcrumb = home / ".config/dex/vault-path"
    breadcrumb.parent.mkdir(parents=True)
    breadcrumb.write_text(f"{former}\n", encoding="utf-8")
    plist = home / "Library/LaunchAgents/com.dex.example.plist"
    plist.parent.mkdir(parents=True)
    with plist.open("wb") as handle:
        plistlib.dump({"ProgramArguments": [str(former / "run.sh")]}, handle)
    observed: list[tuple[Path, str, Path]] = []

    def is_offloaded(root: Path, relative: str, *, home_root: Path) -> bool:
        observed.append((root, relative, home_root))
        return True

    monkeypatch.setattr(automation_ownership, "is_plist_offloaded", is_offloaded)

    assert launch_agents.any_agent_references_former_root(vault, home) is False
    assert observed == [
        (vault, "Library/LaunchAgents/com.dex.example.plist", home),
    ]


def test_offloaded_check_cli_returns_the_claim_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(
        automation_ownership,
        "is_plist_offloaded",
        lambda root, relative, *, home_root: (
            root == vault
            and relative == "Library/LaunchAgents/com.dex.example.plist"
            and home_root == home
        ),
    )

    args = [
        "--offloaded-check",
        "--vault",
        str(vault),
        "--plist-relative",
        "Library/LaunchAgents/com.dex.example.plist",
    ]
    assert launch_agents.main(args) == 0
    assert launch_agents.main([*args[:-1], "Library/LaunchAgents/com.dex.other.plist"]) == 1
