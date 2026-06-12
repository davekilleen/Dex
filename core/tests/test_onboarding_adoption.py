"""Onboarding behavior against an existing (adopted) vault.

These started as characterization tests documenting the old destructive
behavior (unconditional config overwrites, dry-run misreporting, blind
.mcp.json replacement, no adopted flag). They now assert the desired
behavior: finalize_onboarding is safe to run against a pre-populated vault,
reports truthfully, and the adopted flag gates proactive Phase 2 writes.
Fresh-vault behavior is asserted unchanged at the end.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest

import core.mcp.onboarding_server as onboarding

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXAMPLE_MCP_CONFIG = {
    "mcpServers": {
        "work-mcp": {
            "type": "stdio",
            "command": "{{VAULT_PATH}}/.venv/bin/python",
            "args": ["{{VAULT_PATH}}/core/mcp/work_server.py"],
            "env": {"VAULT_PATH": "{{VAULT_PATH}}"},
        },
        "calendar-mcp": {
            "type": "stdio",
            "command": "{{VAULT_PATH}}/.venv/bin/python",
            "args": ["{{VAULT_PATH}}/core/mcp/calendar_server.py"],
            "env": {"VAULT_PATH": "{{VAULT_PATH}}"},
        },
    }
}

USER_EDITED_CLAUDE_MD = """# My Vault Rules

Notes the user wrote themselves, above the profile.

## User Profile

<!-- Updated during onboarding -->
**Name:** Old Name
**Role:** Old Role
**Company Size:** startup
**Working Style:** casual
**Pillars:**
- Old Pillar

---

## My Custom Section

Content Dex must never touch.
"""


def _completed_session() -> dict:
    now = datetime.now().isoformat()
    return {
        "version": "1.0",
        "started_at": now,
        "last_updated": now,
        "completed_steps": [1, 2, 3, 4, 5, 6],
        "current_step": 7,
        "data": {
            "name": "Interview Name",
            "role": "Product Manager",
            "role_group": "product",
            "company": "Interview Co",
            "company_size": "startup",
            "email_domain": "interview.example",
            "pillars": ["Interview Pillar One", "Interview Pillar Two"],
            "obsidian_mode": False,
            "communication": {
                "formality": "professional_casual",
                "directness": "balanced",
                "career_level": "mid",
                "coaching_style": "collaborative",
            },
        },
    }


def _patch_paths(monkeypatch: pytest.MonkeyPatch, vault: Path) -> None:
    system = vault / "System"
    monkeypatch.setattr(onboarding, "BASE_DIR", vault)
    monkeypatch.setattr(onboarding, "USER_PROFILE_FILE", system / "user-profile.yaml")
    monkeypatch.setattr(onboarding, "PILLARS_FILE", system / "pillars.yaml")
    monkeypatch.setattr(onboarding, "USER_PROFILE_TEMPLATE", system / "user-profile-template.yaml")
    monkeypatch.setattr(onboarding, "CLAUDE_MD", vault / "CLAUDE.md")
    monkeypatch.setattr(onboarding, "MCP_CONFIG_EXAMPLE", system / ".mcp.json.example")
    monkeypatch.setattr(onboarding, "MCP_CONFIG_TARGET", system / ".mcp.json")
    monkeypatch.setattr(onboarding, "MARKER_FILE", system / ".onboarding-complete")
    monkeypatch.setattr(onboarding, "SESSION_FILE", system / ".onboarding-session.json")


def _write_session(vault: Path) -> None:
    (vault / "System" / ".onboarding-session.json").write_text(
        json.dumps(_completed_session(), indent=2), encoding="utf-8"
    )


def _build_adopted_vault(fixture_vault: Path, tmp_path: Path) -> Path:
    """Copy the fixture vault and dress it as a desktop-created vault."""
    vault = tmp_path / "adopted-vault"
    shutil.copytree(fixture_vault, vault)
    system = vault / "System"

    (vault / "CLAUDE.md").write_text(USER_EDITED_CLAUDE_MD, encoding="utf-8")
    (system / ".mcp.json.example").write_text(
        json.dumps(EXAMPLE_MCP_CONFIG, indent=2), encoding="utf-8"
    )
    existing_mcp = {
        "mcpServers": {
            "my-notes-mcp": {
                "type": "stdio",
                "command": "node",
                "args": ["notes.js"],
            },
            "work-mcp": {
                "type": "stdio",
                "command": "custom-python",
                "args": ["customized.py"],
                "env": {"VAULT_PATH": "/custom/location"},
            },
        },
        "customTopLevel": True,
    }
    (system / ".mcp.json").write_text(json.dumps(existing_mcp, indent=2), encoding="utf-8")
    _write_session(vault)
    return vault


@pytest.fixture
def adopted_vault(fixture_vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault = _build_adopted_vault(fixture_vault, tmp_path)
    _patch_paths(monkeypatch, vault)
    return vault


@pytest.fixture
def fresh_vault(fixture_vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Minimal fresh vault: template, example config, template CLAUDE.md, no user config."""
    vault = tmp_path / "fresh-vault"
    system = vault / "System"
    system.mkdir(parents=True)
    shutil.copy(
        fixture_vault / "System" / "user-profile-template.yaml",
        system / "user-profile-template.yaml",
    )
    (system / ".mcp.json.example").write_text(
        json.dumps(EXAMPLE_MCP_CONFIG, indent=2), encoding="utf-8"
    )
    (vault / "CLAUDE.md").write_text(
        "# Dex - Your Personal Knowledge System\n\n"
        "## User Profile\n\n"
        "<!-- Updated during onboarding -->\n"
        "**Name:** Not yet configured\n"
        "**Pillars:**\n"
        "- Not yet configured\n\n"
        "---\n\n"
        "## Core Behaviors\n\nKeep these.\n",
        encoding="utf-8",
    )
    _write_session(vault)
    _patch_paths(monkeypatch, vault)
    return vault


