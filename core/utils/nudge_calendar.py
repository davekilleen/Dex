"""Build Dex's opt-in first-month nudge calendar."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta

from core.utils.working_week import (
    get_working_days,
    last_working_day_of_week,
    next_working_day,
)

_MARKER = "Added by Dex · delete the Dex calendar to stop these"
_ICAL_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def is_dex_nudge_event(event: dict) -> bool:
    """Return whether a raw calendar event is one of Dex's own nudges."""
    calendar_name = event.get("calendar_name")
    if (
        isinstance(calendar_name, str)
        and calendar_name.strip().casefold() == "dex"
    ):
        return True

    notes = event.get("notes")
    return isinstance(notes, str) and _MARKER in notes


@dataclass(frozen=True)
class _EventCopy:
    summary: str
    description_lines: tuple[str, ...]


@dataclass(frozen=True)
class _ScheduledEvent:
    day: date
    copy: _EventCopy
    recurring: bool = False


_TEACHING_COPY = (
    _EventCopy(
        "Plan today with Dex (2 min)",
        (
            'Say this: "Plan my day."',
            "Dex reads your calendar and your tasks and hands back a plan for the day: what's fixed, what's yours to move, and the one thing worth protecting.",
            "Skill: /daily-plan",
            "https://heydex.ai/help/daily-rhythm.html",
        ),
    ),
    _EventCopy(
        "What your calendar says you value",
        (
            'Paste this: "Look at my last eight weeks of meetings. Ignore what the events are called — work out what my calendar says I actually value: who gets my time, what share is reactive versus chosen. Then compare against my pillars. Where does my time contradict my stated priorities?"',
            "Works from day one, because Dex already has your real calendar.",
            "Skill: /xray — ask Dex how it worked that out",
            "https://heydex.ai/help/prompts-to-steal.html",
        ),
    ),
    _EventCopy(
        "Let Dex interview you (10 min)",
        (
            'Paste this: "Interview me so you can work brilliantly with me. Ask one question at a time — never a list. Cover what I actually do day to day, the goals I\'m measured on, who my stakeholders are, how I like to work, and what keeps going wrong. Then update my profile with what you learned and show me what changed."',
            "You're bad at guessing what an AI needs to know about you. It's very good at pulling it out of you. Everything after today gets better.",
            "Answer out loud with dictation if you can. You'll say twice as much, and the messy honesty is the good part.",
            "Skill: /identity-snapshot",
            "https://heydex.ai/help/make-it-your-own.html",
        ),
    ),
    _EventCopy(
        "Think out loud, get finished work back",
        (
            'Paste this: "I\'m going to dump thoughts at you in no particular order. Don\'t respond beyond \'noted\'. When I say HARVEST, turn everything into a board update, in my voice, ready to use. File anything that sounds like a task where it belongs."',
            "Best on a walk after a big meeting. Dump the debrief, say HARVEST, done — and the leftovers get filed instead of lost.",
            "Skill: /triage",
            "https://heydex.ai/help/prompts-to-steal.html#magic-words-voice-in-finished-work-out",
        ),
    ),
    _EventCopy(
        "Make Dex argue against you",
        (
            'Paste this: "Here\'s what I\'m about to do: [decision]. You have my goals and my history. Make the strongest honest case AGAINST it — not strawmen, the version my smartest critic would make. Then tell me what evidence would change your mind, and what you\'d do instead."',
            "Most people use AI to agree with them. This is the opposite, and it's where the value is.",
            "Skill: /decision-log",
            "https://heydex.ai/help/prompts-to-steal.html#set-traps-for-your-blind-spots",
        ),
    ),
    _EventCopy(
        "Ask what you could build but haven't",
        (
            'Paste this: "List every tool and connection you have access to in this vault. Then, knowing my role and goals: what are the five most valuable workflows we could build that I\'m not using? For each, what it does, what it needs, and the effort. Rank by payoff."',
            'Don\'t start from your problems, start from what your system can already reach. When one lands, say "turn that into a skill" and it becomes a command you keep forever.',
            "Skill: /create-skill",
            "https://heydex.ai/help/make-it-your-own.html",
        ),
    ),
    _EventCopy(
        "Get an idea properly grilled",
        (
            'Paste this: "I have a rough idea: [one sentence]. Don\'t develop it yet. Act as a sharp product manager and grill me with questions, one at a time, until it\'s properly thought through. When I say done, switch roles: become a skeptical CFO and grill me on cost and payoff. Then write the one-pager."',
            "Swap the personas for whoever actually scares you — your board, your best customer, your most pedantic engineer.",
            "Skill: /product-brief",
            "https://heydex.ai/help/prompts-to-steal.html",
        ),
    ),
    _EventCopy(
        "Write the post-mortem before it happens",
        (
            'Paste this: "It\'s three months from now and [project] has failed. Using what you know about this project, my team and how I work, write the honest post-mortem. What killed it? What early warning did I ignore? Then: the cheapest thing I could do this week to make that story not come true."',
            "Skill: /project-health",
            "https://heydex.ai/help/people-projects.html",
        ),
    ),
    _EventCopy(
        "Find out what you've promised people",
        (
            'Paste this: "Go through my meeting notes from the last month. Find every commitment I made — including soft ones like \'I\'ll take a look\' — and check each against what\'s actually been done. Show me the open promises, oldest first, with who I made them to."',
            "It lands here on purpose: by now you have a fortnight of real meetings for it to work on. Brutal before a 1:1.",
            "Skill: /commitments",
            "https://heydex.ai/help/meetings.html",
        ),
    ),
    _EventCopy(
        "Ask Dex what you're still not using",
        (
            'Say this: "Look at everything we\'ve done together so far. How am I doing, and what else could I be using you for?"',
            "Two weeks of real work in. This is the moment to find out what Dex has noticed, and what it can do that you haven't touched.",
            "Skill: /dex-level-up",
            "https://heydex.ai/help/",
        ),
    ),
)

