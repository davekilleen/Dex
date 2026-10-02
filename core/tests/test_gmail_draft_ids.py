"""Gmail draft ids stay on one format and never swap in a message id."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.gmail_draft import (
    GmailDraftIdError,
    classify_gmail_id,
    draft_id_from_payload,
    normalize_gmail_draft_id,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SKILL = REPO_ROOT / ".claude" / "skills" / "google-workspace-setup" / "SKILL.md"


def test_r_form_and_resource_name_normalize_to_the_same_draft_id() -> None:
    assert normalize_gmail_draft_id("r-4782215337665887188") == "r-4782215337665887188"
    assert (
        normalize_gmail_draft_id("drafts/r-4782215337665887188")
        == "r-4782215337665887188"
    )
    assert classify_gmail_id("r-4782215337665887188") == "draft"
    assert classify_gmail_id("drafts/r-4782215337665887188") == "draft"


def test_message_hex_is_refused_as_a_draft_id() -> None:
    message_id = "18c9f2a3b4d5e6f7"
    assert classify_gmail_id(message_id) == "message"
    with pytest.raises(GmailDraftIdError, match="message id"):
        normalize_gmail_draft_id(message_id)
    with pytest.raises(GmailDraftIdError, match="message id"):
        normalize_gmail_draft_id(f"drafts/{message_id}")


def test_payload_prefers_explicit_draft_id_over_message_id() -> None:
    payload = {
        "id": "r-4782215337665887188",
        "message": {"id": "18c9f2a3b4d5e6f7", "threadId": "18c9f2a3b4d5e6f7"},
    }
    assert draft_id_from_payload(payload) == "r-4782215337665887188"
    assert (
        draft_id_from_payload({"draftId": "drafts/r-4782215337665887188"})
        == "r-4782215337665887188"
    )
    assert (
        draft_id_from_payload({"draft": {"id": "r-4782215337665887188"}})
        == "r-4782215337665887188"
    )


def test_payload_without_a_draft_resource_does_not_use_a_bare_id() -> None:
    with pytest.raises(GmailDraftIdError, match="no draft id"):
        draft_id_from_payload({"id": "18c9f2a3b4d5e6f7", "threadId": "18c9f2a3b4d5e6f7"})


def test_google_workspace_setup_teaches_one_draft_id_format() -> None:
    text = SETUP_SKILL.read_text(encoding="utf-8")
    assert "## Gmail draft identity" in text
    assert "`draft.id` / `draftId`" in text
    assert "`message.id` and `threadId`" in text
    assert "Never pass these to a draft tool" in text
    assert "Do not invent a `#drafts?compose=` URL from a message id" in text
    assert "core.gmail_draft.draft_id_from_payload" in text