def _call_tool(tool: str, arguments: dict | None = None) -> dict:
    result = asyncio.run(onboarding.handle_call_tool(tool, arguments or {}))
    if isinstance(result, list):
        text = "".join(getattr(item, "text", "") for item in result)
    else:
        text = getattr(result, "text", str(result))
    return json.loads(text)


# ---------------------------------------------------------------------------
# Finalize preserves existing config files
# ---------------------------------------------------------------------------


def test_finalize_preserves_existing_config_byte_identical(adopted_vault: Path):
    """Existing user-profile.yaml and pillars.yaml survive finalize untouched."""
    profile_path = adopted_vault / "System" / "user-profile.yaml"
    pillars_path = adopted_vault / "System" / "pillars.yaml"
    profile_before = profile_path.read_bytes()
    pillars_before = pillars_path.read_bytes()

    response = _call_tool("finalize_onboarding")

    assert response["success"] is True
    assert profile_path.read_bytes() == profile_before
    assert pillars_path.read_bytes() == pillars_before
    summary = response["data"]
    assert "System/user-profile.yaml" not in summary["files_created"]
    assert "System/pillars.yaml" not in summary["files_created"]
    assert any("user-profile.yaml" in item for item in summary["files_preserved"])
    assert any("pillars.yaml" in item for item in summary["files_preserved"])
    assert summary["errors"] == []


def test_profile_merge_fills_only_missing_fields(adopted_vault: Path):
    """A profile missing fields gains them additively; existing values stay."""
    profile_path = adopted_vault / "System" / "user-profile.yaml"
    profile_path.write_text(
        "name: Desktop User\n"
        "role: Designer\n"
        "email_domain: ''\n"
        "communication:\n"
        "  formality: casual\n",
        encoding="utf-8",
    )

    ok, outcome = onboarding.create_user_profile(_completed_session())

    assert ok is True
    assert outcome.startswith("merged:")
    assert "email_domain" in outcome

    import yaml

    merged = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert merged["name"] == "Desktop User"
    assert merged["role"] == "Designer"
    assert merged["email_domain"] == "interview.example"
    assert merged["communication"]["formality"] == "casual"
    assert merged["communication"]["directness"] == "balanced"


