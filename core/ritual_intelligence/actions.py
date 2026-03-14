"""Phase-aware local action surface for Ritual Intelligence."""

from __future__ import annotations

from datetime import datetime

from .brief_generate import generate_brief_markdown
from .contact_promote import create_contact_page as create_contact_page_record
from .contact_suggest import refresh_contact_suggestions_for_occurrence
from .corrections import record_correction
from .db import transaction, utc_now
from .manual_note_match import ensure_manual_note_link
from .projection_write import write_daily_log, write_tracked_meeting_note
from .ritual_match import _upcoming_confirmed_occurrence_ids, refresh_ritual_suggestions


def _series_row(conn, series_id: str):
    row = conn.execute("SELECT * FROM ritual_series WHERE id = ?", (series_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown ritual series: {series_id}")
    return row


def _occurrence_row(conn, occurrence_id: str):
    row = conn.execute("SELECT * FROM occurrences WHERE id = ?", (occurrence_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown occurrence: {occurrence_id}")
    return row


def _generate_for_occurrence(conn, occurrence_id: str, *, force_refresh: bool = False) -> dict:
    manual_link = ensure_manual_note_link(conn, occurrence_id)
    refresh_contact_suggestions_for_occurrence(conn, occurrence_id)
    prep_markdown = generate_brief_markdown(conn, occurrence_id)
    if manual_link and manual_link["source_kind"] == "legacy_read_only":
        note_result = {"status": "linked_existing_note", "note_path": manual_link["note_path"]}
    else:
        note_result = write_tracked_meeting_note(conn, occurrence_id, prep_markdown, force_refresh=force_refresh)
    meeting_date = conn.execute(
        "SELECT substr(starts_at, 1, 10) AS meeting_date FROM occurrences WHERE id = ?",
        (occurrence_id,),
    ).fetchone()["meeting_date"]
    daily_log_result = write_daily_log(conn, meeting_date)
    return {
        "occurrence_id": occurrence_id,
        "prep_status": note_result["status"],
        "note_path": note_result.get("note_path"),
        "daily_log_path": daily_log_result.get("daily_log_path"),
    }


def confirm_ritual(series_id: str, *, now: datetime | None = None) -> dict:
    refresh_ritual_suggestions()
    with transaction(create=True) as conn:
        series = _series_row(conn, series_id)
        conn.execute(
            "UPDATE ritual_series SET status = 'confirmed', confirmed_at = ?, updated_at = ? WHERE id = ?",
            (utc_now(), utc_now(), series_id),
        )
        conn.execute(
            "UPDATE occurrences SET ritual_series_id = ?, capture_mode = 'tracked meeting', updated_at = ? WHERE series_key = ?",
            (series_id, utc_now(), series["series_key"]),
        )
        generated = [
            _generate_for_occurrence(conn, occurrence_id)
            for occurrence_id in _upcoming_confirmed_occurrence_ids(conn, now=now)
        ]
        return {"status": "confirmed", "series_id": series_id, "generated": generated}


def reject_ritual(series_id: str) -> dict:
    refresh_ritual_suggestions()
    with transaction(create=True) as conn:
        _series_row(conn, series_id)
        conn.execute(
            "UPDATE ritual_series SET status = 'rejected', updated_at = ? WHERE id = ?",
            (utc_now(), series_id),
        )
        return {"status": "rejected", "series_id": series_id}


def disable_series_tracking(series_id: str) -> dict:
    refresh_ritual_suggestions()
    with transaction(create=True) as conn:
        _series_row(conn, series_id)
        conn.execute(
            "UPDATE ritual_series SET status = 'disabled', updated_at = ? WHERE id = ?",
            (utc_now(), series_id),
        )
        conn.execute(
            "UPDATE occurrences SET ritual_series_id = NULL, updated_at = ? WHERE ritual_series_id = ?",
            (utc_now(), series_id),
        )
        record_correction(conn, action_type="dont_track_series", target_type="ritual_series", target_id=series_id)
        return {"status": "disabled", "series_id": series_id}


def generate_one_off_prep(occurrence_id: str) -> dict:
    with transaction(create=True) as conn:
        occurrence = _occurrence_row(conn, occurrence_id)
        conn.execute(
            """
            UPDATE occurrences
            SET capture_mode = 'tracked meeting', one_off_prep = 1, ritual_series_id = NULL, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), occurrence_id),
        )
        result = _generate_for_occurrence(conn, occurrence_id)
        result["status"] = "one_off_ready"
        result["title"] = occurrence["title"]
        return result


def set_occurrence_activity_log(occurrence_id: str) -> dict:
    with transaction(create=True) as conn:
        _occurrence_row(conn, occurrence_id)
        conn.execute(
            """
            UPDATE occurrences
            SET capture_mode = 'activity log', one_off_prep = 0, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), occurrence_id),
        )
        record_correction(conn, action_type="keep_activity_log", target_type="occurrence", target_id=occurrence_id)
        return {"status": "activity_log", "occurrence_id": occurrence_id}


def list_unmatched_transcripts() -> list[dict]:
    with transaction(create=True) as conn:
        rows = conn.execute(
            """
            SELECT id, source, title, status, occurrenceMatchConfidence, started_at
            FROM transcripts
            WHERE status IN ('unmatched', 'ambiguous')
            ORDER BY started_at DESC, created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def mark_transcript_not_same_meeting(transcript_id: str, occurrence_id: str) -> dict:
    with transaction(create=True) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO transcript_negative_matches (transcript_id, occurrence_id, created_at)
            VALUES (?, ?, ?)
            """,
            (transcript_id, occurrence_id, utc_now()),
        )
        conn.execute(
            """
            UPDATE transcripts
            SET occurrence_id = CASE WHEN occurrence_id = ? THEN NULL ELSE occurrence_id END,
                status = CASE WHEN occurrence_id = ? THEN 'unmatched' ELSE status END,
                updated_at = ?
            WHERE id = ?
            """,
            (occurrence_id, occurrence_id, utc_now(), transcript_id),
        )
        record_correction(
            conn,
            action_type="transcript_not_same_meeting",
            target_type="transcript",
            target_id=transcript_id,
            payload={"occurrence_id": occurrence_id},
        )
        return {"status": "not_same_meeting", "transcript_id": transcript_id, "occurrence_id": occurrence_id}


def reassign_transcript_to_occurrence(transcript_id: str, occurrence_id: str) -> dict:
    with transaction(create=True) as conn:
        _occurrence_row(conn, occurrence_id)
        conn.execute(
            """
            UPDATE transcripts
            SET occurrence_id = ?, status = 'matched', updated_at = ?
            WHERE id = ?
            """,
            (occurrence_id, utc_now(), transcript_id),
        )
        record_correction(
            conn,
            action_type="reassign_transcript",
            target_type="transcript",
            target_id=transcript_id,
            payload={"occurrence_id": occurrence_id},
        )
        return {"status": "reassigned", "transcript_id": transcript_id, "occurrence_id": occurrence_id}


def create_contact_page(contact_id: str) -> dict:
    with transaction(create=True) as conn:
        result = create_contact_page_record(conn, contact_id)
        record_correction(conn, action_type="create_contact_page", target_type="contact", target_id=contact_id)
        return result


def dismiss_contact_suggestion(contact_id: str, occurrence_id: str) -> dict:
    with transaction(create=True) as conn:
        conn.execute(
            """
            UPDATE contact_suggestions
            SET status = 'dismissed', updated_at = ?
            WHERE contact_id = ? AND occurrence_id = ?
            """,
            (utc_now(), contact_id, occurrence_id),
        )
        conn.execute(
            """
            UPDATE contacts
            SET last_dismissed_occurrence_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (occurrence_id, utc_now(), contact_id),
        )
        record_correction(
            conn,
            action_type="not_now_contact",
            target_type="contact",
            target_id=contact_id,
            payload={"occurrence_id": occurrence_id},
        )
        return {"status": "dismissed", "contact_id": contact_id, "occurrence_id": occurrence_id}


def suppress_contact_suggestion(contact_id: str) -> dict:
    with transaction(create=True) as conn:
        conn.execute(
            "UPDATE contacts SET suggestion_state = 'suppressed', updated_at = ? WHERE id = ?",
            (utc_now(), contact_id),
        )
        conn.execute(
            "UPDATE contact_suggestions SET status = 'suppressed', updated_at = ? WHERE contact_id = ?",
            (utc_now(), contact_id),
        )
        record_correction(conn, action_type="never_suggest_contact", target_type="contact", target_id=contact_id)
        return {"status": "suppressed", "contact_id": contact_id}
