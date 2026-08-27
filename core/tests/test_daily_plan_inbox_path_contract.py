"""Daily plans belong in the inbox folder the chassis already names.

The path contract, provision contract, and hook path table already set
``DAILY_PLANS_DIR`` to ``00-Inbox/Daily_Plans``. These tests keep the daily-plan
write path and the daily-review / week-review read paths on that folder, and
leave weekly-plan archives in ``07-Archives/Plans/YYYY-Wxx.md``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core import paths

REPO_ROOT = Path(__file__).resolve().parents[2]
DAILY_PLANS_RELATIVE = "00-Inbox/Daily_Plans"
ARCHIVED_PLANS_PREFIX = "07-Archives/Plans"
ARCHIVED_DAILY_DATED = re.compile(
    r"07-Archives/Plans/(?:YYYY-MM-DD|\{\{TARGET_DATE\}\})"
)
WEEKLY_ARCHIVE_NAME = "07-Archives/Plans/YYYY-Wxx.md"

DAILY_PLAN_WRITE_FILES = (
    REPO_ROOT / ".claude/skills/daily-plan/SKILL.md",
    REPO_ROOT / ".claude/skills/daily-plan/AGENT_INSTRUCTIONS.md",
)
DAILY_PLAN_READ_FILES = (
    REPO_ROOT / ".claude/skills/daily-review/SKILL.md",
    REPO_ROOT / ".claude/skills/daily-review/AGENT_INSTRUCTIONS.md",
    REPO_ROOT / ".claude/skills/week-review/SKILL.md",
    REPO_ROOT / ".claude/skills/week-review/AGENT_INSTRUCTIONS.md",
)
FOLDER_GUIDES = (
    REPO_ROOT / "docs/Dex_System/Folder_Structure.md",
    REPO_ROOT / "06-Resources/Dex_System/Folder_Structure.md",
    REPO_ROOT / "docs/Dex_System/Dex_Technical_Guide.md",
    REPO_ROOT / "06-Resources/Dex_System/Dex_Technical_Guide.md",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chassis_daily_plans_dir_is_inbox_daily_plans() -> None:
    assert paths.DAILY_PLANS_DIR.name == "Daily_Plans"
    assert paths.DAILY_PLANS_DIR.parent == paths.INBOX_DIR
    assert paths.INBOX_DIR.name == "00-Inbox"

    provision = json.loads((REPO_ROOT / "core/provision-contract.json").read_text())
    assert provision["path_exports"]["DAILY_PLANS_DIR"] == DAILY_PLANS_RELATIVE

    contract = json.loads(
        (REPO_ROOT / "packages/dex-contracts/dist/paths.contract.json").read_text()
    )
    assert contract["vault_relative_paths"]["DAILY_PLANS_DIR"] == DAILY_PLANS_RELATIVE

    hook_paths = _read(REPO_ROOT / ".claude/hooks/paths.cjs")
    assert "DAILY_PLANS_DIR" in hook_paths
    assert "Daily_Plans" in hook_paths


@pytest.mark.parametrize("path", DAILY_PLAN_WRITE_FILES, ids=lambda path: path.name)
def test_daily_plan_writes_to_inbox_daily_plans(path: Path) -> None:
    text = _read(path)
    assert f"{DAILY_PLANS_RELATIVE}/" in text
    assert ARCHIVED_PLANS_PREFIX not in text
    assert "Daily_Prep" not in text


@pytest.mark.parametrize("path", DAILY_PLAN_READ_FILES, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_reviews_read_daily_plans_from_inbox(path: Path) -> None:
    text = _read(path)
    assert f"{DAILY_PLANS_RELATIVE}/" in text
    assert ARCHIVED_PLANS_PREFIX not in text
    assert ARCHIVED_DAILY_DATED.search(text) is None


def test_week_plan_still_archives_weekly_files() -> None:
    text = _read(REPO_ROOT / ".claude/skills/week-plan/SKILL.md")
    assert WEEKLY_ARCHIVE_NAME in text
    assert ARCHIVED_DAILY_DATED.search(text) is None


def test_quickref_hook_reads_the_contract_daily_plans_dir() -> None:
    text = _read(REPO_ROOT / ".claude/hooks/daily-plan-quick-ref.cjs")
    assert "loadPaths" in text
    assert "DAILY_PLANS_DIR" in text
    assert "Daily_Prep" not in text
    assert ARCHIVED_PLANS_PREFIX not in text
    assert "00-Inbox" not in text


@pytest.mark.parametrize("path", FOLDER_GUIDES, ids=lambda path: str(path.relative_to(REPO_ROOT)))
def test_folder_guides_name_inbox_for_daily_plans(path: Path) -> None:
    text = _read(path)
    assert DAILY_PLANS_RELATIVE in text
    assert ARCHIVED_DAILY_DATED.search(text) is None
    assert "Daily Plan (`07-Archives/Plans/`)" not in text
    assert "Daily Plan (07-Archives/Plans/)" not in text


def test_archived_plans_readme_does_not_claim_daily_plan_creates_there() -> None:
    text = _read(REPO_ROOT / "07-Archives/Plans/README.md")
    assert DAILY_PLANS_RELATIVE in text
    assert "Created by `/daily-plan`" not in text
    assert ARCHIVED_DAILY_DATED.search(text) is None


def test_archived_daily_dated_pattern_detects_the_old_write_path() -> None:
    leaked = "Create `07-Archives/Plans/YYYY-MM-DD.md`:"
    assert ARCHIVED_DAILY_DATED.search(leaked)
    assert ARCHIVED_DAILY_DATED.search("Archive old file to `07-Archives/Plans/YYYY-Wxx.md`.") is None