# ---------------------------------------------------------------------------
# Dry run reports truthfully
# ---------------------------------------------------------------------------


def test_dry_run_reports_existing_config_truthfully(adopted_vault: Path):
    response = _call_tool("finalize_onboarding", {"dry_run": True})

    assert response["success"] is True
    data = response["data"]
    assert "System/user-profile.yaml" in data["already_exist_files"]
    assert "System/pillars.yaml" in data["already_exist_files"]
    assert "System/user-profile.yaml" not in data["would_create_files"]
    assert "System/pillars.yaml" not in data["would_create_files"]
    assert "System/.mcp.json (merge missing servers into existing)" in data["would_update_configs"]
    # Dry run makes no changes
    assert not (adopted_vault / "System" / ".onboarding-complete").exists()


def test_dry_run_reports_would_create_on_fresh_vault(fresh_vault: Path):
    response = _call_tool("finalize_onboarding", {"dry_run": True})

    assert response["success"] is True
    data = response["data"]
    assert "System/user-profile.yaml" in data["would_create_files"]
    assert "System/pillars.yaml" in data["would_create_files"]
    assert "System/user-profile.yaml" not in data["already_exist_files"]
    assert "System/.mcp.json" in data["would_update_configs"]
    assert data["would_create_marker"]["adopted"] is False


# ---------------------------------------------------------------------------
# CLAUDE.md handling: create-if-missing, marker-bounded replacement
# ---------------------------------------------------------------------------


def test_update_claude_md_creates_when_missing(adopted_vault: Path):
    claude_md = adopted_vault / "CLAUDE.md"
    claude_md.unlink()

    assert onboarding.update_claude_md(_completed_session()) is True

    content = claude_md.read_text(encoding="utf-8")
    assert onboarding.CLAUDE_MD_PROFILE_START in content
    assert onboarding.CLAUDE_MD_PROFILE_END in content
    assert "**Name:** Interview Name" in content


def test_update_claude_md_adds_markers_to_user_edited_file(adopted_vault: Path):
    """A user-edited file without markers gets markers around only the
    replaced region; content outside is untouched."""
    claude_md = adopted_vault / "CLAUDE.md"

    assert onboarding.update_claude_md(_completed_session()) is True

    content = claude_md.read_text(encoding="utf-8")
    assert content.startswith("# My Vault Rules\n\nNotes the user wrote themselves, above the profile.")
    assert "## My Custom Section" in content
    assert "Content Dex must never touch." in content
    assert "**Name:** Interview Name" in content
    assert "Old Name" not in content
    start = content.index(onboarding.CLAUDE_MD_PROFILE_START)
    end = content.index(onboarding.CLAUDE_MD_PROFILE_END)
    assert start < content.index("**Name:** Interview Name") < end


def test_update_claude_md_marker_bounded_replacement(adopted_vault: Path):
    """With markers present, only the marked region changes, byte for byte."""
    claude_md = adopted_vault / "CLAUDE.md"
    before_block = "# Top Rules\n\nUser line above.\n\n"
    marked = (
        onboarding.CLAUDE_MD_PROFILE_START
        + "\n## User Profile\n\n**Name:** Stale\n"
        + onboarding.CLAUDE_MD_PROFILE_END
    )
    after_block = "\n\nUser line below with --- a separator inside.\n"
    claude_md.write_text(before_block + marked + after_block, encoding="utf-8")

    assert onboarding.update_claude_md(_completed_session()) is True

    content = claude_md.read_text(encoding="utf-8")
    assert content.startswith(before_block)
    assert content.endswith(after_block)
    assert "**Name:** Interview Name" in content
    assert "Stale" not in content
    assert content.count(onboarding.CLAUDE_MD_PROFILE_START) == 1
    assert content.count(onboarding.CLAUDE_MD_PROFILE_END) == 1


