"""Deterministic, privacy-bounded capture-to-calendar identity matching."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

MAX_START_DELTA_SECONDS = 5 * 60
UNTITLED_TITLES = {"", "untitled", "untitled meeting"}


def _aware_instant(value: object) -> datetime | None:
    """Parse an ISO timestamp only when it declares a timezone."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _normalized_title(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).casefold()


def _is_untitled(value: object) -> bool:
    return _normalized_title(value) in UNTITLED_TITLES


def _event_start(event: dict[str, Any]) -> object:
    for key in ("start", "start_time", "starts_at", "scheduled_start_time"):
        if event.get(key):
            return event[key]
    return None


def _event_title(event: dict[str, Any]) -> str:
    value = event.get("title", event.get("event_title", ""))
    return value.strip() if isinstance(value, str) else ""


def _raw_attendees(record: dict[str, Any]) -> list[Any]:
    for key in ("attendees", "participants", "invitees"):
        value = record.get(key)
        if isinstance(value, list):
            return value
    return []


def _participant_tokens(record: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for attendee in _raw_attendees(record):
        if isinstance(attendee, str):
            name = " ".join(attendee.split()).casefold()
            if name:
                tokens.add(f"name:{name}")
            continue
        if not isinstance(attendee, dict):
            continue
        email = attendee.get("email")
        name = attendee.get("name")
        if isinstance(email, str) and email.strip():
            tokens.add(f"email:{email.strip().casefold()}")
        if isinstance(name, str) and name.strip():
            tokens.add(f"name:{' '.join(name.split()).casefold()}")
    return tokens


def _capture_participant_labels(capture: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for attendee in _raw_attendees(capture):
        if isinstance(attendee, str):
            label = _normalized_title(attendee)
            if label:
                labels.add(label)
            continue
        if not isinstance(attendee, dict):
            continue
        for key in ("name", "email"):
            label = _normalized_title(attendee.get(key))
            if label:
                labels.add(label)
    return labels


def _safe_attendee_identity(event: dict[str, Any]) -> list[dict[str, str | None]]:
    identities: list[dict[str, str | None]] = []
    for attendee in _raw_attendees(event):
        if isinstance(attendee, str):
            name = " ".join(attendee.split())
            if name:
                identities.append({"name": name, "email": None})
            continue
        if not isinstance(attendee, dict):
            continue
        name_value = attendee.get("name")
        email_value = attendee.get("email")
        name = " ".join(name_value.split()) if isinstance(name_value, str) and name_value.strip() else None
        email = email_value.strip().casefold() if isinstance(email_value, str) and email_value.strip() else None
        if name or email:
            identities.append({"name": name, "email": email})
    return identities


def _utc_iso(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def match_capture_to_calendar(
    capture: dict[str, Any],
    calendar_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Match by instant, then use title and participant overlap only for ties.

    Naive timestamps are rejected rather than assigned a guessed timezone. The
    returned calendar data is an allowlist of meeting identity only.
    """
    capture_start = _aware_instant(capture.get("start_time"))
    if capture_start is None:
        return {"status": "unmatched", "reason": "capture_timestamp_missing_timezone"}

    candidates: list[dict[str, Any]] = []
    valid_calendar_timestamps = 0
    capture_tokens = _participant_tokens(capture)
    capture_title = capture.get("title", "")
    normalized_capture_title = _normalized_title(capture_title)

    for event in calendar_events:
        if not isinstance(event, dict):
            continue
        event_start = _aware_instant(_event_start(event))
        if event_start is None:
            continue
        valid_calendar_timestamps += 1
        delta_seconds = abs((event_start - capture_start).total_seconds())
        if delta_seconds > MAX_START_DELTA_SECONDS:
            continue
        title_corroborated = (
            not _is_untitled(capture_title)
            and normalized_capture_title == _normalized_title(_event_title(event))
        )
        candidates.append(
            {
                "event": event,
                "start": event_start,
                "delta_seconds": delta_seconds,
                "title_corroborated": title_corroborated,
                "participant_overlap": len(capture_tokens & _participant_tokens(event)),
            }
        )

    if not candidates:
        reason = "outside_five_minute_window" if valid_calendar_timestamps else "no_valid_calendar_timestamp"
        return {"status": "unmatched", "reason": reason}

    nearest_delta = min(candidate["delta_seconds"] for candidate in candidates)
    tied = [candidate for candidate in candidates if candidate["delta_seconds"] == nearest_delta]
    if len(tied) > 1:
        best_title = max(candidate["title_corroborated"] for candidate in tied)
        tied = [candidate for candidate in tied if candidate["title_corroborated"] == best_title]
    if len(tied) > 1:
        best_overlap = max(candidate["participant_overlap"] for candidate in tied)
        tied = [candidate for candidate in tied if candidate["participant_overlap"] == best_overlap]
    if len(tied) != 1:
        return {
            "status": "ambiguous",
            "reason": "tie_unresolved_after_title_and_participants",
            "candidate_count": len(tied),
        }

    winner = tied[0]
    event = winner["event"]
    event_title = _event_title(event)
    poor_capture_title = _is_untitled(capture_title) or normalized_capture_title in _capture_participant_labels(capture)
    safe_capture_title = capture_title.strip() if isinstance(capture_title, str) else ""
    identity_title = event_title if poor_capture_title and event_title else safe_capture_title
    return {
        "status": "matched",
        "delta_seconds": int(winner["delta_seconds"]),
        "title_corroborated": winner["title_corroborated"],
        "participant_overlap": winner["participant_overlap"],
        "identity": {
            "title": identity_title,
            "start_time": _utc_iso(winner["start"]),
            "attendees": _safe_attendee_identity(event),
        },
    }
