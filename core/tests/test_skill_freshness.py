"""A skill that just landed on disk must be usable in this session."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from core.utils import skill_freshness

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".claude" / "hooks" / "skill-freshness.py"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
DEX_UPDATE = REPO_ROOT / ".claude" / "skills" / "dex-update" / "SKILL.md"
HOOKS_README = REPO_ROOT / ".claude" / "hooks" / "README.md"


def _write_skill(vault: Path, name: str, description: str = "Do the thing.") -> Path:
    skill_dir = vault / ".claude" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# /{name}\n\nFollow these steps.\n",
        encoding="utf-8",
    )
    return path


def _run_hook(stdin: str, vault: Path, state_dir: Path, extra_args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(vault)
    env["DEX_SKILL_FRESHNESS_STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(HOOK), *(extra_args or [])],
        cwd=vault,
        env=env,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def test_host_slash_list_cannot_be_refreshed_from_dex() -> None:
    """Dex has no skill-reload hook event; CLAUDE.md refresh is a different door."""
    assert skill_freshness.HOST_SLASH_LIST_REFRESHABLE is False

    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    events = set(settings["hooks"])
    assert "SessionStart" in events
    assert "UserPromptSubmit" in events
    assert "SkillReload" not in events
    assert "slash" not in json.dumps(settings).lower()

    composition = (REPO_ROOT / ".claude" / "hooks" / "claude-composition-refresh.sh").read_text(
        encoding="utf-8"
    )
    assert "CLAUDE.md" in composition
    assert "slash" not in composition.lower()

    wired = json.dumps(settings["hooks"]["UserPromptSubmit"])
    assert "skill-freshness.py" in wired
    session_wired = json.dumps(settings["hooks"]["SessionStart"])
    assert "skill-freshness.py" in session_wired
    assert "--session-start" in session_wired

    readme = HOOKS_README.read_text(encoding="utf-8")
    assert "skill-freshness.py" in readme


def test_new_skill_on_disk_is_injected_this_session_without_restart(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    state = tmp_path / "state"
    _write_skill(vault, "daily-plan", "Plan the day.")

    start = _run_hook(
        json.dumps({"hook_event_name": "SessionStart", "session_id": "s1"}),
        vault,
        state,
        extra_args=["--session-start"],
    )
    assert start.returncode == 0
    assert start.stdout == ""

    _write_skill(vault, "feedback", "Report a Dex bug with zero homework.")

    hello = _run_hook(
        json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "s1",
                "prompt": "what's next",
            }
        ),
        vault,
        state,
    )
    assert hello.returncode == 0
    payload = json.loads(hello.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "/feedback" in context
    assert ".claude/skills/feedback/SKILL.md" in context
    assert "Report a Dex bug" in context
    assert "/daily-plan" not in context
    assert "restart first" in context


def test_named_slash_skill_is_injected_when_missing_from_session_snapshot(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    state = tmp_path / "state"
    _write_skill(vault, "daily-plan")
    started = _run_hook(
        json.dumps({"hook_event_name": "SessionStart", "session_id": "s2"}),
        vault,
        state,
        extra_args=["--session-start"],
    )
    assert started.returncode == 0
    # Simulate SessionStart happening before the update wrote /feedback,
    # then the user typing /feedback even though the slash menu omitted it.
    _write_skill(vault, "feedback", "Report a Dex bug.")

    result = _run_hook(
        json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "s2",
                "prompt": "/feedback something broke",
            }
        ),
        vault,
        state,
    )
    assert result.returncode == 0
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "/feedback" in context
    assert ".claude/skills/feedback/SKILL.md" in context


def test_already_present_skill_stays_silent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    state = tmp_path / "state"
    _write_skill(vault, "feedback", "Report a Dex bug.")
    started = _run_hook(
        json.dumps({"hook_event_name": "SessionStart", "session_id": "s3"}),
        vault,
        state,
        extra_args=["--session-start"],
    )
    assert started.returncode == 0

    result = _run_hook(
        json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "s3",
                "prompt": "/feedback",
            }
        ),
        vault,
        state,
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_first_prompt_without_session_start_still_routes_a_named_new_skill(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    state = tmp_path / "state"
    _write_skill(vault, "daily-plan")
    _write_skill(vault, "feedback", "Report a Dex bug.")

    result = _run_hook(
        json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "s4",
                "prompt": "please run /feedback",
            }
        ),
        vault,
        state,
    )
    assert result.returncode == 0
    context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "/feedback" in context
    assert "/daily-plan" not in context


def test_hidden_available_pack_is_not_treated_as_installed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    available = vault / ".claude" / "skills" / "_available" / "sales" / "call-prep"
    available.mkdir(parents=True)
    (available / "SKILL.md").write_text("---\nname: call-prep\n---\n", encoding="utf-8")
    _write_skill(vault, "feedback")

    installed = skill_freshness.list_installed_skills(vault)
    assert "feedback" in installed
    assert "call-prep" not in installed
    assert "_available" not in installed


def test_hook_fails_open_for_empty_and_invalid_stdin(tmp_path: Path) -> None:
    for stdin in ("", "{not-json"):
        result = _run_hook(stdin, tmp_path, tmp_path / "state")
        assert result.returncode == 0
        assert result.stdout == ""


def test_dex_update_treats_newly_landed_skills_as_live_this_session() -> None:
    text = DEX_UPDATE.read_text(encoding="utf-8")
    assert "SKILL.md" in text
    assert "slash" in text.lower()
    assert "restart" in text.lower()