def test_update_claude_md_appends_when_no_profile_region(adopted_vault: Path):
    """No heading and no markers: the section is appended, nothing replaced.
    The old code silently no-opped on files without a '---' separator."""
    claude_md = adopted_vault / "CLAUDE.md"
    original = "# Rules\n\nJust user content, no profile section.\n"
    claude_md.write_text(original, encoding="utf-8")

    assert onboarding.update_claude_md(_completed_session()) is True

    content = claude_md.read_text(encoding="utf-8")
    assert content.startswith(original)
    assert onboarding.CLAUDE_MD_PROFILE_START in content
    assert "**Name:** Interview Name" in content


def test_update_claude_md_legacy_preserves_user_subsection_before_separator(adopted_vault: Path):
    """C-F3: a user subsection sitting between the legacy '## User Profile'
    heading and the next '---' must survive. The old '## User Profile.*?\\n---'
    span ran to the FIRST separator and destroyed everything in between."""
    claude_md = adopted_vault / "CLAUDE.md"
    claude_md.write_text(
        "# Top\n\n"
        "## User Profile\n\n"
        "<!-- Updated during onboarding -->\n"
        "**Name:** Old Name\n\n"
        "## My Private Rules\n\n"
        "never touch these\n\n"
        "---\n\n"
        "## Footer Section\n\nstays too\n",
        encoding="utf-8",
    )

    assert onboarding.update_claude_md(_completed_session()) is True

    content = claude_md.read_text(encoding="utf-8")
    # The user's private subsection and its body survive untouched
    assert "## My Private Rules" in content
    assert "never touch these" in content
    # Later content survives too
    assert "## Footer Section" in content
    assert "stays too" in content
    # The profile itself was replaced and is now marker-bounded
    assert "**Name:** Interview Name" in content
    assert "Old Name" not in content
    assert onboarding.CLAUDE_MD_PROFILE_START in content
    assert onboarding.CLAUDE_MD_PROFILE_END in content
    # The replaced profile region does not swallow the private subsection
    start = content.index(onboarding.CLAUDE_MD_PROFILE_START)
    end = content.index(onboarding.CLAUDE_MD_PROFILE_END)
    assert content.index("## My Private Rules") > end
    assert start < content.index("**Name:** Interview Name") < end


def test_update_claude_md_mangled_marker_order_falls_through_to_append(adopted_vault: Path):
    """C-F5: when both markers exist but END precedes START, the marker regex
    finds no bounded match. The file must NOT be rewritten unchanged while
    reporting success; it falls through to a real append."""
    claude_md = adopted_vault / "CLAUDE.md"
    mangled = (
        "# Rules\n\n"
        + onboarding.CLAUDE_MD_PROFILE_END
        + "\nstray content between reversed markers\n"
        + onboarding.CLAUDE_MD_PROFILE_START
        + "\n"
    )
    claude_md.write_text(mangled, encoding="utf-8")

    assert onboarding.update_claude_md(_completed_session()) is True

    content = claude_md.read_text(encoding="utf-8")
    # The original (reversed) content is preserved and a real profile section
    # was appended, rather than the file being written back byte-identical.
    assert content != mangled
    assert "stray content between reversed markers" in content
    assert "**Name:** Interview Name" in content
    # A correctly ordered START...END pair now exists in the appended section
    last_start = content.rindex(onboarding.CLAUDE_MD_PROFILE_START)
    last_end = content.rindex(onboarding.CLAUDE_MD_PROFILE_END)
    assert last_start < last_end


# ---------------------------------------------------------------------------
# .mcp.json merge
# ---------------------------------------------------------------------------


def test_setup_mcp_config_merges_into_existing(adopted_vault: Path):
    """Existing servers and keys survive; missing example servers merge in."""
    target = adopted_vault / "System" / ".mcp.json"

    success, error, report = onboarding.setup_mcp_config(adopted_vault)

    assert success is True
    assert error is None
    assert report["action"] == "merged"
    assert report["merged_servers"] == ["calendar-mcp"]
    assert "work-mcp" in report["preserved_servers"]

    merged = json.loads(target.read_text(encoding="utf-8"))
    # User's own server and top-level key survive
    assert merged["mcpServers"]["my-notes-mcp"]["command"] == "node"
    assert merged["customTopLevel"] is True
    # User's customized copy of an example server is not overwritten
    assert merged["mcpServers"]["work-mcp"]["command"] == "custom-python"
    # Missing example server merged in with the vault path substituted
    assert merged["mcpServers"]["calendar-mcp"]["env"]["VAULT_PATH"] == str(adopted_vault)


