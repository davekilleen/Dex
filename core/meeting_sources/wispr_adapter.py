"""Map Wispr Flow's payloads onto the internal meeting record.

Everything provider-specific about Wispr lives here, so nothing downstream has
to know this source exists. Three of its traits are load-bearing:

- **Titles come back empty.** Wispr titles a capture from the calendar event,
  and its calendar sync is Google-only. A Microsoft 365 user therefore gets no
  title at all. We derive one from the body rather than leave a note called
  nothing, and we mark it as derived so it is never mistaken for what the
  meeting was actually called.
- **Attendees come back empty for the same reason.** That makes every summary
  from this source unreliable for attribution: it names speakers it cannot
  identify. The record carries the emptiness honestly and downstream resolves
  attendance from Dex's own calendar.
- **``todos`` is present but empty in practice.** Action items are prose inside
  the summary, under a "Next Steps" heading, so they are extracted from there
  and only from there.
"""
from __future__ import annotations

import re
from typing import Any

from core.meeting_sources.record import Attendee, MeetingRecord, parse_timestamp  # noqa: F401

SOURCE = "wispr"

# Wispr writes its action items under a heading like "### Next Steps".
_NEXT_STEPS = re.compile(r"^#{1,6}\s*next steps\s*$", re.IGNORECASE)
_HEADING = re.compile(r"^#{1,6}\s+")
_BULLET = re.compile(r"^\s*[-*]\s+(?P<text>.+?)\s*$")
# "- (Ken) Add Pipedrive deal id..." — the parenthesised owner is a speaker
# label, which for this source may be "Speaker 1" and is not a resolved person.
_LEADING_OWNER = re.compile(r"^\((?P<owner>[^)]{1,40})\)\s*(?P<rest>.+)$")


def _attendees(raw: Any) -> tuple[Attendee, ...]:
    if not isinstance(raw, list):
        return ()
    people: list[Attendee] = []
    for entry in raw:
        if isinstance(entry, str) and entry.strip():
            people.append(Attendee(name=entry.strip()))
        elif isinstance(entry, dict):
            name = (entry.get("name") or entry.get("display_name") or "").strip() or None
            email = (entry.get("email") or "").strip() or None
            if name or email:
                people.append(Attendee(name=name, email=email))
    return tuple(people)


def extract_action_items(body: str) -> tuple[str, ...]:
    """Pull the bullets under a Next Steps heading, and nothing else.

    Deliberately narrow. Reading action items out of the whole summary would
    sweep up decisions and observations as though they were commitments, which
    is how a meeting note turns into tasks nobody agreed to.
    """
    if not body:
        return ()
    lines = body.splitlines()
    items: list[str] = []
    collecting = False
    for line in lines:
        if _NEXT_STEPS.match(line.strip()):
            collecting = True
            continue
        if collecting and _HEADING.match(line.strip()):
            break
        if not collecting:
            continue
        match = _BULLET.match(line)
        if match:
            items.append(match.group("text"))
    return tuple(items)


def derive_title(body: str, *, fallback: str) -> str:
    """A usable title when the provider supplies none.

    The first sentence of a Wispr summary is a one-line description of the
    meeting, which is exactly what a title wants to be. Trimmed to something
    filename-shaped.
    """
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or _HEADING.match(stripped):
            continue
        sentence = re.split(r"(?<=[.!?])\s", stripped)[0].strip(" .")
        if not sentence:
            continue
        if len(sentence) <= 80:
            return sentence
        # Trim on a word boundary: a title cut mid-word reads as corruption.
        return sentence[:80].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return fallback


def to_record(payload: dict[str, Any]) -> MeetingRecord:
    """Map one Wispr meeting (list item or detail) onto the internal record."""
    if not isinstance(payload, dict) or not payload.get("id"):
        raise ValueError("A Wispr meeting payload needs an id")

    start = parse_timestamp(payload.get("start"))
    if start is None:
        raise ValueError(f"Wispr meeting {payload['id']} has no usable start time")

    # Detail calls put the notes in `summary`; list items carry a truncated
    # `content_excerpt`. `content` has been empty on every capture seen.
    body = (payload.get("summary") or payload.get("content") or payload.get("content_excerpt") or "").strip()

    provider_title = (payload.get("title") or "").strip()
    title = provider_title or derive_title(body, fallback=f"Meeting {start.astimezone():%H:%M}")

    return MeetingRecord(
        source=SOURCE,
        source_id=str(payload["id"]),
        start=start,
        end=parse_timestamp(payload.get("end")),
        title=title,
        body=body,
        attendees=_attendees(payload.get("attendees")),
        action_items=extract_action_items(body),
        has_transcript=bool(payload.get("has_transcript")),
        finalized=bool(payload.get("finalized", True)),
        modified_at=parse_timestamp(payload.get("modified_at")),
        extra={"title_was_derived": not provider_title},
    )
