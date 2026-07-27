from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from core.utils import working_week

MARKER = "Added by Dex · delete the Dex calendar to stop these"
WEEKLY_SUMMARY = "Weekly wrap-up with Dex (5 min)"
TEACHING_COPY = (
    (
        "Plan today with Dex (2 min)",
        (
            'Say this: "Plan my day."',
            "Dex reads your calendar and your tasks and hands back a plan for the day: what's fixed, what's yours to move, and the one thing worth protecting.",
            "Skill: /daily-plan",
            "https://heydex.ai/help/daily-rhythm.html",
        ),
    ),
    (
        "What your calendar says you value",
        (
            'Paste this: "Look at my last eight weeks of meetings. Ignore what the events are called — work out what my calendar says I actually value: who gets my time, what share is reactive versus chosen. Then compare against my pillars. Where does my time contradict my stated priorities?"',
            "Works from day one, because Dex already has your real calendar.",
            "Skill: /xray — ask Dex how it worked that out",
            "https://heydex.ai/help/prompts-to-steal.html",
        ),
    ),
    (
        "Let Dex interview you (10 min)",
        (
            'Paste this: "Interview me so you can work brilliantly with me. Ask one question at a time — never a list. Cover what I actually do day to day, the goals I\'m measured on, who my stakeholders are, how I like to work, and what keeps going wrong. Then update my profile with what you learned and show me what changed."',
            "You're bad at guessing what an AI needs to know about you. It's very good at pulling it out of you. Everything after today gets better.",
            "Answer out loud with dictation if you can. You'll say twice as much, and the messy honesty is the good part.",
            "Skill: /identity-snapshot",
            "https://heydex.ai/help/make-it-your-own.html",
        ),
    ),
    (
        "Think out loud, get finished work back",
        (
            'Paste this: "I\'m going to dump thoughts at you in no particular order. Don\'t respond beyond \'noted\'. When I say HARVEST, turn everything into a board update, in my voice, ready to use. File anything that sounds like a task where it belongs."',
            "Best on a walk after a big meeting. Dump the debrief, say HARVEST, done — and the leftovers get filed instead of lost.",
            "Skill: /triage",
            "https://heydex.ai/help/capture.html",
        ),
    ),
    (
        "Make Dex argue against you",
        (
            'Paste this: "Here\'s what I\'m about to do: [decision]. You have my goals and my history. Make the strongest honest case AGAINST it — not strawmen, the version my smartest critic would make. Then tell me what evidence would change your mind, and what you\'d do instead."',
            "Most people use AI to agree with them. This is the opposite, and it's where the value is.",
            "Skill: /decision-log",
            "https://heydex.ai/help/goals-decisions.html",
        ),
    ),
    (
        "Ask what you could build but haven't",
        (
            'Paste this: "List every tool and connection you have access to in this vault. Then, knowing my role and goals: what are the five most valuable workflows we could build that I\'m not using? For each, what it does, what it needs, and the effort. Rank by payoff."',
            'Don\'t start from your problems, start from what your system can already reach. When one lands, say "turn that into a skill" and it becomes a command you keep forever.',
            "Skill: /create-skill",
            "https://heydex.ai/help/make-it-your-own.html",
        ),
    ),
    (
        "Get an idea properly grilled",
        (
            'Paste this: "I have a rough idea: [one sentence]. Don\'t develop it yet. Act as a sharp product manager and grill me with questions, one at a time, until it\'s properly thought through. When I say done, switch roles: become a skeptical CFO and grill me on cost and payoff. Then write the one-pager."',
            "Swap the personas for whoever actually scares you — your board, your best customer, your most pedantic engineer.",
            "Skill: /product-brief",
            "https://heydex.ai/help/prompts-to-steal.html",
        ),
    ),
    (
        "Write the post-mortem before it happens",
        (
            'Paste this: "It\'s three months from now and [project] has failed. Using what you know about this project, my team and how I work, write the honest post-mortem. What killed it? What early warning did I ignore? Then: the cheapest thing I could do this week to make that story not come true."',
            "Skill: /project-health",
            "https://heydex.ai/help/people-projects.html",
        ),
    ),
    (
        "Catch Dex up on a meeting",
        (
            'Say this: "I just had a meeting with [who] about [what] — here\'s what happened."',
            "Dex pulls out the decisions, the promises and who owes what, and files them against the right people and projects. Connect a meeting tool later and it does this without you typing.",
            "Skill: /process-meetings",
            "https://heydex.ai/help/meetings.html",
        ),
    ),
    (
        "Ask Dex what you're still not using",
        (
            'Say this: "Look at everything we\'ve done together so far. How am I doing, and what else could I be using you for?"',
            "Two weeks of real work in. This is the moment to find out what Dex has noticed, and what it can do that you haven't touched.",
            "Skill: /dex-level-up",
            "https://heydex.ai/help/",
        ),
    ),
)
GRANOLA_DAY_NINE = (
    "Find out what you've promised people",
    (
        'Paste this: "Go through my meeting notes from the last month. Find every commitment I made — including soft ones like \'I\'ll take a look\' — and check each against what\'s actually been done. Show me the open promises, oldest first, with who I made them to."',
        "It lands here on purpose: by now you have a fortnight of real meetings for it to work on. Brutal before a 1:1.",
        "Skill: /commitments",
        "https://heydex.ai/help/meetings.html",
    ),
)


