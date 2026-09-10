"""Map Granola's API payloads onto the internal meeting record.

Granola is the provider the record has to fit without bending, because it is
the one already in use and its behaviour must not change. It is also usefully
unlike Wispr, which is what makes the pair a real test of the contract rather
than a shape drawn around a single source:

- Granola supplies a title; Wispr supplies none.
- Granola supplies attendees with emails, so attribution is resolved and
  person-page routing works; Wispr supplies none.
- Granola's action items are markdown checkboxes the user has already curated;
  Wispr's are prose bullets under a heading.
- Granola's transcript is a list of speaker turns; Wispr's is fetched separately.

None of that reaches anything downstream. Both produce a MeetingRecord.
"""
from __future__ import annotations

from typing import Any

from core.meeting_sources.record import Attendee, MeetingRecord, parse_timestamp

SOURCE = "granola"

_CHECKBOX_PREFIXES = ("- [ ]", "* [ ]")


def _attendees(raw: Any) -> tuple[Attendee, ...]:
    if not isinstance(raw, list):
        return ()
    people: list[Attendee] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").strip() or None
        email = (entry.get("email") or "").strip() or None
        if name or email:
            people.append(Attendee(name=name, email=email))
    return tuple(people)


def extract_action_items(notes: str) -> tuple[str, ...]:
    """Unchecked checkbox lines, which is how Granola records action items.

    Only unchecked ones: a ticked box is something already done, and importing
    it as an open task would hand the user back work they have finished.
    """
    items: list[str] = []
    for line in (notes or "").splitlines():
        stripped = line.strip()
        for prefix in _CHECKBOX_PREFIXES:
            if stripped.startswith(prefix):
                text = stripped[len(prefix):].strip()
                if text:
                    items.append(text)
                break
    return tuple(items)


def _transcript_present(detail: dict[str, Any]) -> bool:
    transcript = detail.get("transcript")
    if isinstance(transcript, list):
        return any(
            isinstance(turn, dict) and (turn.get("text") or "").strip() for turn in transcript
        )
    return bool(transcript)


def to_record(detail: dict[str, Any]) -> MeetingRecord:
    """Map one Granola note detail onto the internal record."""
    if not isinstance(detail, dict) or not detail.get("id"):
        raise ValueError("A Granola note detail needs an id")

    start = parse_timestamp(detail.get("created_at"))
    if start is None:
        raise ValueError(f"Granola note {detail['id']} has no usable created_at")

    notes = detail.get("summary_markdown") or detail.get("summary_text") or ""
    title = (detail.get("title") or "").strip()

    extra: dict[str, Any] = {"title_was_derived": not title}
    if detail.get("web_url"):
        extra["web_url"] = detail["web_url"]

    return MeetingRecord(
        source=SOURCE,
        source_id=str(detail["id"]),
        start=start,
        end=parse_timestamp(detail.get("ended_at") or detail.get("end")),
        title=title or "Untitled Meeting",
        body=notes.strip(),
        attendees=_attendees(detail.get("attendees")),
        action_items=extract_action_items(notes),
        has_transcript=_transcript_present(detail),
        finalized=True,
        modified_at=parse_timestamp(detail.get("updated_at")),
        extra=extra,
    )