_MANUAL_MEETING_COPY = _EventCopy(
    "Catch Dex up on a meeting",
    (
        'Say this: "I just had a meeting with [who] about [what] — here\'s what happened."',
        "Dex pulls out the decisions, the promises and who owes what, and files them against the right people and projects. Connect a meeting tool later and it does this without you typing.",
        "Skill: /process-meetings",
        "https://heydex.ai/help/meetings.html",
    ),
)

_WEEKLY_COPY = _EventCopy(
    "Weekly wrap-up with Dex (5 min)",
    (
        'Say this: "Review my week."',
        "What got done, what slipped, what carries over. Five minutes at the end of the week is what stops the next one starting cold.",
        "Skill: /week-review",
        "https://heydex.ai/help/daily-rhythm.html",
    ),
)

_SIGN_OFF_COPY = _EventCopy(
    "Keep the weekly rhythm? (last nudge)",
    (
        'Say this: "Review my week."',
        "That's the end of the getting-started series — no more new prompts from us.",
        "The weekly wrap-up stays in your calendar from here, because it's the one that compounds. If you'd rather it didn't, delete the calendar called Dex and everything stops. One tap, no hard feelings.",
        "Everything from the last few weeks lives at https://heydex.ai/help/prompts-to-steal.html",
    ),
)


def _is_last_working_day(day: date) -> bool:
    return day == last_working_day_of_week(day)


def _next_last_working_day(day: date) -> date:
    while not _is_last_working_day(day):
        day = next_working_day(day)
    return day


def _personalised_teaching_copy(
    pillars: list[str],
    granola_connected: bool,
) -> tuple[_EventCopy, ...]:
    teaching_copy = list(_TEACHING_COPY)
    if not granola_connected:
        teaching_copy[8] = _MANUAL_MEETING_COPY

    selected_pillars = pillars[:3]
    if selected_pillars:
        if len(selected_pillars) == 1:
            pillar_names = selected_pillars[0]
        elif len(selected_pillars) == 2:
            pillar_names = f"{selected_pillars[0]} and {selected_pillars[1]}"
        else:
            pillar_names = (
                f"{selected_pillars[0]}, {selected_pillars[1]} "
                f"and {selected_pillars[2]}"
            )
        day_three = teaching_copy[2]
        teaching_copy[2] = _EventCopy(
            day_three.summary,
            (
                f"You told Dex your big areas are {pillar_names}.",
                *day_three.description_lines,
            ),
        )

    return tuple(teaching_copy)


