"""Captured learnings are worth nothing until something routes them.

These cover the mechanical half only: parsing, clustering, the trigger, and
recording an outcome. Applying an edit stays in the skill, because it must be
shown and confirmed first.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from core.utils import learning_routing as routing

TODAY = date(2026, 8, 19)


def _day_file(vault: Path, day: str, body: str) -> Path:
    folder = vault / routing.LEARNINGS_RELATIVE
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.md"
    path.write_text(f"# Session Learnings - {day}\n\n---\n\n{body}", encoding="utf-8")
    return path


ENTRY = """## 09:15 - Correction

**What was said:**

> stop over inferring from timesheet codes

**Why it matters:** it invents facts about the day.
**Status:** pending

---

## 11:40 - Correction

**What was said:**

> the daily-plan skill skipped step 5.8 entirely

**Why it matters:** an unrun step looks identical to an empty one.
**Status:** pending

---
"""


def test_entries_are_parsed_with_their_location(tmp_path):
    path = _day_file(tmp_path, "2026-08-18", ENTRY)

    entries = routing.parse_file(path)

    assert len(entries) == 2
    assert entries[0].time == "09:15"
    assert "timesheet codes" in entries[0].body
    assert entries[0].day == date(2026, 8, 18)
    assert all(e.is_pending for e in entries)


def test_a_file_that_is_not_a_day_is_ignored(tmp_path):
    folder = tmp_path / routing.LEARNINGS_RELATIVE
    folder.mkdir(parents=True)
    readme = folder / "README.md"
    readme.write_text("## 09:00 - not a learning\n**Status:** pending\n", encoding="utf-8")

    assert routing.parse_file(readme) == []


def test_a_malformed_file_yields_nothing_rather_than_raising(tmp_path):
    path = _day_file(tmp_path, "2026-08-18", "no entries here at all\n")

    assert routing.parse_file(path) == []


def test_already_routed_entries_are_not_pending(tmp_path):
    _day_file(
        tmp_path,
        "2026-08-18",
        "## 09:15 - Done one\n\n**Status:** implemented (2026-08-18 — CLAUDE-custom.md)\n\n---\n",
    )

    entries = routing.read_all(tmp_path)

    assert len(entries) == 1
    assert routing.pending(entries) == []


def test_clusters_group_by_destination_not_by_wording(tmp_path):
    _day_file(tmp_path, "2026-08-18", ENTRY)

    clusters = routing.cluster(routing.read_all(tmp_path))
    kinds = {c.kind for c in clusters}

    assert "behavioural" in kinds
    assert "skill-defect" in kinds
    for c in clusters:
        assert c.destination, "every cluster must name where it goes"


def test_a_cluster_of_several_entries_becomes_one_edit(tmp_path):
    """Josh's point: eight related entries are one rule, not eight edits."""
    many = "".join(
        f"## 0{n}:00 - Correction\n\n> stop assuming, always verify first\n\n**Status:** pending\n\n---\n\n"
        for n in range(1, 5)
    )
    _day_file(tmp_path, "2026-08-18", many)

    clusters = routing.cluster(routing.read_all(tmp_path))

    assert len(clusters) == 1
    assert len(clusters[0].entries) == 4


def test_the_trigger_fires_on_volume(tmp_path):
    body = "".join(
        f"## 09:{n:02d} - Correction\n\n> stop doing that\n\n**Status:** pending\n\n---\n\n"
        for n in range(12)
    )
    _day_file(tmp_path, "2026-08-19", body)

    due, reason = routing.should_review(routing.read_all(tmp_path), today=TODAY)

    assert due is True
    assert "pending" in reason


def test_the_trigger_fires_on_age_even_for_a_single_entry(tmp_path):
    """A count-only trigger never fires on a slow, steady leak."""
    old = (TODAY - timedelta(days=30)).isoformat()
    _day_file(tmp_path, old, "## 09:00 - Correction\n\n> stop that\n\n**Status:** pending\n\n---\n")

    due, reason = routing.should_review(routing.read_all(tmp_path), today=TODAY)

    assert due is True
    assert "days old" in reason


def test_the_trigger_stays_quiet_on_a_small_recent_backlog(tmp_path):
    """A hook that fires into a healthy vault is noise."""
    _day_file(tmp_path, "2026-08-19", "## 09:00 - Correction\n\n> stop that\n\n**Status:** pending\n\n---\n")

    due, _ = routing.should_review(routing.read_all(tmp_path), today=TODAY)

    assert due is False


def test_the_trigger_is_silent_on_an_empty_vault(tmp_path):
    due, reason = routing.should_review(routing.read_all(tmp_path), today=TODAY)

    assert due is False
    assert reason == "nothing pending"


def test_recording_an_outcome_says_where_it_went(tmp_path):
    path = _day_file(tmp_path, "2026-08-18", ENTRY)
    entry = routing.parse_file(path)[0]

    assert routing.set_status(entry, routing.IMPLEMENTED, "CLAUDE-custom.md", today=TODAY) is True

    text = path.read_text(encoding="utf-8")
    assert "**Status:** implemented (2026-08-19 — CLAUDE-custom.md)" in text
    # A falling count must mean something was installed, not that it aged out.
    assert routing.pending(routing.parse_file(path)) != routing.parse_file(path)


def test_dropping_an_entry_records_why(tmp_path):
    path = _day_file(tmp_path, "2026-08-18", ENTRY)
    entry = routing.parse_file(path)[0]

    routing.set_status(entry, routing.DROPPED, "already covered by an existing rule", today=TODAY)

    assert "dropped (2026-08-19 — already covered" in path.read_text(encoding="utf-8")


def test_two_entries_in_one_file_never_have_their_statuses_crossed(tmp_path):
    path = _day_file(tmp_path, "2026-08-18", ENTRY)
    second = routing.parse_file(path)[1]

    routing.set_status(second, routing.IMPLEMENTED, "process-meetings SKILL.md", today=TODAY)

    reparsed = routing.parse_file(path)
    assert reparsed[0].is_pending, "the first entry must be untouched"
    assert reparsed[1].status == routing.IMPLEMENTED


def test_an_invented_status_is_refused(tmp_path):
    """Without a third state, stale entries either linger or get quietly deleted."""
    path = _day_file(tmp_path, "2026-08-18", ENTRY)
    entry = routing.parse_file(path)[0]

    with pytest.raises(ValueError):
        routing.set_status(entry, "done", "somewhere")