@pytest.fixture(autouse=True)
def reset_working_week_cache() -> None:
    working_week._reset_cache()
    yield
    working_week._reset_cache()


def _configure_working_week(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    days: list[str],
) -> None:
    profile = vault / "System" / "user-profile.yaml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        f"working_week:\n  days: [{', '.join(days)}]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VAULT_PATH", str(vault))


def _unfold_lines(calendar_text: str) -> list[str]:
    unfolded: list[str] = []
    for line in calendar_text.split("\r\n"):
        if line.startswith(" "):
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _events(calendar_text: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in _unfold_lines(calendar_text):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            assert current is not None
            events.append(current)
            current = None
        elif current is not None:
            key, value = line.split(":", 1)
            current[key] = value
    return events


def _unescape_text(value: str) -> str:
    replacements = {
        "n": "\n",
        "N": "\n",
        ",": ",",
        ";": ";",
        "\\": "\\",
    }
    return re.sub(
        r"\\([nN,;\\])",
        lambda match: replacements[match.group(1)],
        value,
    )


def _summary(event: dict[str, str]) -> str:
    return _unescape_text(event["SUMMARY"])


def _description(event: dict[str, str]) -> str:
    return _unescape_text(event["DESCRIPTION"])


def test_monday_to_friday_calendar_skips_weekends_and_wraps_up_on_friday(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.utils.nudge_calendar import build_nudge_calendar

    _configure_working_week(
        tmp_path,
        monkeypatch,
        ["monday", "tuesday", "wednesday", "thursday", "friday"],
    )

    events = _events(build_nudge_calendar(date(2026, 7, 26)))
    dated_events = [
        (
            datetime.strptime(event["DTSTART;VALUE=DATE"], "%Y%m%d").date(),
            _summary(event),
        )
        for event in events
    ]

    assert all(event_date.weekday() not in {5, 6} for event_date, _ in dated_events)
    assert {
        event_date.weekday()
        for event_date, summary in dated_events
        if summary == WEEKLY_SUMMARY
    } == {4}


def test_sunday_to_thursday_calendar_skips_friday_and_saturday(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.utils.nudge_calendar import build_nudge_calendar

    _configure_working_week(
        tmp_path,
        monkeypatch,
        ["sunday", "monday", "tuesday", "wednesday", "thursday"],
    )

    events = _events(build_nudge_calendar(date(2026, 7, 25)))
    dated_events = [
        (
            datetime.strptime(event["DTSTART;VALUE=DATE"], "%Y%m%d").date(),
            _summary(event),
        )
        for event in events
    ]

    assert all(event_date.weekday() not in {4, 5} for event_date, _ in dated_events)
    assert {
        event_date.weekday()
        for event_date, summary in dated_events
        if summary == WEEKLY_SUMMARY
    } == {3}
    assert [event["RRULE"] for event in events if "RRULE" in event] == [
        "FREQ=WEEKLY;BYDAY=TH"
    ]


@pytest.mark.parametrize(
    "start_from",
    [date(2026, 7, 27) + timedelta(days=offset) for offset in range(7)],
)
def test_run_always_starts_on_the_next_working_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    start_from: date,
) -> None:
    from core.utils.nudge_calendar import build_nudge_calendar

    _configure_working_week(
        tmp_path,
        monkeypatch,
        ["monday", "tuesday", "wednesday", "thursday", "friday"],
    )

    first_event = _events(build_nudge_calendar(start_from))[0]
    first_date = datetime.strptime(
        first_event["DTSTART;VALUE=DATE"],
        "%Y%m%d",
    ).date()

    assert first_date == working_week.next_working_day(start_from)
    assert first_date != start_from
    assert working_week.is_working_day(first_date)


def test_every_event_is_private_transparent_all_day_and_has_no_alarm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.utils.nudge_calendar import build_nudge_calendar

    _configure_working_week(
        tmp_path,
        monkeypatch,
        ["monday", "tuesday", "wednesday", "thursday", "friday"],
    )
    calendar_text = build_nudge_calendar(date(2026, 7, 26))
    events = _events(calendar_text)

    assert "VALARM" not in calendar_text
    assert len({event["UID"] for event in events}) == len(events)
    for event in events:
        start = datetime.strptime(event["DTSTART;VALUE=DATE"], "%Y%m%d").date()
        end = datetime.strptime(event["DTEND;VALUE=DATE"], "%Y%m%d").date()
        assert end == start + timedelta(days=1)
        assert event["TRANSP"] == "TRANSPARENT"
        assert event["CLASS"] == "PRIVATE"
        assert event["DTSTAMP"] == "20260726T000000Z"


def test_calendar_metadata_line_folding_and_open_ended_recurrence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.utils.nudge_calendar import build_nudge_calendar

    _configure_working_week(
        tmp_path,
        monkeypatch,
        ["monday", "tuesday", "wednesday", "thursday", "friday"],
    )
    calendar_text = build_nudge_calendar(date(2026, 7, 26))
    unfolded = _unfold_lines(calendar_text)
    events = _events(calendar_text)
    recurring = [event["RRULE"] for event in events if "RRULE" in event]

    assert unfolded[:6] == [
        "BEGIN:VCALENDAR",
        "PRODID:-//Dex//First-Month Nudge Calendar//EN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Dex",
    ]
    assert calendar_text.endswith("\r\n")
    assert all(
        len(line.encode("utf-8")) <= 75
        for line in calendar_text.split("\r\n")
    )
    assert recurring == ["FREQ=WEEKLY;BYDAY=FR"]
    assert "UNTIL" not in recurring[0]
    assert "COUNT" not in recurring[0]


def test_teaching_events_appear_once_in_order_with_exact_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.utils.nudge_calendar import build_nudge_calendar

    _configure_working_week(
        tmp_path,
        monkeypatch,
        ["monday", "tuesday", "wednesday", "thursday", "friday"],
    )
    events = _events(
        build_nudge_calendar(
            date(2026, 7, 26),
            granola_connected=False,
        )
    )
    teaching_summaries = [summary for summary, _ in TEACHING_COPY]
    teaching_events = [
        event for event in events if _summary(event) in teaching_summaries
    ]

    assert [_summary(event) for event in teaching_events] == teaching_summaries
    assert len(teaching_events) == 10
    for event, (_, lines) in zip(teaching_events, TEACHING_COPY, strict=True):
        assert _description(event) == "\n\n".join((*lines, MARKER))


def test_granola_connection_swaps_the_ninth_teaching_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.utils.nudge_calendar import build_nudge_calendar

    _configure_working_week(
        tmp_path,
        monkeypatch,
        ["monday", "tuesday", "wednesday", "thursday", "friday"],
    )

    without_granola = build_nudge_calendar(
        date(2026, 7, 26),
        granola_connected=False,
    )
    with_granola_events = _events(
        build_nudge_calendar(
            date(2026, 7, 26),
            granola_connected=True,
        )
    )
    promises_event = next(
        event
        for event in with_granola_events
        if _summary(event) == GRANOLA_DAY_NINE[0]
    )

    assert GRANOLA_DAY_NINE[0] not in without_granola
    assert "Go through my meeting notes from the last month" not in without_granola
    assert _description(promises_event) == "\n\n".join(
        (*GRANOLA_DAY_NINE[1], MARKER)
    )
    assert "Catch Dex up on a meeting" not in {
        _summary(event) for event in with_granola_events
    }


def test_pillars_personalise_only_the_third_teaching_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.utils.nudge_calendar import build_nudge_calendar

    _configure_working_week(
        tmp_path,
        monkeypatch,
        ["monday", "tuesday", "wednesday", "thursday", "friday"],
    )

    personalised = _events(
        build_nudge_calendar(
            date(2026, 7, 26),
            pillars=["Customers", "Product", "Team", "Ignored"],
        )
    )
    plain = _events(build_nudge_calendar(date(2026, 7, 26), pillars=[]))
    personalised_day_three = next(
        event
        for event in personalised
        if _summary(event) == "Let Dex interview you (10 min)"
    )
    plain_day_three = next(
        event
        for event in plain
        if _summary(event) == "Let Dex interview you (10 min)"
    )

    assert _description(personalised_day_three).startswith(
        "You told Dex your big areas are Customers, Product and Team.\n\n"
    )
    assert "Ignored" not in _description(personalised_day_three)
    assert not _description(plain_day_three).startswith(
        "You told Dex your big areas are"
    )


def test_every_description_ends_with_the_reader_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.utils.nudge_calendar import build_nudge_calendar

    _configure_working_week(
        tmp_path,
        monkeypatch,
        ["monday", "tuesday", "wednesday", "thursday", "friday"],
    )

    events = _events(build_nudge_calendar(date(2026, 7, 26)))

    assert events
    assert all(_description(event).splitlines()[-1] == MARKER for event in events)


def test_weekly_and_sign_off_events_use_the_exact_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.utils.nudge_calendar import build_nudge_calendar

    _configure_working_week(
        tmp_path,
        monkeypatch,
        ["monday", "tuesday", "wednesday", "thursday", "friday"],
    )
    events = _events(build_nudge_calendar(date(2026, 7, 26)))
    weekly_events = [
        event for event in events if _summary(event) == WEEKLY_SUMMARY
    ]
    sign_off = next(
        event
        for event in events
        if _summary(event) == "Keep the weekly rhythm? (last nudge)"
    )

    weekly_lines = (
        'Say this: "Review my week."',
        "What got done, what slipped, what carries over. Five minutes at the end of the week is what stops the next one starting cold.",
        "Skill: /week-review",
        "https://heydex.ai/help/daily-rhythm.html",
        MARKER,
    )
    sign_off_lines = (
        'Say this: "Review my week."',
        "That's the end of the getting-started series — no more new prompts from us.",
        "The weekly wrap-up stays in your calendar from here, because it's the one that compounds. If you'd rather it didn't, delete the calendar called Dex and everything stops. One tap, no hard feelings.",
        "Everything from the last few weeks lives at https://heydex.ai/help/prompts-to-steal.html",
        MARKER,
    )

    assert all(
        _description(event) == "\n\n".join(weekly_lines)
        for event in weekly_events
    )
    assert _description(sign_off) == "\n\n".join(sign_off_lines)
    assert [_summary(event) for event in events[-4:]] == [
        WEEKLY_SUMMARY,
        WEEKLY_SUMMARY,
        "Keep the weekly rhythm? (last nudge)",
        WEEKLY_SUMMARY,
    ]


def test_same_inputs_produce_byte_identical_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.utils.nudge_calendar import build_nudge_calendar

    _configure_working_week(
        tmp_path,
        monkeypatch,
        ["sunday", "monday", "tuesday", "wednesday", "thursday"],
    )
    inputs = {
        "start_from": date(2026, 7, 25),
        "pillars": ["Customers", "Product"],
        "granola_connected": True,
    }

    assert build_nudge_calendar(**inputs) == build_nudge_calendar(**inputs)


def test_text_values_escape_punctuation_backslashes_and_newlines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.utils.nudge_calendar import build_nudge_calendar

    _configure_working_week(
        tmp_path,
        monkeypatch,
        ["monday", "tuesday", "wednesday", "thursday", "friday"],
    )
    events = _events(
        build_nudge_calendar(
            date(2026, 7, 26),
            pillars=["Customers, Growth; Core\\Platform\nEmerging"],
        )
    )
    day_three = next(
        event
        for event in events
        if _summary(event) == "Let Dex interview you (10 min)"
    )

    assert "Customers\\, Growth\\; Core\\\\Platform\\nEmerging" in day_three[
        "DESCRIPTION"
    ]
    assert _description(day_three).startswith(
        "You told Dex your big areas are "
        "Customers, Growth; Core\\Platform\nEmerging.\n\n"
    )


def test_dex_nudge_event_detection_is_defensive() -> None:
    from core.utils.nudge_calendar import is_dex_nudge_event

    assert is_dex_nudge_event({"calendar_name": "  dEx  ", "notes": None}) is True
    assert is_dex_nudge_event(
        {
            "calendar_name": "Personal",
            "notes": f"Try this today.\n\n{MARKER}",
        }
    ) is True
    assert is_dex_nudge_event(
        {
            "calendar_name": "Work",
            "notes": "Ordinary meeting notes",
        }
    ) is False
    assert is_dex_nudge_event({}) is False
    assert is_dex_nudge_event({"calendar_name": None, "notes": None}) is False


def test_generate_nudge_calendar_tool_writes_parseable_idempotent_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.mcp import granola_server, onboarding_server

    class FixedDate(date):
        @classmethod
        def today(cls) -> FixedDate:
            return cls(2026, 7, 26)

    system = tmp_path / "System"
    system.mkdir()
    (system / "user-profile.yaml").write_text(
        "pillars:\n"
        "  - name: Profile pillar\n"
        "working_week:\n"
        "  days: [monday, tuesday, wednesday, thursday, friday]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        onboarding_server,
        "SESSION_FILE",
        system / ".onboarding-session.json",
    )
    monkeypatch.setattr(onboarding_server, "date", FixedDate)
    monkeypatch.setattr(granola_server, "get_api_key", lambda: "grn_connected")

    session = onboarding_server.create_new_session()
    session["data"]["pillars"] = ["Customers", "Product"]
    assert onboarding_server.save_session(session) is True

    tool_names = {
        tool.name
        for tool in asyncio.run(onboarding_server.handle_list_tools())
    }
    assert "generate_nudge_calendar" in tool_names

    first_payload = json.loads(
        asyncio.run(
            onboarding_server.handle_call_tool("generate_nudge_calendar", {})
        )[0].text
    )
    calendar_path = Path(first_payload["data"]["path"])
    first_bytes = calendar_path.read_bytes()
    with calendar_path.open("r", encoding="utf-8", newline="") as calendar_file:
        calendar_text = calendar_file.read()
    events = _events(calendar_text)

    assert first_payload["success"] is True
    assert calendar_path == (system / "dex-calendar.ics").resolve()
    assert calendar_path.is_absolute()
    assert events
    assert first_payload["data"]["event_count"] == len(events)
    assert first_payload["data"]["first_event_date"] == datetime.strptime(
        events[0]["DTSTART;VALUE=DATE"],
        "%Y%m%d",
    ).date().isoformat()
    assert "You told Dex your big areas are Customers and Product." in calendar_text
    assert GRANOLA_DAY_NINE[0] in calendar_text

    second_payload = json.loads(
        asyncio.run(
            onboarding_server.handle_call_tool("generate_nudge_calendar", {})
        )[0].text
    )

    assert second_payload == first_payload
    assert calendar_path.read_bytes() == first_bytes


def test_ritual_calendar_analysis_ignores_dex_nudges() -> None:
    from core.ritual_intelligence.calendar_ingest import normalize_events

    events = normalize_events(
        [
            {
                "provider_event_id": "real-meeting",
                "title": "Customer review",
                "start": "2026-07-27T09:00:00+01:00",
                "end": "2026-07-27T10:00:00+01:00",
                "calendar_name": "Work",
                "notes": "Review the launch",
            },
            {
                "provider_event_id": "dex-calendar-nudge",
                "title": "Plan today with Dex",
                "start": "2026-07-27T10:00:00+01:00",
                "end": "2026-07-27T10:15:00+01:00",
                "calendar_name": "Dex",
            },
            {
                "provider_event_id": "imported-dex-nudge",
                "title": "Review my week",
                "start": "2026-07-27T11:00:00+01:00",
                "end": "2026-07-27T11:15:00+01:00",
                "calendar_name": "Work",
                "notes": MARKER,
            },
        ]
    )

    assert [event.title for event in events] == ["Customer review"]
