"""A person can locally install a read-only Dex panel in Obsidian."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from core.harnesses.registry import detect_harnesses, get_profile
from core.mcp import onboarding_server
from core.obsidian_panel import (
    build_today_brief,
    install_local_plugin,
    refuse_network,
    refuse_vault_write,
)
from core.obsidian_panel.safety import plugin_source_violations
from core.onboarding.harness_receipt import (
    build_receipt_for_ids,
    canonical_receipt_bytes,
)
from core.utils import doctor

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 8, 29)
REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-obsidian-plugin"
ADAPTER_PATH = REPO_ROOT / "core" / "harnesses" / "adapters" / "obsidian.json"
VSCODE_KIRO_PATHS = (
    REPO_ROOT / "packages" / "dex-vscode-plugin",
    REPO_ROOT / "packages" / "dex-kiro-plugin",
    REPO_ROOT / "core" / "harnesses" / "adapters" / "vscode.json",
    REPO_ROOT / "core" / "harnesses" / "adapters" / "kiro.json",
    REPO_ROOT / "core" / "harnesses" / "profiles" / "vscode.json",
    REPO_ROOT / "core" / "harnesses" / "profiles" / "kiro.json",
)


@pytest.fixture
def context(tmp_path: Path) -> doctor.DoctorContext:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "core").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


def _write_vault(root: Path) -> Path:
    (root / "System").mkdir(parents=True)
    (root / "01-Quarter_Goals").mkdir(parents=True)
    (root / "02-Week_Priorities").mkdir(parents=True)
    (root / "03-Tasks").mkdir(parents=True)
    (root / "00-Inbox" / "Daily_Plans").mkdir(parents=True)
    (root / "System" / "pillars.yaml").write_text(
        'pillars:\n  - id: focus\n    name: "Focus"\n    description: "Ship the brief"\n',
        encoding="utf-8",
    )
    (root / "01-Quarter_Goals" / "Quarter_Goals.md").write_text(
        "### 1. Make today visible\n\n**Progress:** started\n",
        encoding="utf-8",
    )
    (root / "02-Week_Priorities" / "Week_Priorities.md").write_text(
        "## This Week\n- [ ] Open Dex in Obsidian today\n---\n",
        encoding="utf-8",
    )
    (root / "03-Tasks" / "Tasks.md").write_text(
        "- [ ] Review the urgent brief today\n- [x] Already done\n",
        encoding="utf-8",
    )
    (root / "00-Inbox" / "Daily_Plans" / "2026-08-29.md").write_text(
        "# Saturday, August 29, 2026\n\n- See today's brief in Obsidian\n",
        encoding="utf-8",
    )
    return root


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    for path in root.rglob("*"):
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = (
                path.stat().st_mtime_ns,
                path.read_text(encoding="utf-8"),
            )
    return snapshot


def test_obsidian_markers_do_not_select_chatgpt_work_or_vscode() -> None:
    for env in ({"OBSIDIAN_VAULT": "1"}, {"OBSIDIAN_APP": "1"}):
        assert [profile.id for profile in detect_harnesses(env=env)] == ["obsidian"]

    detected = [
        profile.id
        for profile in detect_harnesses(
            env={}, paths=[Path("/tmp/.obsidian/plugins/dex-readonly/main.js")]
        )
    ]
    assert detected == ["obsidian"]
    assert [profile.id for profile in detect_harnesses(env={"CHATGPT_WORK": "1"})] == [
        "chatgpt-work"
    ]
    assert detect_harnesses(env={}, paths=[Path("/tmp/.obsidian/app.json")]) == ()


def test_obsidian_install_contract_names_local_panel_and_no_store() -> None:
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    example = adapter["example"]
    guide = example["install_guide"].lower()
    manifest = json.loads((PLUGIN_ROOT / "manifest.json").read_text(encoding="utf-8"))

    assert adapter["native_paths"] == ["manifest.json", "main.js", "styles.css"]
    assert adapter["status"] == "native-local"
    assert example["local_package"] == "./packages/dex-obsidian-plugin"
    assert example["install_path"] == ".obsidian/plugins/dex-readonly"
    assert example["community_store"] == "not-submitted"
    assert example["network"] == "none"
    assert example["writes"] == "none"
    assert example["deferred"] == "vscode-kiro-lot-files"
    assert "dex folder" in example["vault_grant"].lower()
    assert "obsidian" in guide
    assert "today" in guide
    assert "community store" in guide
    assert "ubuntu cloud" in guide
    assert "chatgpt work folder grant" in guide
    assert manifest["id"] == "dex-readonly"
    assert "community" not in manifest["description"].lower() or "not" in manifest["description"].lower()
    for relative in adapter["native_paths"]:
        assert (PLUGIN_ROOT / relative).is_file()


def test_developer_guide_names_the_obsidian_local_steps() -> None:
    guide = (REPO_ROOT / "docs" / "HARNESS-PORTABILITY.md").read_text(encoding="utf-8")
    assert "Obsidian" in guide
    assert ".obsidian/plugins/dex-readonly" in guide
    assert "community store" in guide.lower()
    assert "Ubuntu Cloud is not a person opening Obsidian" in guide
    assert "VS Code and Kiro shared lot files are deferred" in guide


def test_plugin_source_has_no_write_or_network() -> None:
    violations = plugin_source_violations(PLUGIN_ROOT)
    assert violations == []
    main = (PLUGIN_ROOT / "main.js").read_text(encoding="utf-8")
    assert "addCommand" not in main
    assert "cachedRead" in main
    assert "getAbstractFileByPath" in main
    assert "fetch(" not in main
    assert "requestUrl" not in main
    assert "https://" not in main
    assert "http://" not in main


def test_today_brief_shows_saturday_without_writing(tmp_path: Path) -> None:
    vault = _write_vault(tmp_path / "dex")
    before = _snapshot(vault)

    brief = build_today_brief(vault, today=TODAY)

    assert brief["today"] == "Saturday, August 29, 2026"
    assert any("See today's brief in Obsidian" in line for line in brief["daily_plan"])
    assert any("Open Dex in Obsidian today" in line for line in brief["week_priorities"])
    assert any("urgent brief today" in line for line in brief["urgent_tasks"])
    assert brief["pillars"][0]["name"] == "Focus"
    assert _snapshot(vault) == before


def test_local_install_does_not_change_notes(tmp_path: Path) -> None:
    vault = _write_vault(tmp_path / "dex")
    note_before = _snapshot(vault)

    dest = install_local_plugin(vault)

    assert dest == vault / ".obsidian" / "plugins" / "dex-readonly"
    assert (dest / "main.js").is_file()
    enabled = json.loads((vault / ".obsidian" / "community-plugins.json").read_text())
    assert enabled == ["dex-readonly"]
    after = _snapshot(vault)
    for relative, payload in note_before.items():
        assert after[relative] == payload
    assert "03-Tasks/Tasks.md" in after
    assert after["03-Tasks/Tasks.md"] == note_before["03-Tasks/Tasks.md"]


def test_write_and_network_attempts_are_refused(tmp_path: Path) -> None:
    vault = _write_vault(tmp_path / "dex")
    target = vault / "03-Tasks" / "Tasks.md"
    before = target.read_text(encoding="utf-8")

    with pytest.raises(PermissionError, match="does not write"):
        refuse_vault_write(target)
    with pytest.raises(PermissionError, match="does not use the internet"):
        refuse_network("https://obsidian.md")

    assert target.read_text(encoding="utf-8") == before
    assert not os.environ.get("DEX_OBSIDIAN_ALLOW_NETWORK")


def test_this_lot_does_not_add_vscode_or_kiro_files() -> None:
    for path in VSCODE_KIRO_PATHS:
        assert not path.exists()
    package_names = {path.name for path in (REPO_ROOT / "packages").iterdir()}
    assert "dex-obsidian-plugin" in package_names
    assert "dex-vscode-plugin" not in package_names
    assert "dex-kiro-plugin" not in package_names


def test_chatgpt_work_folder_grant_is_not_invented() -> None:
    adapter = json.loads(
        (REPO_ROOT / "core" / "harnesses" / "adapters" / "chatgpt-work.json").read_text(
            encoding="utf-8"
        )
    )
    assert "grant the Dex vault folder" in adapter["example"]["vault_grant"]
    assert "this runner will not invent that grant" in (
        REPO_ROOT / "docs" / "HARNESS-PORTABILITY.md"
    ).read_text(encoding="utf-8").lower()


def test_doctor_names_obsidian_read_only_limits(
    context: doctor.DoctorContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    receipt = build_receipt_for_ids(
        ["obsidian"],
        detected_ids=("obsidian",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))

    result = doctor._probe_harness_capabilities(context)
    limitations = list(get_profile("obsidian").limitations)
    joined = " ".join(limitations).lower()

    assert result.verdict == "OK"
    assert "Obsidian" in result.detail
    assert "read-only" in joined
    assert "community store" in joined
    assert "ubuntu cloud" in joined
    assert "vs code" in joined
    assert "kiro" in joined
    assert "chatgpt work folder grant" in joined
    assert "fully automatic" not in result.detail.lower()
    assert result.structured_detail["selected"] == ["obsidian"]
    assert result.structured_detail["limitations"] == {"obsidian": limitations}
    rows = {row["id"]: row for row in get_profile("obsidian").capability_rows()}
    assert rows["mcp"]["mode"] == "unavailable"
    assert rows["agent-skills"]["mode"] == "unavailable"
    assert rows["interactive-prompts"]["mode"] == "unavailable"
    assert get_profile("obsidian").adapter["status"] == "native-local"


def test_setup_preview_keeps_obsidian_separate_from_chatgpt_work() -> None:
    inspected = onboarding_server.inspect_harnesses(["obsidian"])

    assert inspected["selected"] == ["obsidian"]
    assert "chatgpt-work" not in inspected["selected"]
    by_id = {row["id"]: row for row in inspected["profiles"]}
    joined = " ".join(by_id["obsidian"]["limitations"]).lower()
    assert "read-only" in joined
    assert "community store" in joined
    assert "chatgpt work folder grant" in joined
    assert "microsoft 365" not in joined
