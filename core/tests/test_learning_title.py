"""Learning titles come from the note, not from a generic kind label."""
from __future__ import annotations

from core.utils.learning_title import (
    contents_match,
    is_generic_title,
    title_from_content,
)


def test_title_comes_from_the_first_useful_sentence() -> None:
    assert (
        title_from_content("no, stop over inferring from timesheet entries")
        == "Stop over inferring from timesheet entries"
    )
    assert title_from_content("I prefer summaries in bullet points") == (
        "I prefer summaries in bullet points"
    )
    assert title_from_content("don't do that") == "Don't do that"


def test_generic_kind_labels_are_never_preferred_when_content_exists() -> None:
    title = title_from_content(
        "no, that's not what I asked",
        fallback="Correction",
    )
    assert title == "That's not what I asked"
    assert not is_generic_title(title)


def test_stock_boilerplate_is_ignored_when_naming() -> None:
    title = title_from_content(
        "**What was said:**\n\n> stop writing failure patterns and then failing them\n\n"
        "**Why it matters:** a correction is the highest-value signal about how this "
        "assistant fails, and it is lost when nobody writes it down.\n\n"
        "**Suggested fix:** confirm during /daily-review and route to "
        "`Mistake_Patterns.md`\n",
        fallback="Correction",
    )
    assert "failure patterns" in title.lower()
    assert title != "Correction"


def test_empty_content_can_fall_back_to_the_kind() -> None:
    assert title_from_content("", fallback="Correction") == "Correction"
    assert title_from_content("   ", fallback="Preference") == "Preference"


def test_long_content_is_clipped_at_a_word() -> None:
    title = title_from_content(
        "stop inventing folders at the top of the vault when Archives and "
        "Resources already exist and should be used instead of creating new ones"
    )
    assert len(title) <= 73
    assert title.endswith("…")
    assert "inventing folders" in title


def test_contents_match_ignores_titles_and_markup() -> None:
    left = "## 09:15 - Correction\n\n> stop over inferring from timesheet codes"
    right = "Stop over inferring from timesheet codes."
    other = "> the daily-plan skill skipped step 5.8 entirely"

    assert contents_match(left, right) is True
    assert contents_match(left, other) is False
    assert contents_match("Correction", "Correction") is False
