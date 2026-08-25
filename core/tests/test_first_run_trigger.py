"""First-run entrypoints must use the marker written by canonical onboarding."""


from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPLETION_MARKER = "System/.onboarding-complete"


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_first_run_entrypoints_share_the_canonical_completion_marker() -> None:
    claude_md = _read("CLAUDE.md")
    setup_skill = _read(".claude/skills/setup/SKILL.md")

    assert f"If `{COMPLETION_MARKER}` doesn't exist, this is a fresh setup." in claude_md
    assert f"If `{COMPLETION_MARKER}` already exists, setup is complete." in setup_skill
    assert "start_onboarding_session()" in setup_skill
    assert "core/onboarding/FLOW.md" in setup_skill


def test_first_run_entrypoints_do_not_use_seeded_folder_existence() -> None:
    assert (
        "If `04-Projects/` folder doesn't exist, this is a fresh setup."
        not in _read("CLAUDE.md")
    )
    assert (
        "If `04-Projects/` already exists, setup is complete."
        not in _read(".claude/skills/setup/SKILL.md")
    )


def test_shipped_projects_folder_proves_the_old_signal_is_not_freshness() -> None:
    assert (REPO_ROOT / "04-Projects" / "README.md").is_file()
