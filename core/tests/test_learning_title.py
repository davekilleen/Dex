"""Learning titles come from the note, not from a generic kind label."""
from __future__ import annotations

from core.utils.learning_title import (
    CONTENT_MATCH_THRESHOLD,
    contents_match,
    idea_title_from_learning,
    infer_kind,
    is_generic_title,
    is_rewritable_generic_title,
    learning_title_from_text,
    retitle_learning_entry,
    title_from_content,
)


def test_learning_title_from_text() -> None:
    assert (
        learning_title_from_text("no, stop over inferring from timesheet entries", "Correction")
        == "Stop over inferring from timesheet entries"
    )
    assert learning_title_from_text("I prefer summaries in bullet points", "Preference") == (
        "I prefer summaries in bullet points"
    )
    assert learning_title_from_text("don't do that", "Correction") == "Don't do that"
    assert learning_title_from_text("", "Correction") == "Correction"
    assert learning_title_from_text("   ", "Preference") == "Preference"
    assert learning_title_from_text("no", "Correction") == "Correction"
    assert learning_title_from_text("wrong", "Correction") == "Correction"
    assert learning_title_from_text("stop over inferring from timesheet codes") == (
        "Stop over inferring from timesheet codes"
    )


def test_title_from_content_is_the_shared_helper() -> None:
    assert title_from_content("no, that's not what I asked", fallback="Correction") == (
        "That's not what I asked"
    )
    assert not is_generic_title(title_from_content("no, that's not what I asked"))


def test_stop_filler_is_stripped_only_when_a_clearer_verb_follows() -> None:
    assert (
        learning_title_from_text("stop, don't invent folders at the top of the vault")
        == "Don't invent folders at the top of the vault"
    )
    assert (
        learning_title_from_text("stop over inferring from timesheet codes")
        == "Stop over inferring from timesheet codes"
    )


def test_stock_boilerplate_is_ignored_when_naming() -> None:
    title = learning_title_from_text(
        "**What was said:**\n\n> stop writing failure patterns and then failing them\n\n"
        "**Why it matters:** a correction is the highest-value signal about how this "
        "assistant fails, and it is lost when nobody writes it down.\n\n"
        "**Suggested fix:** confirm during /daily-review and route to "
        "`Mistake_Patterns.md`\n",
        "Correction",
    )
    assert "failure patterns" in title.lower()
    assert title != "Correction"


def test_long_content_is_clipped_at_a_word() -> None:
    title = learning_title_from_text(
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
    assert CONTENT_MATCH_THRESHOLD == 0.75


def test_short_unrelated_notes_do_not_fuzzy_match() -> None:
    assert contents_match("stop that", "stop doing that") is False
    assert contents_match("stop that", "stop that") is True


def test_same_line_field_prefix_is_not_kept_in_the_title() -> None:
    assert (
        learning_title_from_text("**What happened:** stop over inferring from timesheet codes")
        == "Stop over inferring from timesheet codes"
    )
    assert is_rewritable_generic_title("Correction.")


def test_shared_auto_capture_boilerplate_does_not_merge_unrelated_notes() -> None:
    boilerplate = (
        "**Why it matters:** a correction is the highest-value signal about how this "
        "assistant fails, and it is lost when nobody writes it down.\n\n"
        "**Suggested fix:** classify during /daily-review and route to "
        "`Mistake_Patterns.md`\n"
    )
    left = f"**What was said:**\n\n> stop over inferring from timesheet codes\n\n{boilerplate}"
    right = f"**What was said:**\n\n> the daily-plan skill skipped step 5.8 entirely\n\n{boilerplate}"

    assert contents_match(left, right) is False
    assert contents_match(left, left) is True


def test_idea_title_adds_fix_prefix_only_for_fix_language() -> None:
    assert idea_title_from_learning("Stop over inferring from timesheet codes") == (
        "Stop over inferring from timesheet codes"
    )
    assert idea_title_from_learning(
        "Stop over inferring from timesheet codes",
        "write a rule that timesheet codes are not meetings",
    ).startswith("Fix: ")
    assert "Correction" not in idea_title_from_learning("Correction", "classify during /daily-review")


def test_retitle_learning_entry_is_pure_and_skips_finished() -> None:
    pending = (
        "## 09:15 - Correction\n\n"
        "**What was said:**\n\n> stop over inferring from timesheet codes\n\n"
        "**Status:** pending\n"
    )
    rewritten = retitle_learning_entry(pending)
    assert rewritten != pending
    assert "## 09:15 - Stop over inferring from timesheet codes" in rewritten
    assert "**Kind:** Correction" in rewritten
    assert retitle_learning_entry(rewritten) == rewritten

    finished = (
        "## 09:15 - Correction\n\n"
        "**What was said:**\n\n> stop over inferring from timesheet codes\n\n"
        "**Status:** implemented\n"
    )
    assert retitle_learning_entry(finished) == finished
    dropped = finished.replace("implemented", "dropped")
    assert retitle_learning_entry(dropped) == dropped


def test_infer_kind_from_old_title_or_body() -> None:
    assert infer_kind(title="Correction") == "Correction"
    assert infer_kind(title="Preference") == "Preference"
    assert infer_kind(title="Stop inventing folders", body="I prefer bullet summaries") == (
        "Preference"
    )
    assert infer_kind(explicit="correction") == "Correction"
