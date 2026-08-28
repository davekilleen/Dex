from __future__ import annotations

import asyncio
import builtins
import importlib
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from core.mcp import onboarding_server, work_server
from core.utils import working_week

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def reset_working_week_cache():
    working_week._reset_cache()
    yield
    working_week._reset_cache()


def _write_profile(vault: Path, content: str) -> None:
    profile = vault / "System" / "user-profile.yaml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(content, encoding="utf-8")


def test_default_is_monday_to_friday_when_profile_is_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert working_week.get_working_days() == {0, 1, 2, 3, 4}


@pytest.mark.parametrize(
    "profile_content",
    [
        "name: Existing User\n",
        "working_week:\n  days: [monday\n",
    ],
)
def test_default_is_monday_to_friday_when_setting_is_absent_or_yaml_is_malformed(
    tmp_path: Path,
    monkeypatch,
    profile_content: str,
) -> None:
    _write_profile(tmp_path, profile_content)
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert working_week.get_working_days() == {0, 1, 2, 3, 4}


def test_default_is_monday_to_friday_when_profile_is_unreadable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(tmp_path, "working_week:\n  days: [sunday]\n")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    def refuse_profile_read(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr("builtins.open", refuse_profile_read)

    assert working_week.get_working_days() == {0, 1, 2, 3, 4}


def test_sunday_to_thursday_configuration_is_loaded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "working_week:\n"
        "  days: [sunday, monday, tuesday, wednesday, thursday]\n",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert working_week.get_working_days() == {6, 0, 1, 2, 3}


def test_full_names_abbreviations_and_integers_parse_case_insensitively(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "working_week:\n"
        "  days: [Sunday, MON, tUeSdAy, WED, 4, unknown, 8]\n",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert working_week.get_working_days() == {6, 0, 1, 2, 4}


def test_normalize_working_days_reuses_profile_parsing_rules() -> None:
    assert working_week.normalize_working_days(
        ["Sunday", "MON", "tUeSdAy", "sun", 4, "unknown", 8, True]
    ) == ["sunday", "monday", "tuesday", "friday"]


def test_integer_weekday_boundaries_zero_and_six_parse(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(tmp_path, "working_week:\n  days: [0, 6]\n")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert working_week.get_working_days() == {0, 6}


@pytest.mark.parametrize(
    "configured_days",
    [
        "[]",
        "[unknown, 8, -1]",
    ],
)
def test_zero_recognised_working_days_falls_back_to_monday_to_friday(
    tmp_path: Path,
    monkeypatch,
    configured_days: str,
) -> None:
    _write_profile(
        tmp_path,
        f"working_week:\n  days: {configured_days}\n",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert working_week.get_working_days() == {0, 1, 2, 3, 4}


def test_profile_is_loaded_once_until_the_cache_is_reset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _write_profile(tmp_path, "working_week:\n  days: [sunday]\n")

    assert working_week.get_working_days() == {6}

    _write_profile(tmp_path, "working_week:\n  days: [monday]\n")
    assert working_week.get_working_days() == {6}

    working_week._reset_cache()
    assert working_week.get_working_days() == {0}


def test_sunday_to_thursday_day_checks_and_display_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "working_week:\n"
        "  days: [sunday, monday, tuesday, wednesday, thursday]\n",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert working_week.is_working_day(date(2026, 7, 26)) is True
    assert working_week.is_working_day(date(2026, 7, 31)) is False
    assert working_week.working_day_names() == [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
    ]


def test_sunday_to_thursday_navigation_handles_working_and_non_working_days(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "working_week:\n"
        "  days: [sunday, monday, tuesday, wednesday, thursday]\n",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert working_week.next_working_day(date(2026, 7, 26)) == date(2026, 7, 27)
    assert working_week.next_working_day(date(2026, 7, 30)) == date(2026, 8, 2)
    assert working_week.next_working_day(date(2026, 7, 31)) == date(2026, 8, 2)

    for day in (
        date(2026, 7, 26),
        date(2026, 7, 29),
        date(2026, 7, 31),
        date(2026, 8, 1),
    ):
        assert working_week.first_working_day_of_week(day) == date(2026, 7, 26)
        assert working_week.last_working_day_of_week(day) == date(2026, 7, 30)


def test_monday_to_friday_navigation_handles_working_and_non_working_days(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert working_week.next_working_day(date(2026, 7, 27)) == date(2026, 7, 28)
    assert working_week.next_working_day(date(2026, 7, 31)) == date(2026, 8, 3)
    assert working_week.next_working_day(date(2026, 8, 1)) == date(2026, 8, 3)

    for day in (
        date(2026, 7, 27),
        date(2026, 7, 29),
        date(2026, 8, 1),
        date(2026, 8, 2),
    ):
        assert working_week.first_working_day_of_week(day) == date(2026, 7, 27)
        assert working_week.last_working_day_of_week(day) == date(2026, 7, 31)

    assert working_week.working_day_names() == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
    ]


def test_calendar_capacity_uses_sunday_to_thursday_working_week(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "working_week:\n"
        "  days: [sunday, monday, tuesday, wednesday, thursday]\n",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    working_week._reset_cache()
    monkeypatch.setattr(work_server, "_tz_today", lambda: date(2026, 7, 26))

    capacity = work_server.get_calendar_capacity_data(days_ahead=7)

    assert [day["day_name"] for day in capacity["days"]] == [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
    ]


def test_calendar_capacity_without_setting_keeps_monday_to_friday_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(tmp_path, "name: Existing User\n")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    working_week._reset_cache()
    monkeypatch.setattr(work_server, "_tz_today", lambda: date(2026, 7, 26))

    capacity = work_server.get_calendar_capacity_data(days_ahead=7)

    assert [day["day_name"] for day in capacity["days"]] == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
    ]


def test_work_server_import_fallback_keeps_monday_to_friday(
    monkeypatch,
) -> None:
    real_import = builtins.__import__

    def import_without_working_week(name, *args, **kwargs):
        if name == "core.utils.working_week":
            raise ImportError("working-week utility unavailable")
        return real_import(name, *args, **kwargs)

    try:
        with monkeypatch.context() as import_context:
            import_context.setattr(builtins, "__import__", import_without_working_week)
            importlib.reload(work_server)

            assert work_server._is_working_day(date(2026, 7, 31)) is True
            assert work_server._is_working_day(date(2026, 8, 1)) is False
    finally:
        importlib.reload(work_server)


def test_calendar_capacity_tool_handler_uses_configured_working_week(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "working_week:\n"
        "  days: [sunday, monday, tuesday, wednesday, thursday]\n",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    working_week._reset_cache()
    monkeypatch.setattr(work_server, "_tz_today", lambda: date(2026, 7, 26))

    result = asyncio.run(
        work_server.handle_call_tool(
            "analyze_calendar_capacity",
            {
                "days_ahead": 7,
                "events": [
                    {
                        "date": "2026-07-26",
                        "title": "Sunday planning",
                        "duration_minutes": 30,
                    }
                ],
            },
        )
    )
    payload = json.loads(result[0].text)

    assert [day["day_name"] for day in payload["days"]] == [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
    ]


def test_calendar_capacity_planning_ignores_nudges_and_keeps_meetings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "working_week:\n"
        "  days: [monday, tuesday, wednesday, thursday, friday]\n",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    working_week._reset_cache()
    monkeypatch.setattr(work_server, "_tz_today", lambda: date(2026, 7, 27))

    result = asyncio.run(
        work_server.handle_call_tool(
            "analyze_calendar_capacity",
            {
                "days_ahead": 1,
                "events": [
                    {
                        "date": "2026-07-27",
                        "title": "Customer review",
                        "duration_minutes": 60,
                        "calendar_name": "Work",
                    },
                    {
                        "date": "2026-07-27",
                        "title": "Plan today with Dex",
                        "duration_minutes": 30,
                        "calendar_name": " Dex ",
                    },
                    {
                        "date": "2026-07-27",
                        "title": "Review my week",
                        "duration_minutes": 30,
                        "calendar_name": "Work",
                        "notes": (
                            "Added by Dex · delete the Dex calendar to stop these"
                        ),
                    },
                ],
            },
        )
    )
    payload = json.loads(result[0].text)

    assert payload["days"][0]["meeting_count"] == 1
    assert payload["days"][0]["meeting_hours"] == 1.0


def test_task_scheduling_uses_configured_working_week(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_profile(
        tmp_path,
        "working_week:\n"
        "  days: [sunday, monday, tuesday, wednesday, thursday]\n",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    working_week._reset_cache()
    monkeypatch.setattr(work_server, "_tz_today", lambda: date(2026, 7, 26))
    monkeypatch.setattr(work_server, "get_all_tasks", lambda: [])
    monkeypatch.setattr(
        work_server,
        "generate_scheduling_suggestions",
        lambda _tasks, calendar_capacity: calendar_capacity,
    )

    result = asyncio.run(
        work_server.handle_call_tool(
            "suggest_task_scheduling",
            {
                "calendar_events": [
                    {
                        "date": "2026-07-26",
                        "title": "Sunday planning",
                        "duration_minutes": 30,
                    }
                ],
            },
        )
    )
    payload = json.loads(result[0].text)

    assert [day["day_name"] for day in payload["days"]] == [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
    ]


def test_onboarding_weekly_plan_starts_on_users_first_working_day(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 29)

    _write_profile(
        tmp_path,
        "working_week:\n"
        "  days: [sunday, monday, tuesday, wednesday, thursday]\n",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    working_week._reset_cache()
    monkeypatch.setattr(onboarding_server, "datetime", FixedDatetime)

    plan = onboarding_server.generate_weekly_plan(
        [
            {
                "title": "Sunday planning",
                "start": "2026-07-26T09:00:00",
                "end": "2026-07-26T10:00:00",
            },
            {
                "title": "Friday catch-up",
                "start": "2026-07-31T09:00:00",
                "end": "2026-07-31T10:00:00",
            },
        ],
        ["Customers"],
        "Founder",
    )

    assert plan.startswith("# Week Priorities - Jul 26 to Aug 01, 2026")
    assert "**Sunday** (1 meetings)" in plan
    assert "Sunday planning" in plan
    assert "**Friday**" not in plan
    assert "Friday catch-up" not in plan


def test_onboarding_import_fallback_keeps_monday_to_friday(
    monkeypatch,
) -> None:
    real_import = builtins.__import__

    def import_without_working_week(name, *args, **kwargs):
        if name == "core.utils.working_week":
            raise ImportError("working-week utility unavailable")
        return real_import(name, *args, **kwargs)

    try:
        with monkeypatch.context() as import_context:
            import_context.setattr(builtins, "__import__", import_without_working_week)
            importlib.reload(onboarding_server)

            assert onboarding_server.working_day_names() == [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
            ]
            assert onboarding_server.first_working_day_of_week(
                date(2026, 8, 2)
            ) == date(2026, 7, 27)
    finally:
        importlib.reload(onboarding_server)


def test_profile_template_ships_the_default_working_week() -> None:
    """The shipped template carries the Monday-Friday default.

    Asserted on the parsed value, not the literal text, so the comment above it
    can be reworded without breaking the build.
    """
    import yaml

    template = yaml.safe_load(
        (REPO_ROOT / "System/user-profile-template.yaml").read_text(encoding="utf-8")
    )

    assert template["working_week"]["days"] == [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
    ]


def test_next_working_day_from_events_skips_out_of_office_until_she_is_back() -> None:
    today = date(2026, 8, 28)
    without_ooo = working_week.next_working_day_from_events(today, [])
    assert without_ooo["date"] == "2026-08-31"
    assert without_ooo["spoken"] == "Monday 31 August"
    assert without_ooo["skipped_out_of_office"] is False

    with_ooo = working_week.next_working_day_from_events(
        today,
        [
            {
                "title": "Out of office",
                "start": "2026-08-29",
                "end": "2026-09-07",
                "all_day": True,
            }
        ],
    )
    assert with_ooo["date"] == "2026-09-07"
    assert with_ooo["spoken"] == "Monday 7 September"
    assert with_ooo["skipped_out_of_office"] is True
    assert with_ooo["out_until"] == "2026-09-06"


def test_out_of_office_event_type_covers_google_ooo_blocks() -> None:
    result = working_week.next_working_day_from_events(
        date(2026, 8, 28),
        [
            {
                "eventType": "outOfOffice",
                "start": date(2026, 8, 31),
                "end": date(2026, 9, 7),
                "all_day": True,
            }
        ],
    )
    assert result["date"] == "2026-09-07"
    assert result["spoken"] == "Monday 7 September"
