"""Regression coverage for which quarter the Work MCP answers goals for.

Someone preparing the next quarter early records that choice in their profile.
These tests hold the public `get_quarterly_goals` boundary to that choice, while
guaranteeing it can never take away goals the user can already see, and that the
Q1 2026 value seeded into early vaults can never strand anyone in an expired
quarter.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from core.mcp import work_server

TODAY = date(2026, 9, 7)  # inside Q3 2026 for a January fiscal year


def _call_quarterly_goals(arguments: dict | None = None) -> dict:
    result = asyncio.run(
        work_server.handle_call_tool("get_quarterly_goals", arguments or {})
    )
    return json.loads(result[0].text)


def _vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    current_quarter: str | None,
    goals_quarter: str,
    q1_start_month: int = 1,
    quarter_start: str | None = None,
    quarter_end: str | None = None,
) -> None:
    profile = tmp_path / "System/user-profile.yaml"
    profile.parent.mkdir(parents=True)
    lines = [
        "capabilities:",
        "  quarter_goals:",
        "    enabled: true",
        "quarterly_planning:",
        f"  q1_start_month: {q1_start_month}",
    ]
    if current_quarter is not None:
        lines.append(f"  current_quarter: {current_quarter}")
    if quarter_start is not None:
        lines.append(f"  quarter_start_date: {quarter_start}")
    if quarter_end is not None:
        lines.append(f"  quarter_end_date: {quarter_end}")
    profile.write_text("\n".join(lines) + "\n", encoding="utf-8")

    goals = tmp_path / "01-Quarter_Goals/Quarter_Goals.md"
    goals.parent.mkdir(parents=True)
    goals.write_text(
        f"---\nquarter: {goals_quarter}\n---\n"
        f"### 1. Prepare {goals_quarter} — **Growth** "
        f"^{goals_quarter.replace(' ', '-')}-goal-1\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", profile)
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals)
    monkeypatch.setattr(
        work_server, "get_week_priorities_file", lambda: tmp_path / "missing.md"
    )
    monkeypatch.setattr(work_server, "_tz_today", lambda: TODAY)


# --- the reported bug -------------------------------------------------------


def test_goals_written_for_the_declared_next_quarter_are_returned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The original report: next quarter chosen, goals written, nothing shown."""
    _vault(
        tmp_path,
        monkeypatch,
        current_quarter="Q4 2026",
        goals_quarter="Q4 2026",
        quarter_start="2026-10-01",
        quarter_end="2026-12-31",
    )

    result = _call_quarterly_goals()

    assert result["quarter"] == "Q4 2026"
    assert result["count"] == 1
    assert result["goals"][0]["title"] == "Prepare Q4 2026"


def test_declared_quarter_is_honored_when_its_cached_dates_are_blank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shipped profile shape leaves the cached dates empty."""
    _vault(
        tmp_path, monkeypatch, current_quarter="Q4 2026", goals_quarter="Q4 2026"
    )

    result = _call_quarterly_goals()

    assert result["quarter"] == "Q4 2026"
    assert result["count"] == 1


# --- the fix must never take goals away -------------------------------------


def test_declaring_next_quarter_never_hides_the_goals_you_already_have(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Choosing next quarter before writing its goals must not blank the page.

    This is the shape that matters most: the goals file is still this quarter's,
    and answering for the declared quarter would replace one visible goal with an
    empty list — the very complaint being fixed.
    """
    _vault(
        tmp_path, monkeypatch, current_quarter="Q4 2026", goals_quarter="Q3 2026"
    )

    result = _call_quarterly_goals()

    assert result["quarter"] == "Q3 2026"
    assert result["count"] == 1
    assert result["goals"][0]["title"] == "Prepare Q3 2026"


# --- expired and out-of-range declarations ----------------------------------


