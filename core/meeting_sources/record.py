"""The internal meeting record every source is mapped onto.

The point of this contract is that nothing downstream should ever ask which
tool a meeting came from. A provider adapter's whole job is to produce one of
these; `/process-meetings`, person pages and task extraction consume it.

Two decisions here matter more than the field list:

**Absence is representable.** ``title`` and ``attendees`` are routinely empty
from real providers: a recorder that titles and attributes from a calendar it
cannot read returns neither. A record that forced them would push adapters into
inventing values, and an invented attendee becomes an invented commitment two
steps later. Empty means unknown, and callers must treat it that way.

**Provenance is mandatory.** ``source`` and ``source_id`` are what dedup and
person-page touch tracking run on. A record without them would be reprocessed
as new on every sweep.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Attendee:
    """Someone present. ``email`` is what person-page routing keys on."""

    name: str | None = None
    email: str | None = None

    def __post_init__(self) -> None:
        if not self.name and not self.email:
            raise ValueError("An attendee needs at least a name or an email")


@dataclass(frozen=True)
class MeetingRecord:
    """One meeting, in the shape Dex works with regardless of origin."""

    source: str
    source_id: str
    start: datetime
    end: datetime | None = None
    title: str | None = None
    body: str = ""
    attendees: tuple[Attendee, ...] = ()
    action_items: tuple[str, ...] = ()
    has_transcript: bool = False
    finalized: bool = True
    modified_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source or not self.source_id:
            raise ValueError("A meeting record must carry source and source_id")
        if self.start.tzinfo is None:
            raise ValueError("start must be timezone-aware")

    @property
    def attribution_is_reliable(self) -> bool:
        """Whether anything in the body may be attributed to a named person.

        False when the provider gave us no attendees. A summary from such a
        source names speakers it cannot actually identify, so ownership,
        commitments and quotes taken from it would be fabrications with a
        plausible shape. Callers should resolve attendance from the calendar
        instead, or record the meeting unattributed.
        """
        return bool(self.attendees)

    @property
    def local_date(self) -> str:
        return self.start.astimezone().strftime("%Y-%m-%d")


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a provider timestamp into an aware datetime, or None.

    Providers are inconsistent about trailing Z, fractional seconds and naive
    values. A naive timestamp is treated as UTC rather than local, because
    every source seen so far reports UTC and guessing local would silently
    shift meetings across day boundaries.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
