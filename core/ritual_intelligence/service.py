"""Core local runtime for Ritual Intelligence."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .calendar_ingest import get_internal_domains, load_calendar_events
from .db import bootstrap_database, connect, transaction
from .meeting_reconcile import reconcile_events


class RitualIntelligenceService:
    """Local-first service surface for Ritual Intelligence."""

    def __init__(self) -> None:
        self._internal_domains = get_internal_domains()

    def refresh_calendar(
        self,
        *,
        start_offset_days: int = -28,
        end_offset_days: int = 14,
        calendar_name: str | None = None,
        events=None,
    ) -> dict:
        now = datetime.now(timezone.utc)
        window_start = now + timedelta(days=start_offset_days)
        window_end = now + timedelta(days=end_offset_days)
        normalized_events = events
        if normalized_events is None:
            normalized_events = load_calendar_events(
                start_offset_days=start_offset_days,
                end_offset_days=end_offset_days,
                calendar_name=calendar_name,
            )
        with transaction(create=True) as conn:
            result = reconcile_events(
                conn,
                normalized_events,
                internal_domains=self._internal_domains,
                window_start=window_start,
                window_end=window_end,
            )
        try:
            from .actions import _generate_for_occurrence
            from .ritual_match import _upcoming_confirmed_occurrence_ids, refresh_ritual_suggestions

            refresh_ritual_suggestions()
            with transaction(create=True) as conn:
                generated = [
                    _generate_for_occurrence(conn, occurrence_id)
                    for occurrence_id in _upcoming_confirmed_occurrence_ids(conn, now=now.astimezone())
                ]
            result["generated"] = generated
        except ImportError:
            result["generated"] = []
        return result

    def list_occurrences(self, *, limit: int = 50) -> list[dict]:
        conn = bootstrap_database(connect(create=True))
        try:
            rows = conn.execute(
                """
                SELECT id, title, starts_at, ends_at, state, capture_mode, provider,
                       source_series_id, series_key, note_path, daily_log_path
                FROM occurrences
                ORDER BY starts_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def list_ritual_suggestions(self) -> list[dict]:
        try:
            from .ritual_match import list_ritual_suggestions
        except ImportError:
            return []
        return list_ritual_suggestions()

    def confirm_ritual(self, series_id: str) -> dict:
        from .actions import confirm_ritual

        return confirm_ritual(series_id)

    def reject_ritual(self, series_id: str) -> dict:
        from .actions import reject_ritual

        return reject_ritual(series_id)

    def disable_series_tracking(self, series_id: str) -> dict:
        from .actions import disable_series_tracking

        return disable_series_tracking(series_id)

    def generate_one_off_prep(self, occurrence_id: str) -> dict:
        from .actions import generate_one_off_prep

        return generate_one_off_prep(occurrence_id)

    def set_occurrence_activity_log(self, occurrence_id: str) -> dict:
        from .actions import set_occurrence_activity_log

        return set_occurrence_activity_log(occurrence_id)

    def list_unmatched_transcripts(self) -> list[dict]:
        from .actions import list_unmatched_transcripts

        return list_unmatched_transcripts()

    def ingest_granola_local(self, *, days_back: int = 30) -> list[dict]:
        from .transcript_ingest import ingest_granola_local

        return ingest_granola_local(days_back=days_back)

    def import_manual_transcript(
        self,
        *,
        file_path,
        title: str,
        started_at=None,
        ended_at=None,
        source_event_id: str | None = None,
    ) -> dict:
        from .transcript_ingest import import_manual_transcript

        return import_manual_transcript(
            file_path=file_path,
            title=title,
            started_at=started_at,
            ended_at=ended_at,
            source_event_id=source_event_id,
        )

    def reconcile_unmatched_transcripts(self) -> list[dict]:
        from .transcript_reconcile import reconcile_unmatched_transcripts

        return reconcile_unmatched_transcripts()

    def mark_transcript_not_same_meeting(self, transcript_id: str, occurrence_id: str) -> dict:
        from .actions import mark_transcript_not_same_meeting

        return mark_transcript_not_same_meeting(transcript_id, occurrence_id)

    def reassign_transcript_to_occurrence(self, transcript_id: str, occurrence_id: str) -> dict:
        from .actions import reassign_transcript_to_occurrence

        return reassign_transcript_to_occurrence(transcript_id, occurrence_id)

    def create_contact_page(self, contact_id: str) -> dict:
        from .actions import create_contact_page

        return create_contact_page(contact_id)

    def dismiss_contact_suggestion(self, contact_id: str, occurrence_id: str) -> dict:
        from .actions import dismiss_contact_suggestion

        return dismiss_contact_suggestion(contact_id, occurrence_id)

    def suppress_contact_suggestion(self, contact_id: str) -> dict:
        from .actions import suppress_contact_suggestion

        return suppress_contact_suggestion(contact_id)


def ensure_runtime_ready() -> sqlite3.Connection:
    """Bootstrap the runtime DB and return a live connection."""
    return bootstrap_database(connect(create=True))