def _schedule_events(
    start_from: date,
    teaching_copy: tuple[_EventCopy, ...],
) -> list[_ScheduledEvent]:
    events: list[_ScheduledEvent] = []
    day = next_working_day(start_from)
    teaching_index = 0

    while teaching_index < len(teaching_copy):
        if _is_last_working_day(day):
            events.append(_ScheduledEvent(day, _WEEKLY_COPY))
        else:
            events.append(_ScheduledEvent(day, teaching_copy[teaching_index]))
            teaching_index += 1
        day = next_working_day(day)

    for _ in range(2):
        day = _next_last_working_day(day)
        events.append(_ScheduledEvent(day, _WEEKLY_COPY))
        day = next_working_day(day)

    day = _next_last_working_day(day)
    events.append(_ScheduledEvent(day, _SIGN_OFF_COPY))

    recurring_day = _next_last_working_day(next_working_day(day))
    events.append(_ScheduledEvent(recurring_day, _WEEKLY_COPY, recurring=True))
    return events


def _escape_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _fold_line(line: str) -> str:
    folded: list[str] = []
    segment = ""
    limit = 75

    for character in line:
        if len((segment + character).encode("utf-8")) > limit:
            folded.append(segment)
            segment = character
            limit = 74
        else:
            segment += character

    folded.append(segment)
    return "\r\n ".join(folded)


def _run_id(
    start_from: date,
    pillars: list[str],
    granola_connected: bool,
) -> str:
    inputs = json.dumps(
        {
            "start_from": start_from.isoformat(),
            "pillars": pillars,
            "granola_connected": granola_connected,
            "working_days": sorted(get_working_days()),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(inputs.encode("utf-8")).hexdigest()[:20]


def _render_event(
    event: _ScheduledEvent,
    *,
    event_index: int,
    run_id: str,
    dtstamp: str,
) -> list[str]:
    description = "\n\n".join((*event.copy.description_lines, _MARKER))
    lines = [
        "BEGIN:VEVENT",
        f"UID:dex-nudge-{run_id}-{event_index:02d}@heydex.ai",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;VALUE=DATE:{event.day:%Y%m%d}",
        f"DTEND;VALUE=DATE:{event.day + timedelta(days=1):%Y%m%d}",
        f"SUMMARY:{_escape_text(event.copy.summary)}",
        f"DESCRIPTION:{_escape_text(description)}",
        "TRANSP:TRANSPARENT",
        "CLASS:PRIVATE",
    ]
    if event.recurring:
        lines.append(
            f"RRULE:FREQ=WEEKLY;BYDAY={_ICAL_WEEKDAYS[event.day.weekday()]}"
        )
    lines.append("END:VEVENT")
    return lines


def build_nudge_calendar(
    start_from: date,
    pillars: list[str] | None = None,
    granola_connected: bool = False,
) -> str:
    """Return a deterministic first-month Dex calendar in iCalendar format."""
    selected_pillars = list(pillars or [])
    teaching_copy = _personalised_teaching_copy(
        selected_pillars,
        granola_connected,
    )
    events = _schedule_events(start_from, teaching_copy)
    run_id = _run_id(start_from, selected_pillars, granola_connected)
    dtstamp = f"{start_from:%Y%m%d}T000000Z"

    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//Dex//First-Month Nudge Calendar//EN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Dex",
    ]
    for event_index, event in enumerate(events, start=1):
        lines.extend(
            _render_event(
                event,
                event_index=event_index,
                run_id=run_id,
                dtstamp=dtstamp,
            )
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold_line(line) for line in lines) + "\r\n"