def test_setup_mcp_config_unchanged_is_byte_identical(adopted_vault: Path):
    target = adopted_vault / "System" / ".mcp.json"
    full_config = {
        "mcpServers": {
            "work-mcp": {"command": "mine"},
            "calendar-mcp": {"command": "mine-too"},
        }
    }
    target.write_text(json.dumps(full_config, indent=2), encoding="utf-8")
    before = target.read_bytes()

    success, error, report = onboarding.setup_mcp_config(adopted_vault)

    assert success is True
    assert error is None
    assert report["action"] == "unchanged"
    assert report["merged_servers"] == []
    assert target.read_bytes() == before


def test_setup_mcp_config_never_overwrites_invalid_existing(adopted_vault: Path):
    """An unparseable existing config is reported, never replaced."""
    target = adopted_vault / "System" / ".mcp.json"
    target.write_text("{ not valid json", encoding="utf-8")
    before = target.read_bytes()

    success, error, report = onboarding.setup_mcp_config(adopted_vault)

    assert success is False
    assert "left untouched" in error
    assert target.read_bytes() == before


# ---------------------------------------------------------------------------
# Completion marker: adopted flag
# ---------------------------------------------------------------------------


def test_finalize_writes_adopted_flag(adopted_vault: Path):
    response = _call_tool("finalize_onboarding", {"adopted": True})
    assert response["success"] is True

    marker = json.loads((adopted_vault / "System" / ".onboarding-complete").read_text())
    assert marker["adopted"] is True

    check = _call_tool("check_onboarding_complete")
    assert check["success"] is True
    assert check["data"]["adopted"] is True


def test_finalize_preserves_preexisting_adopted_marker(adopted_vault: Path):
    """The adopt path may write the marker before finalize runs; the flag
    survives finalization even without the explicit argument.

    C-F6: the adopt script also writes adopt_release_tag and adopted_at. These
    must survive finalize, which previously rebuilt the marker from scratch and
    dropped them.
    """
    marker_file = adopted_vault / "System" / ".onboarding-complete"
    adopt_written = {
        "adopted": True,
        "adopt_release_tag": "v9.9.9-test",
        "adopted_at": "2026-06-01T12:00:00",
    }
    marker_file.write_text(json.dumps(adopt_written), encoding="utf-8")

    # A minimal adopt-written marker is tolerated by the checker
    pre_check = _call_tool("check_onboarding_complete")
    assert pre_check["success"] is True
    assert pre_check["data"]["adopted"] is True

    response = _call_tool("finalize_onboarding")
    assert response["success"] is True

    marker = json.loads(marker_file.read_text())
    assert marker["adopted"] is True
    # Fields the adopt script wrote survive finalize
    assert marker["adopt_release_tag"] == "v9.9.9-test"
    assert marker["adopted_at"] == "2026-06-01T12:00:00"
    # Finalize's own fields are present too
    assert marker["user_name"] == "Interview Name"
    assert "completed_at" in marker


def test_fresh_finalize_marks_not_adopted(fresh_vault: Path):
    response = _call_tool("finalize_onboarding")
    assert response["success"] is True

    marker = json.loads((fresh_vault / "System" / ".onboarding-complete").read_text())
    assert marker["adopted"] is False

    check = _call_tool("check_onboarding_complete")
    assert check["data"]["adopted"] is False


# ---------------------------------------------------------------------------
# Phase 2 gating: adopted vaults get proposals, not proactive writes
# ---------------------------------------------------------------------------


