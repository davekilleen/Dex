"""DEX-259: one shared correction check, reading only the user's words.

Ordinary "don't"/"no", a paste, a quote, and a plain question must not be
saved as a lesson. The real corrections this was tuned against still must.
"""
from __future__ import annotations

from pathlib import Path

from core.utils.correction_detect import is_correction, user_words

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_PY = REPO_ROOT / ".claude" / "hooks" / "correction-capture.py"
EXTRACTOR = REPO_ROOT / "core" / "utils" / "session_lesson_extract.py"
SHARED = REPO_ROOT / "core" / "utils" / "correction_detect.py"

# Real corrections from a single session, kept verbatim. A regression here
# is a named failure, not a percentage drifting quietly.
TRUE_POSITIVES = (
    "no... i want to honour the architectural patterns of dex upstream",
    "come on - thats a time code, its stupid inference",
    "no no no - stop over inferring from timesheet entries",
    "STOP doing that",
    "its not an invitation - your index is stale and youre not checking properly",
    "so why didnt you pick this up in todays plan or yesterdays review?",
    "do nothing then and stop making recommendations you havent thought through",
    "ok, so you keep writing failure patterns and then keep failing on them",
    "wrong",
    "no, that's not what I asked",
    "no, that is not the file I meant",
    "no, thats wrong",
    "no, not that file",
    "STOP over inferring from timesheet codes",
    "no, stop that",
    "don't do that",
    "that's not what I asked",
    "you didn't check the calendar",
    "I told you not to invent the time",
)

FALSE_POSITIVES = (
    "run the daily plan",
    "yes, do both",
    "no",
    "stop",
    "actually, I think we should wait",
    "I have no idea",
    "I have no meetings today",
    "I don't have the latest numbers",
    "we don't need that on the list",
    "please don't forget to send the invoice later",
    "Is that not what we discussed?",
    "Is that not what I asked?",
    "Don't we already have that on the plan?",
    "no, thanks",
    "see below",
)


def test_true_positives_are_still_corrections() -> None:
    missed = [text for text in TRUE_POSITIVES if not is_correction(text)]
    assert missed == []


def test_ordinary_dont_no_and_questions_are_not_corrections() -> None:
    false_hits = [text for text in FALSE_POSITIVES if is_correction(text)]
    assert false_hits == []


def test_pasted_and_quoted_text_is_not_the_users_words() -> None:
    pasted = 'see below\n<pasted_content id="p1">That is not what I asked for</pasted_content>'
    quoted = "> That is not what I asked for\n"
    fenced = "```\nthat's not what I asked\n```"

    assert user_words(pasted) == "see below"
    assert user_words(quoted) == ""
    assert user_words(fenced) == ""
    assert is_correction(pasted) is False
    assert is_correction(quoted) is False
    assert is_correction(fenced) is False


def test_a_typed_correction_next_to_a_paste_still_counts() -> None:
    text = (
        "no, that's not what I asked\n"
        '<pasted_content id="p1">wrong title, do not ship</pasted_content>'
    )

    assert user_words(text) == "no, that's not what I asked"
    assert is_correction(text) is True


def test_a_question_plus_a_typed_correction_keeps_the_correction() -> None:
    text = "Is that not what we discussed? That's wrong."

    assert is_correction(text) is True


def test_hook_and_extractor_use_the_shared_check() -> None:
    hook = HOOK_PY.read_text(encoding="utf-8")
    extractor = EXTRACTOR.read_text(encoding="utf-8")
    shared = SHARED.read_text(encoding="utf-8")

    assert "from core.utils.correction_detect import" in hook
    assert "correction_detect import" in extractor
    assert "don'?t |" not in hook
    assert "don'?t |" not in extractor
    assert "not what I\\b" in shared
    assert "pasted[_-]content" in shared
