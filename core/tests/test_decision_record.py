"""Read-only decision-record lookup for the unpublished connector box."""

from __future__ import annotations

from pathlib import Path

from core.context.decision_record import ask_what_was_decided


def _write_decision_log(vault: Path, *, title: str, decision: str, date: str = "2026-04-12") -> Path:
    folder = vault / "06-Resources" / "Decisions"
    folder.mkdir(parents=True)
    path = folder / "Decision_Log.md"
    path.write_text(
        f"## {date} — {title}\n\n"
        f"**Decision:** {decision}\n\n"
        "**Context:** The choice had to be written down.\n",
        encoding="utf-8",
    )
    return path


def test_ask_returns_the_decision_and_the_file(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    _write_decision_log(
        vault,
        title="Keep pricing annual-only",
        decision="Sell only annual plans.",
    )
    payload = ask_what_was_decided(vault, "what was decided about pricing")
    assert payload["found"] is True
    assert payload["matches"][0]["decision"] == "Sell only annual plans."
    assert payload["matches"][0]["file"] == "06-Resources/Decisions/Decision_Log.md"
    assert payload["matches"][0]["title"] == "Keep pricing annual-only"


def test_ask_reads_a_project_decision_record(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    project = vault / "04-Projects" / "Checkout"
    project.mkdir(parents=True)
    (project / "Decisions.md").write_text(
        "## 2026-05-01 — Pause guest checkout\n\n"
        "**Decision:** Guest checkout stays off until fraud review finishes.\n",
        encoding="utf-8",
    )
    payload = ask_what_was_decided(vault, "guest checkout")
    assert payload["found"] is True
    assert payload["matches"][0]["file"] == "04-Projects/Checkout/Decisions.md"
    assert "Guest checkout stays off" in payload["matches"][0]["decision"]


def test_ask_does_not_invent_or_use_meeting_notes(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    meetings = vault / "00-Inbox" / "Meetings"
    meetings.mkdir(parents=True)
    (meetings / "2026-04-12 - Pricing.md").write_text(
        "## Notes\n\nWe decided to give pricing away for free.\n",
        encoding="utf-8",
    )
    payload = ask_what_was_decided(vault, "pricing")
    assert payload["found"] is False
    assert payload["matches"] == []


def test_ask_skips_symlinks_and_paths_outside_the_folder(tmp_path: Path) -> None:
    vault = tmp_path / "Dex"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text(
        "## 2026-01-01 — Secret\n\n**Decision:** Do not leak this.\n",
        encoding="utf-8",
    )
    folder = vault / "06-Resources" / "Decisions"
    folder.mkdir(parents=True)
    (folder / "Decision_Log.md").symlink_to(outside)
    payload = ask_what_was_decided(vault, "Secret")
    assert payload["found"] is False
    assert ask_what_was_decided(None, "Secret")["found"] is False
    assert ask_what_was_decided(vault, "")["found"] is False
    assert ask_what_was_decided(vault, object())["found"] is False