def test_phase2_writes_suppressed_on_adopted_vault(adopted_vault: Path, monkeypatch: pytest.MonkeyPatch):
    marker = adopted_vault / "System" / ".onboarding-complete"
    marker.write_text(
        json.dumps({"completed_at": datetime.now().isoformat(), "adopted": True}),
        encoding="utf-8",
    )

    week_file = adopted_vault / "02-Week_Priorities" / "Week_Priorities.md"
    week_file.parent.mkdir(parents=True, exist_ok=True)
    week_file.write_text("# My Existing Plan\n", encoding="utf-8")
    week_before = week_file.read_bytes()

    assert onboarding.write_weekly_plan("# Generated Plan\n") is False
    assert week_file.read_bytes() == week_before

    import core.paths as core_paths

    monkeypatch.setattr(core_paths, "PEOPLE_DIR", adopted_vault / "05-Areas" / "People")
    contact = {"name": "Adopted Contact", "email": "adopted.contact@external.example"}
    assert onboarding.create_person_page(contact, "interview.example") is False
    page = adopted_vault / "05-Areas" / "People" / "External" / "Adopted_Contact.md"
    assert not page.exists()

    # Approved proposals go through with force=True
    assert onboarding.write_weekly_plan("# Approved Plan\n", force=True) is True
    assert week_file.read_text(encoding="utf-8") == "# Approved Plan\n"
    assert onboarding.create_person_page(contact, "interview.example", force=True) is True
    assert page.exists()


def test_phase2_writes_proceed_on_fresh_vault(fresh_vault: Path, monkeypatch: pytest.MonkeyPatch):
    """Without the adopted flag, Phase 2 writes behave exactly as before."""
    response = _call_tool("finalize_onboarding")
    assert response["success"] is True

    week_file = fresh_vault / "02-Week_Priorities" / "Week_Priorities.md"
    assert onboarding.write_weekly_plan("# Generated Plan\n") is True
    assert week_file.read_text(encoding="utf-8") == "# Generated Plan\n"

    import core.paths as core_paths

    monkeypatch.setattr(core_paths, "PEOPLE_DIR", fresh_vault / "05-Areas" / "People")
    contact = {"name": "Fresh Contact", "email": "fresh.contact@external.example"}
    assert onboarding.create_person_page(contact, "interview.example") is True
    assert (fresh_vault / "05-Areas" / "People" / "External" / "Fresh_Contact.md").exists()


# ---------------------------------------------------------------------------
# Fresh-vault golden journey unchanged
# ---------------------------------------------------------------------------


def test_fresh_vault_finalize_creates_profile_and_pillars(fresh_vault: Path):
    """The release-critical fresh path: onboarding to profile/pillars creation."""
    response = _call_tool("finalize_onboarding")

    assert response["success"] is True
    summary = response["data"]
    assert summary["errors"] == []
    assert "System/user-profile.yaml" in summary["files_created"]
    assert "System/pillars.yaml" in summary["files_created"]
    assert summary["files_preserved"] == []

    import yaml

    profile = yaml.safe_load((fresh_vault / "System" / "user-profile.yaml").read_text(encoding="utf-8"))
    assert profile["name"] == "Interview Name"
    assert profile["email_domain"] == "interview.example"
    assert profile["communication"]["formality"] == "professional_casual"

    pillars = yaml.safe_load((fresh_vault / "System" / "pillars.yaml").read_text(encoding="utf-8"))
    assert [p["name"] for p in pillars["pillars"]] == [
        "Interview Pillar One",
        "Interview Pillar Two",
    ]

    # CLAUDE.md template section replaced and now marker-bounded
    claude_content = (fresh_vault / "CLAUDE.md").read_text(encoding="utf-8")
    assert "**Name:** Interview Name" in claude_content
    assert onboarding.CLAUDE_MD_PROFILE_START in claude_content
    assert "## Core Behaviors" in claude_content

    # .mcp.json created from the example with the vault path substituted
    mcp_config = json.loads((fresh_vault / "System" / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp_config["mcpServers"]["work-mcp"]["env"]["VAULT_PATH"] == str(fresh_vault)

    # Session file removed, PARA structure present
    assert not (fresh_vault / "System" / ".onboarding-session.json").exists()
    assert (fresh_vault / "04-Projects").is_dir()
    assert (fresh_vault / "03-Tasks" / "Tasks.md").exists()