def test_the_old_seeded_q1_2026_value_is_ignored_even_with_matching_goals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Early vaults were seeded with Q1 2026 and nothing ever rewrites it."""
    _vault(
        tmp_path,
        monkeypatch,
        current_quarter="Q1 2026",
        goals_quarter="Q1 2026",
        quarter_start="2026-01-01",
        quarter_end="2026-03-31",
    )

    result = _call_quarterly_goals()

    assert result["quarter"] == "Q3 2026"
    assert result["count"] == 0


def test_a_quarter_beyond_the_next_one_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _vault(
        tmp_path, monkeypatch, current_quarter="Q2 2027", goals_quarter="Q2 2027"
    )

    result = _call_quarterly_goals()

    assert result["quarter"] == "Q3 2026"


@pytest.mark.parametrize(
    "value", ["next quarter", "q4 2026", "Q4-2026", "2026 Q4", "Q5 2026", ""]
)
def test_an_unreadable_declared_quarter_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    _vault(tmp_path, monkeypatch, current_quarter=value, goals_quarter="Q3 2026")

    result = _call_quarterly_goals()

    assert result["quarter"] == "Q3 2026"
    assert result["count"] == 1


def test_an_explicit_quarter_argument_still_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _vault(
        tmp_path, monkeypatch, current_quarter="Q4 2026", goals_quarter="Q4 2026"
    )

    result = _call_quarterly_goals({"quarter": "Q3 2026"})

    assert result["quarter"] == "Q3 2026"
    assert result["count"] == 0


# --- pacing and "which quarter is it now" must not move ---------------------


def test_a_declared_quarter_never_moves_what_quarter_it_is_now(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_quarter_info drives velocity and weekly pacing.

    Pointing it at a quarter that has not started yet yields negative elapsed
    weeks and a "behind pace" verdict for a quarter nobody has begun, so the
    declared quarter must not reach it.
    """
    _vault(
        tmp_path, monkeypatch, current_quarter="Q4 2026", goals_quarter="Q4 2026"
    )

    info = work_server.get_quarter_info()

    assert info["quarter"] == "Q3 2026"
    assert info["start_date"] == date(2026, 7, 1)
    assert info["end_date"] == date(2026, 9, 30)
    assert info["weeks_remaining"] >= 0


# --- the safety window itself -----------------------------------------------


@pytest.mark.parametrize("q1_start_month", list(range(1, 13)))
def test_an_expired_declaration_is_rejected_for_every_fiscal_year_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    q1_start_month: int,
) -> None:
    """A quarter labelled two years ago has ended under any fiscal calendar."""
    _vault(
        tmp_path,
        monkeypatch,
        current_quarter="Q1 2024",
        goals_quarter="Q1 2024",
        q1_start_month=q1_start_month,
    )

    assert work_server._declared_planning_quarter(TODAY) is None


@pytest.mark.parametrize("q1_start_month", list(range(1, 13)))
def test_a_far_future_declaration_is_rejected_for_every_fiscal_year_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    q1_start_month: int,
) -> None:
    """Nothing more than one quarter ahead may be honored, whatever the calendar."""
    _vault(
        tmp_path,
        monkeypatch,
        current_quarter="Q1 2029",
        goals_quarter="Q1 2029",
        q1_start_month=q1_start_month,
    )

    assert work_server._declared_planning_quarter(TODAY) is None


def _quarter_windows_by_stepping(q1_start_month: int) -> list:
    """Every fiscal quarter from 2023 to 2029, built by walking months forward.

    Deliberately a different construction from the implementation's month-index
    arithmetic, so this is an independent oracle rather than a restatement.
    """
    import calendar as _calendar

    windows = []
    year, month = 2023, q1_start_month
    while year < 2030:
        start = date(year, month, 1)
        end_month, end_year = month, year
        for _ in range(2):
            end_month += 1
            if end_month > 12:
                end_month, end_year = 1, end_year + 1
        end = date(
            end_year, end_month, _calendar.monthrange(end_year, end_month)[1]
        )
        windows.append((start, end))
        month += 3
        if month > 12:
            month -= 12
            year += 1
    return windows


