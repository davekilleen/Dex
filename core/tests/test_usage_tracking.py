"""Proof that marking a feature as used actually writes, and never writes the wrong thing.

The adoption checkboxes in usage_log.md had a reader and no writer: 34 skills
instructed the assistant to hand-edit the file, nothing verified that it had,
and a run where the edit was skipped looked exactly like a run where it was not.
These tests exist so that failure mode cannot come back silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.mcp import analytics_helper

LOG_WITH_CONSENT = """# Dex Usage Tracking

**Consent asked:** yes
**Consent decision:** opted-in
**Health telemetry:** opted-out

## Core Workflows

- [x] Daily planning (`/daily-plan`)
- [ ] Meeting prep (`/meeting-prep`)
- [ ] Person page created
- [ ] Journaling (`/journal`)
- [ ] Journaling setup (`/journal`)
"""


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "System").mkdir(parents=True)
    (tmp_path / "System" / "usage_log.md").write_text(LOG_WITH_CONSENT, encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    return tmp_path


def _log(vault: Path) -> str:
    return (vault / "System" / "usage_log.md").read_text(encoding="utf-8")


def test_marking_an_unticked_feature_writes_the_box(vault: Path) -> None:
    result = analytics_helper.mark_feature_used("meeting-prep")

    assert result["status"] == "marked"
    assert result["label"] == "Meeting prep (`/meeting-prep`)"
    assert "- [x] Meeting prep (`/meeting-prep`)" in _log(vault)


def test_a_leading_slash_is_accepted(vault: Path) -> None:
    assert analytics_helper.mark_feature_used("/meeting-prep")["status"] == "marked"
    assert "- [x] Meeting prep (`/meeting-prep`)" in _log(vault)


def test_a_plain_label_without_a_command_is_matched(vault: Path) -> None:
    result = analytics_helper.mark_feature_used("Person page created")

    assert result["status"] == "marked"
    assert "- [x] Person page created" in _log(vault)


def test_marking_twice_is_idempotent_and_writes_nothing_the_second_time(vault: Path) -> None:
    analytics_helper.mark_feature_used("meeting-prep")
    after_first = _log(vault)

    result = analytics_helper.mark_feature_used("meeting-prep")

    assert result["status"] == "already_marked"
    assert _log(vault) == after_first


def test_an_ambiguous_name_reports_candidates_and_changes_nothing(vault: Path) -> None:
    before = _log(vault)

    result = analytics_helper.mark_feature_used("journal")

    assert result["status"] == "ambiguous"
    assert sorted(result["candidates"]) == [
        "Journaling (`/journal`)",
        "Journaling setup (`/journal`)",
    ]
    assert _log(vault) == before


def test_an_unknown_feature_changes_nothing(vault: Path) -> None:
    before = _log(vault)

    assert analytics_helper.mark_feature_used("no-such-skill")["status"] == "not_found"
    assert _log(vault) == before


def test_consent_lines_are_never_touched(vault: Path) -> None:
    analytics_helper.mark_feature_used("meeting-prep")
    updated = _log(vault)

    assert "**Consent asked:** yes" in updated
    assert "**Consent decision:** opted-in" in updated
    assert "**Health telemetry:** opted-out" in updated
    assert analytics_helper.check_consent() == "opted-in"


def test_every_other_line_survives_byte_for_byte(vault: Path) -> None:
    before = _log(vault).splitlines()

    analytics_helper.mark_feature_used("meeting-prep")

    after = _log(vault).splitlines()
    assert len(before) == len(after)
    changed = [(b, a) for b, a in zip(before, after) if b != a]
    assert changed == [
        ("- [ ] Meeting prep (`/meeting-prep`)", "- [x] Meeting prep (`/meeting-prep`)")
    ]


def test_a_missing_log_is_reported_not_raised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    result = analytics_helper.mark_feature_used("meeting-prep")

    assert result["status"] == "unavailable"
    assert not (tmp_path / "System" / "usage_log.md").exists()


def test_marking_leaves_no_temp_file_behind(vault: Path) -> None:
    analytics_helper.mark_feature_used("meeting-prep")

    assert list((vault / "System").glob("*.tmp")) == []


def test_marking_never_sends_anything(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Local bookkeeping must not depend on, or trigger, the analytics transport."""
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("mark_feature_used must not fire an analytics event")

    monkeypatch.setattr(analytics_helper, "fire_event", explode)

    assert analytics_helper.mark_feature_used("meeting-prep")["status"] == "marked"


def test_it_runs_when_analytics_consent_is_declined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Adoption tracking is local, so opting out of analytics must not disable it."""
    (tmp_path / "System").mkdir(parents=True)
    (tmp_path / "System" / "usage_log.md").write_text(
        LOG_WITH_CONSENT.replace("opted-in", "opted-out"), encoding="utf-8"
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert analytics_helper.check_consent() == "opted-out"
    assert analytics_helper.is_analytics_enabled() is False
    assert analytics_helper.mark_feature_used("meeting-prep")["status"] == "marked"


def test_the_reader_sees_what_the_writer_wrote(vault: Path) -> None:
    """The parsed feature map was dead code; this is the loop closing."""
    assert analytics_helper.load_usage_log()["features"]["Meeting prep (`/meeting-prep`)"] is False

    analytics_helper.mark_feature_used("meeting-prep")

    assert analytics_helper.load_usage_log()["features"]["Meeting prep (`/meeting-prep`)"] is True


# --- the tool has to be reachable, which is the half that was missing ---


def _decode(result: list) -> dict:
    import json

    return json.loads(result[0].text)


def test_the_tool_is_registered_on_the_analytics_server() -> None:
    """The helper existed for months but no skill could reach it."""
    import asyncio

    from core.mcp import analytics_server

    names = {tool.name for tool in asyncio.run(analytics_server.list_tools())}

    assert "mark_feature_used" in names


def test_the_registered_tool_marks_a_feature_end_to_end(vault: Path) -> None:
    import asyncio

    from core.mcp import analytics_server

    payload = _decode(
        asyncio.run(analytics_server.call_tool("mark_feature_used", {"feature": "meeting-prep"}))
    )

    assert payload["status"] == "marked"
    assert "- [x] Meeting prep (`/meeting-prep`)" in _log(vault)


def test_the_registered_tool_reports_an_unknown_feature_rather_than_failing(vault: Path) -> None:
    import asyncio

    from core.mcp import analytics_server

    payload = _decode(
        asyncio.run(analytics_server.call_tool("mark_feature_used", {"feature": "no-such-skill"}))
    )

    assert payload["status"] == "not_found"
