from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.mcp import analytics_server, onboarding_server

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_AUTOMATION = REPO_ROOT / ".scripts" / "meeting-intel" / "install-automation.sh"


def _run_auth_check(
    tmp_path: Path,
    *,
    api_key: str | None = None,
    dot_env: str | None = None,
    legacy_credentials: bool = False,
):
    vault = tmp_path / "vault"
    script_dir = vault / ".scripts" / "meeting-intel"
    lib_dir = script_dir / "lib"
    lib_dir.mkdir(parents=True)
    shutil.copy2(INSTALL_AUTOMATION, script_dir / INSTALL_AUTOMATION.name)
    shutil.copy2(
        REPO_ROOT / ".scripts" / "meeting-intel" / "lib" / "granola-api-key.cjs",
        lib_dir / "granola-api-key.cjs",
    )
    if dot_env is not None:
        (vault / ".env").write_text(dot_env, encoding="utf-8")

    home = tmp_path / "home"
    home.mkdir()
    if legacy_credentials:
        legacy_path = (
            home
            / "Library"
            / "Application Support"
            / "Granola"
            / ("supabase" + ".json")
        )
        legacy_path.parent.mkdir(parents=True)
        legacy_path.write_text('{"workos_tokens": "stale"}\n', encoding="utf-8")
    env = os.environ.copy()
    env["HOME"] = str(home)
    if api_key is None:
        env.pop("GRANOLA_API_KEY", None)
    else:
        env["GRANOLA_API_KEY"] = api_key

    return subprocess.run(
        ["bash", str(script_dir / INSTALL_AUTOMATION.name), "--auth"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.parametrize(
    ("api_key", "dot_env"),
    [
        ("grn_from_environment", None),
        (None, 'GRANOLA_API_KEY="grn_from_vault_env"\n'),
    ],
)
def test_meeting_intel_auth_accepts_the_sync_api_key_sources(
    tmp_path: Path,
    api_key: str | None,
    dot_env: str | None,
) -> None:
    result = _run_auth_check(tmp_path, api_key=api_key, dot_env=dot_env)

    assert result.returncode == 0
    assert "Granola API key found" in result.stdout
    assert "/granola-setup" not in result.stdout


def test_meeting_intel_auth_points_missing_keys_to_granola_setup(tmp_path: Path) -> None:
    result = _run_auth_check(tmp_path, legacy_credentials=True)

    assert result.returncode == 0
    assert "Granola API key not found" in result.stdout
    assert "/granola-setup" in result.stdout
    assert "desktop app and sign in" not in result.stdout


def test_install_and_setup_instructions_detect_the_app_without_claiming_connection() -> None:
    install_text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    setup_text = (REPO_ROOT / ".claude" / "skills" / "setup" / "SKILL.md").read_text(encoding="utf-8")
    update_text = (REPO_ROOT / ".claude" / "skills" / "dex-update" / "SKILL.md").read_text(encoding="utf-8")

    for text in (install_text, setup_text, update_text):
        assert "/Applications/Granola.app" in text
        assert "Granola app detected" in text
        assert "/granola-setup" in text

    assert "needs a Granola Business API key" in install_text
    assert "If the API key is configured and meeting automation is not yet installed" in update_text
    assert "If the app is present, the API key is configured" not in update_text


def test_onboarding_granola_detection_checks_the_application(monkeypatch, tmp_path: Path) -> None:
    app_path = tmp_path / "Granola.app"
    monkeypatch.setattr(onboarding_server.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(onboarding_server, "GRANOLA_APP_PATH", app_path, raising=False)

    assert onboarding_server.check_granola()["installed"] is False

    app_path.mkdir()
    detected = onboarding_server.check_granola()
    assert detected["installed"] is True
    assert detected["app_found"] is True
    assert detected["path"] == str(app_path)


@pytest.mark.parametrize(
    ("shape", "expected_enabled"),
    [
        ("automatic", True),
        ({"mode": "automatic"}, True),
        ("manual", False),
        ({"mode": "manual"}, False),
    ],
)
def test_identify_user_accepts_string_and_object_meeting_processing(
    monkeypatch,
    shape,
    expected_enabled: bool,
) -> None:
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(analytics_server, "is_analytics_enabled", lambda: True)
    monkeypatch.setattr(
        analytics_server,
        "load_user_profile",
        lambda: {"meeting_processing": shape},
    )
    monkeypatch.setattr(
        analytics_server,
        "fire_event",
        lambda name, properties: events.append((name, properties)) or {"fired": True},
    )

    asyncio.run(analytics_server._call_tool_inner("identify_user", {}))

    assert events[0][0] == "user_identified"
    assert events[0][1]["granola_enabled"] is expected_enabled


def test_meeting_processing_instructions_write_the_canonical_object_shape() -> None:
    bare_shape = re.compile(r"meeting_processing:\s+(?:manual|automatic)")
    for relative_path in (
        ".claude/flows/onboarding.md",
        ".claude/skills/setup/SKILL.md",
    ):
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert bare_shape.search(text) is None, relative_path
        assert "meeting_processing:" in text
        assert "mode: manual" in text
        assert "mode: automatic" in text


def test_no_live_code_or_instructions_use_legacy_granola_local_auth() -> None:
    intentional_history_or_prohibition = {
        Path("CHANGELOG.md"),
        Path(".claude/skills/granola-setup/SKILL.md"),
        Path(".scripts/meeting-intel/sync-from-granola.cjs"),
        Path("06-Resources/Dex_System/Dex_Technical_Guide.md"),
        Path("docs/Dex_System/Dex_Technical_Guide.md"),
        Path("System/Session_Learnings/2026-01-30.md"),
    }
    excluded_parts = {".git", "node_modules", "plugins", "ritual_intelligence", "tests"}
    markers = ("cache" + "-v", "supabase" + ".json")
    offenders = []

    for root, directory_names, file_names in os.walk(REPO_ROOT):
        directory_names[:] = [
            name for name in directory_names if name not in excluded_parts
        ]
        for file_name in file_names:
            path = Path(root) / file_name
            if path.suffix not in {".md", ".sh", ".py", ".cjs"}:
                continue
            relative_path = path.relative_to(REPO_ROOT)
            if relative_path in intentional_history_or_prohibition:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(marker in text for marker in markers):
                offenders.append(str(relative_path))

    assert offenders == []


def test_agent_meeting_skills_use_the_connected_granola_model() -> None:
    claude_getting_started = (
        REPO_ROOT / ".claude" / "skills" / "getting-started" / "SKILL.md"
    ).read_text(encoding="utf-8")
    agent_getting_started = (
        REPO_ROOT / ".agents" / "skills" / "getting-started" / "SKILL.md"
    ).read_text(encoding="utf-8")

    for text in (claude_getting_started, agent_getting_started):
        assert "**Granola:** ✅ Connected" in text
        assert "Granola isn't connected" in text
        assert "Connecting Granola — run `/granola-setup`" in text
        assert "I can see Granola is connected" in text

    claude_process = (
        REPO_ROOT / ".claude" / "skills" / "process-meetings" / "SKILL.md"
    ).read_text(encoding="utf-8")
    agent_process = (
        REPO_ROOT / ".agents" / "skills" / "process-meetings" / "SKILL.md"
    ).read_text(encoding="utf-8")
    for text in (claude_process, agent_process):
        assert "Granola API key is connected" in text
        assert "node .scripts/auto-link-people.cjs" in text
