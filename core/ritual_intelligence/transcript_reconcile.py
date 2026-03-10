"""Reconcile transcript artifacts onto canonical occurrences."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from .db import transaction, utc_now
from .matching import occurrence_match_confidence
from .models import NormalizedAttendee, TranscriptArtifact


def _load_occurrence_contacts(conn, occurrence_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT attendee_name, attendee_email, attendee_type
        FROM occurrence_contacts
        WHERE occurrence_id = ?
        """,
        (occurrence_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _candidate_occurrences(conn, transcript_row: dict) -> list[dict]:
    if transcript_row.get("started_at"):
        started_at = datetime.fromisoformat(transcript_row["started_at"])
        earliest = (started_at - timedelta(hours=6)).isoformat()
        latest = (started_at + timedelta(hours=6)).isoformat()
        rows = conn.execute(
            """
            SELECT o.*, se.source_event_id
            FROM occurrences o
            LEFT JOIN source_events se ON se.occurrence_id = o.id AND se.provider = o.provider
            WHERE o.starts_at BETWEEN ? AND ?
            ORDER BY o.starts_at ASC
            """,
            (earliest, latest),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT o.*, se.source_event_id
            FROM occurrences o
            LEFT JOIN source_events se ON se.occurrence_id = o.id AND se.provider = o.provider
            ORDER BY o.starts_at DESC
            LIMIT 20
            """
        ).fetchall()
    return [dict(row) for row in rows]


def reconcile_unmatched_transcripts() -> list[dict]:
    results: list[dict] = []
    with transaction(create=True) as conn:
        transcript_rows = conn.execute(
            """
            SELECT *
            FROM transcripts
            WHERE status IN ('unmatched', 'ambiguous')
            ORDER BY started_at DESC, created_at DESC
            """
        ).fetchall()
        for transcript_row in transcript_rows:
            transcript = TranscriptArtifact(
                transcript_id=transcript_row["id"],
                source=transcript_row["source"],
                source_transcript_id=transcript_row["source_transcript_id"],
                title=transcript_row["title"],
                started_at=datetime.fromisoformat(transcript_row["started_at"]) if transcript_row["started_at"] else None,
                ended_at=datetime.fromisoformat(transcript_row["ended_at"]) if transcript_row["ended_at"] else None,
                source_event_id=transcript_row["source_event_id"],
                attendees=[
                    NormalizedAttendee(
                        name=entry.get("name"),
                        email=entry.get("email"),
                        status=entry.get("status"),
                        attendee_type=entry.get("attendee_type"),
                    )
                    for entry in json.loads(transcript_row["attendees_json"] or "[]")
                ],
                raw_text=transcript_row["raw_text"],
            )
            candidates = []
            for occurrence in _candidate_occurrences(conn, dict(transcript_row)):
                negative = conn.execute(
                    """
                    SELECT 1
                    FROM transcript_negative_matches
                    WHERE transcript_id = ? AND occurrence_id = ?
                    """,
                    (transcript.transcript_id, occurrence["id"]),
                ).fetchone()
                if negative:
                    continue
                contacts = _load_occurrence_contacts(conn, occurrence["id"])
                confidence = occurrence_match_confidence(transcript, occurrence, contacts)
                candidates.append((confidence, occurrence))

            candidates.sort(key=lambda item: item[0], reverse=True)
            best_confidence = candidates[0][0] if candidates else 0.0
            second_confidence = candidates[1][0] if len(candidates) > 1 else 0.0

            if best_confidence >= 0.75 and (best_confidence - second_confidence) >= 0.1:
                best_occurrence = candidates[0][1]
                conn.execute(
                    """
                    UPDATE transcripts
                    SET occurrence_id = ?, status = 'matched', occurrenceMatchConfidence = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (best_occurrence["id"], best_confidence, utc_now(), transcript.transcript_id),
                )
                if best_confidence >= 0.9 and best_occurrence["capture_mode"] == "activity log":
                    conn.execute(
                        "UPDATE occurrences SET capture_mode = 'tracked meeting', updated_at = ? WHERE id = ?",
                        (utc_now(), best_occurrence["id"]),
                    )
                results.append(
                    {
                        "transcript_id": transcript.transcript_id,
                        "status": "matched",
                        "occurrence_id": best_occurrence["id"],
                        "occurrenceMatchConfidence": best_confidence,
                    }
                )
            elif best_confidence >= 0.5:
                conn.execute(
                    """
                    UPDATE transcripts
                    SET status = 'ambiguous', occurrenceMatchConfidence = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (best_confidence, utc_now(), transcript.transcript_id),
                )
                results.append(
                    {
                        "transcript_id": transcript.transcript_id,
                        "status": "ambiguous",
                        "occurrenceMatchConfidence": best_confidence,
                    }
                )
            else:
                conn.execute(
                    """
                    UPDATE transcripts
                    SET status = 'unmatched', occurrenceMatchConfidence = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (best_confidence, utc_now(), transcript.transcript_id),
                )
                results.append(
                    {
                        "transcript_id": transcript.transcript_id,
                        "status": "unmatched",
                        "occurrenceMatchConfidence": best_confidence,
                    }
                )
    return results