@pytest.mark.parametrize("q1_start_month", list(range(1, 13)))
def test_an_accepted_declaration_is_always_the_live_or_next_quarter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    q1_start_month: int,
) -> None:
    """Sweeps every day of 2026, including the quarter-end days.

    An earlier version of this guard allowed anything starting within 92 days,
    which let a quarter *two* ahead through on the last day of a quarter. The
    oracle here is built by stepping months forward, independently of the
    implementation, so it can catch that class of bug.
    """
    profile = tmp_path / "System/user-profile.yaml"
    profile.parent.mkdir(parents=True)
    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", profile)

    windows = _quarter_windows_by_stepping(q1_start_month)
    accepted_days = 0

    # Every quarter boundary in 2026 and the days either side of it, plus a
    # mid-month sample: the boundaries are where an off-by-one shows up.
    probe_days = set()
    for start, end in windows:
        for anchor in (start, end):
            for delta in (-1, 0, 1):
                candidate = anchor + timedelta(days=delta)
                if candidate.year == 2026:
                    probe_days.add(candidate)
    for month in range(1, 13):
        probe_days.add(date(2026, month, 15))

    for day in sorted(probe_days):
        live = next(i for i, (s, e) in enumerate(windows) if s <= day <= e)
        allowed_windows = {windows[live], windows[live + 1]}

        for label_year in (2025, 2026, 2027):
            for num in (1, 2, 3, 4):
                profile.write_text(
                    "quarterly_planning:\n"
                    f"  q1_start_month: {q1_start_month}\n"
                    f"  current_quarter: Q{num} {label_year}\n",
                    encoding="utf-8",
                )
                got = work_server._declared_planning_quarter(day)
                if got is None:
                    continue
                accepted_days += 1
                # Whatever was accepted must name one of exactly two windows.
                matching = [
                    w
                    for w in allowed_windows
                    if work_server._fiscal_quarter_label(w[0], q1_start_month) == got
                    or work_server._fiscal_quarter_label(w[1], q1_start_month) == got
                ]
                assert matching, (
                    f"honored {got!r} on {day} for q1_start_month="
                    f"{q1_start_month}, but that is neither the live quarter "
                    f"{windows[live]} nor the next one {windows[live + 1]}"
                )

    assert accepted_days > 0, "the sweep never accepted anything — it proves nothing"


def test_the_day_a_quarter_ends_does_not_admit_the_quarter_after_next(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact days an earlier 92-day bound got wrong."""
    profile = tmp_path / "System/user-profile.yaml"
    profile.parent.mkdir(parents=True)
    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", profile)

    for today, two_ahead, next_one in [
        (date(2026, 3, 31), "Q3 2026", "Q2 2026"),
        (date(2026, 12, 31), "Q2 2027", "Q1 2027"),
    ]:
        profile.write_text(
            "quarterly_planning:\n  q1_start_month: 1\n"
            f"  current_quarter: {two_ahead}\n",
            encoding="utf-8",
        )
        assert work_server._declared_planning_quarter(today) is None

        profile.write_text(
            "quarterly_planning:\n  q1_start_month: 1\n"
            f"  current_quarter: {next_one}\n",
            encoding="utf-8",
        )
        assert work_server._declared_planning_quarter(today) == next_one


def test_a_near_miss_quarter_string_is_reported_not_swallowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """"q4 2026" must not look identical to the bug of ignoring the choice."""
    _vault(tmp_path, monkeypatch, current_quarter="q4 2026", goals_quarter="Q3 2026")

    with caplog.at_level("WARNING", logger=work_server.logger.name):
        assert work_server._declared_planning_quarter(TODAY) is None

    assert any("q4 2026" in record.getMessage() for record in caplog.records), (
        caplog.text
    )


def test_an_empty_declaration_is_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The shipped default is empty; it must not warn on every call."""
    _vault(tmp_path, monkeypatch, current_quarter="", goals_quarter="Q3 2026")

    with caplog.at_level("WARNING", logger=work_server.logger.name):
        assert work_server._declared_planning_quarter(TODAY) is None

    assert not caplog.records, caplog.text
