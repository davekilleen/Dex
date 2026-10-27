"""Background retitle/split is safe, idempotent, and does not drop notes."""
from __future__ import annotations

from pathlib import Path

from core.utils.learning_title_backfill import RECEIPT_RELATIVE, backfill_vault


def _learning(vault: Path, day: str, body: str) -> Path:
    folder = vault / "System" / "Session_Learnings"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.md"
    path.write_text(
        f"# Session Learnings - {day}\n\n---\n\n{body}",
        encoding="utf-8",
    )
    return path


def _backlog(vault: Path, body: str) -> Path:
    system = vault / "System"
    system.mkdir(parents=True, exist_ok=True)
    path = system / "Dex_Backlog.md"
    path.write_text(
        "# Dex Improvement Backlog\n\n"
        "### 💡 Low Priority (Score: <60)\n\n"
        f"{body}"
        "## Archive (Implemented)\n\n",
        encoding="utf-8",
    )
    return path


def test_retitles_generic_headings_from_their_content(tmp_path: Path) -> None:
    path = _learning(
        tmp_path,
        "2026-10-01",
        "## 09:15 - Correction\n\n"
        "**What was said:**\n\n"
        "> stop over inferring from timesheet codes\n\n"
        "**Status:** pending\n\n---\n\n"
        "## 11:40 - Correction\n\n"
        "**What was said:**\n\n"
        "> the daily-plan skill skipped step 5.8 entirely\n\n"
        "**Status:** pending\n\n---\n\n"
        "## 12:00 - Session completed\n\n"
        "**Session ended**\n\n---\n",
    )

    result = backfill_vault(tmp_path)
    text = path.read_text(encoding="utf-8")

    assert result["retitled"] == 2
    assert "stop over inferring from timesheet codes" in text
    assert "daily-plan skill skipped step 5.8" in text
    assert "## 09:15 - Correction" not in text
    assert "## 11:40 - Correction" not in text
    assert "## 12:00 - Session completed" in text
    assert text.count("**Status:** pending") == 2


def test_second_run_is_a_noop(tmp_path: Path) -> None:
    path = _learning(
        tmp_path,
        "2026-10-01",
        "## 09:15 - Correction\n\n"
        "> stop over inferring from timesheet codes\n\n"
        "**Status:** pending\n\n---\n",
    )

    first = backfill_vault(tmp_path)
    before = path.read_text(encoding="utf-8")
    second = backfill_vault(tmp_path)

    assert first["retitled"] == 1
    assert second["unchanged"] is True
    assert second["retitled"] == 0
    assert path.read_text(encoding="utf-8") == before
    assert (tmp_path / RECEIPT_RELATIVE).is_file()


def test_splits_a_generic_backlog_idea_without_losing_evidence(tmp_path: Path) -> None:
    path = _backlog(
        tmp_path,
        "- **[idea-001]** Fix: Correction\n"
        "  - **Score:** 0\n"
        "  - **Category:** system\n"
        "  - **Captured:** 2026-10-01\n"
        "  - **Source:** Session Learning Synthesis\n"
        "  - **Description:** From session learning (2026-10-01): "
        "stop over inferring from timesheet codes\n"
        "  - **🔔 Why Now? (AI-enriched 2026-10-02):** "
        "Session learning (2026-10-02): Correction. "
        "the daily-plan skill skipped step 5.8 entirely "
        "*(Source: Session Learning 2026-10-02)*\n\n",
    )

    result = backfill_vault(tmp_path)
    text = path.read_text(encoding="utf-8")

    assert result["split"] >= 1
    assert "stop over inferring from timesheet codes" in text
    assert "daily-plan skill skipped step 5.8" in text
    assert "Fix: Correction" not in text
    assert "idea-001" in text
    assert "idea-002" in text


def test_does_not_touch_a_content_titled_idea(tmp_path: Path) -> None:
    path = _backlog(
        tmp_path,
        "- **[idea-001]** Fix: Stop inventing top-level folders\n"
        "  - **Score:** 0\n"
        "  - **Category:** system\n"
        "  - **Captured:** 2026-10-01\n"
        "  - **Description:** Stop inventing top-level folders\n\n",
    )
    before = path.read_text(encoding="utf-8")

    result = backfill_vault(tmp_path)

    assert result["split"] == 0
    assert path.read_text(encoding="utf-8") == before


def test_missing_folders_are_a_silent_success(tmp_path: Path) -> None:
    result = backfill_vault(tmp_path)

    assert result["unchanged"] is True
    assert result["retitled"] == 0
    assert result["split"] == 0
