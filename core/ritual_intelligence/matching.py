"""Provider-neutral transcript/occurrence matching helpers."""

from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher

from .models import TranscriptArtifact


def _title_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left.lower(), right.lower()).ratio()


def _time_similarity(transcript: TranscriptArtifact, occurrence: dict) -> float:
    if transcript.source_event_id and occurrence.get("source_event_id") == transcript.source_event_id:
        return 1.0
    if transcript.started_at is None:
        return 0.0
    occurrence_start = datetime.fromisoformat(occurrence["starts_at"])
    delta_minutes = abs((occurrence_start - transcript.started_at).total_seconds()) / 60
    if delta_minutes <= 15:
        return 1.0
    if delta_minutes <= 60:
        return 0.75
    if delta_minutes <= 180:
        return 0.5
    return 0.0


def _attendee_overlap(transcript: TranscriptArtifact, occurrence_contacts: list[dict]) -> float:
    transcript_emails = {attendee.email for attendee in transcript.attendees if attendee.email}
    occurrence_emails = {row["attendee_email"] for row in occurrence_contacts if row["attendee_email"]}
    if not transcript_emails or not occurrence_emails:
        return 0.0
    overlap = transcript_emails & occurrence_emails
    return len(overlap) / max(len(transcript_emails), len(occurrence_emails))


def occurrence_match_confidence(
    transcript: TranscriptArtifact,
    occurrence: dict,
    occurrence_contacts: list[dict],
) -> float:
    if transcript.source_event_id and occurrence.get("source_event_id") == transcript.source_event_id:
        return 1.0
    time_score = _time_similarity(transcript, occurrence)
    attendee_score = _attendee_overlap(transcript, occurrence_contacts)
    title_score = _title_similarity(transcript.title, occurrence["title"])
    weighted = (time_score * 0.5) + (attendee_score * 0.3) + (title_score * 0.2)
    return round(weighted, 2)
