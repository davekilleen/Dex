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
        "## 13:05 - Preference\n\n"
        "**What was said:**\n\n"
        "> I prefer summaries in bullet points\n\n"
        "**Status:** pending\n\n---\n\n"
        "## 12:00 - Session completed\n\n"
        "**Session ended**\n\n---\n\n"
        "## 14:00 - Correction\n\n"
        "**What was said:**\n\n"
        "> already routed so leave this heading alone\n\n"
        "**Status:** implemented\n\n---\n",
    )

    result = backfill_vault(tmp_path)
    text = path.read_text(encoding="utf-8")

    assert result["retitled"] == 3
    assert "stop over inferring from timesheet codes" in text
    assert "daily-plan skill skipped step 5.8" in text
    assert "I prefer summaries in bullet points" in text
    assert "## 09:15 - Correction" not in text
    assert "## 11:40 - Correction" not in text
    assert "## 13:05 - Preference" not in text
    assert "## 12:00 - Session completed" in text
    assert "## 14:00 - Correction" in text
    assert text.count("**Status:** pending") == 3
    assert text.count("**Kind:**") == 3

    second = backfill_vault(tmp_path)
    assert second["unchanged"] is True
    assert second["retitled"] == 0
    assert path.read_text(encoding="utf-8") == text


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


def test_retitles_bracketed_headings_and_what_happened_entries(tmp_path: Path) -> None:
    path = _learning(
        tmp_path,
        "2026-10-01",
        "## [09:15] - Correction\n\n"
        "**What happened:** stop over inferring from timesheet codes\n\n"
        "**Status:** pending\n\n---\n\n"
        "## 10:00 - Preference\n\n"
        "**What was said:**\n\n"
        "> I prefer summaries in bullet points\n\n"
        "**Status:** pending\n\n---\n",
    )

    backfill_vault(tmp_path)
    text = path.read_text(encoding="utf-8")

    assert "## [09:15] - Stop over inferring from timesheet codes" in text
    assert "## 10:00 - I prefer summaries in bullet points" in text
    assert "## [09:15] - Correction" not in text
    assert "## 10:00 - Preference" not in text
    assert "**Kind:** Correction" in text
    assert "**Kind:** Preference" in text


def test_leaves_descriptive_titles_and_empty_generic_notes_alone(tmp_path: Path) -> None:
    path = _learning(
        tmp_path,
        "2026-10-01",
        "## 09:15 - Stop inventing top-level folders\n\n"
        "> stop inventing top-level folders\n\n"
        "**Status:** pending\n\n---\n\n"
        "## 10:00 - Correction\n\n"
        "**Status:** pending\n\n---\n",
    )
    before = path.read_text(encoding="utf-8")

    result = backfill_vault(tmp_path)

    assert result["retitled"] == 0
    assert path.read_text(encoding="utf-8") == before


def test_preserves_crlf_and_does_not_drop_bodies(tmp_path: Path) -> None:
    folder = tmp_path / "System" / "Session_Learnings"
    folder.mkdir(parents=True)
    path = folder / "2026-10-01.md"
    words = "stop over inferring from timesheet codes"
    path.write_bytes(
        (
            "# Session Learnings - 2026-10-01\r\n\r\n"
            f"## 09:15 - Correction\r\n\r\n"
            f"**What was said:**\r\n\r\n> {words}\r\n\r\n"
            "**Status:** pending\r\n\r\n---\r\n"
        ).encode("utf-8")
    )

    backfill_vault(tmp_path)
    data = path.read_bytes()

    assert b"\r\n" in data
    assert words.encode("utf-8") in data
    assert b"## 09:15 - Correction" not in data


def test_retitles_trailing_period_and_preserves_bom(tmp_path: Path) -> None:
    folder = tmp_path / "System" / "Session_Learnings"
    folder.mkdir(parents=True)
    path = folder / "2026-10-01.md"
    words = "stop over inferring from timesheet codes"
    path.write_bytes(
        (
            "\ufeff# Session Learnings - 2026-10-01\n\n"
            f"## 09:15 - Correction.\n\n> {words}\n\n"
            "**Status:** pending\n\n---\n"
        ).encode("utf-8")
    )

    result = backfill_vault(tmp_path)
    data = path.read_bytes()

    assert result["retitled"] == 1
    assert data.startswith("\ufeff".encode("utf-8"))
    assert words.encode("utf-8") in data
    assert b"## 09:15 - Correction." not in data
    assert b"## 09:15 - Stop over inferring from timesheet codes" in data


def test_skips_readme_and_implemented_ideas(tmp_path: Path) -> None:
    readme = tmp_path / "System" / "Session_Learnings" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("## 09:00 - Correction\n\n> do not retitle a readme\n", encoding="utf-8")
    path = _backlog(
        tmp_path,
        "- **[idea-001]** Fix: Correction\n"
        "  - **Implemented:** 2026-10-01\n\n",
    )
    # Archive heading is already after the low-priority section in the helper,
    # so move this idea into the archive block.
    path.write_text(
        "# Dex Improvement Backlog\n\n"
        "### 💡 Low Priority (Score: <60)\n\n"
        "## Archive (Implemented)\n\n"
        "- **[idea-001]** Fix: Correction\n"
        "  - **Implemented:** 2026-10-01\n",
        encoding="utf-8",
    )
    before_readme = readme.read_text(encoding="utf-8")
    before_backlog = path.read_text(encoding="utf-8")

    result = backfill_vault(tmp_path)

    assert result["retitled"] == 0
    assert result["split"] == 0
    assert readme.read_text(encoding="utf-8") == before_readme
    assert path.read_text(encoding="utf-8") == before_backlog
