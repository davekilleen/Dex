"""Local transcript ingestion for external artifacts and manual imports."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .db import transaction, utc_now
from .models import TranscriptArtifact
from .transcript_store import extract_action_items, extract_decisions, write_transcript_artifact


def ingest_artifacts(artifacts: list[TranscriptArtifact]) -> list[dict]:
    results: list[dict] = []
    with transaction(create=True) as conn:
        for artifact in artifacts:
            raw_path, summary_path, summary_text = write_transcript_artifact(
                artifact.source,
                artifact.transcript_id,
                artifact.title,
                artifact.raw_text or "",
            )
            conn.execute(
                """
                INSERT INTO transcripts (
                  id, source, source_transcript_id, title, started_at, ended_at, source_event_id,
                  attendees_json, status, occurrenceMatchConfidence, raw_path, summary_path, raw_text, summary_text, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unmatched', NULL, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, source_transcript_id) DO UPDATE SET
                  title = excluded.title,
                  started_at = excluded.started_at,
                  ended_at = excluded.ended_at,
                  source_event_id = excluded.source_event_id,
                  attendees_json = excluded.attendees_json,
                  raw_path = excluded.raw_path,
                  summary_path = excluded.summary_path,
                  raw_text = excluded.raw_text,
                  summary_text = excluded.summary_text,
                  updated_at = excluded.updated_at
                """,
                (
                    artifact.transcript_id,
                    artifact.source,
                    artifact.source_transcript_id,
                    artifact.title,
                    artifact.started_at.isoformat() if artifact.started_at else None,
                    artifact.ended_at.isoformat() if artifact.ended_at else None,
                    artifact.source_event_id,
                    json.dumps([attendee.as_dict() for attendee in artifact.attendees], sort_keys=True),
                    raw_path,
                    summary_path,
                    artifact.raw_text,
                    summary_text,
                    utc_now(),
                    utc_now(),
                ),
            )
            conn.execute("DELETE FROM transcript_action_items WHERE transcript_id = ?", (artifact.transcript_id,))
            conn.execute("DELETE FROM transcript_decisions WHERE transcript_id = ?", (artifact.transcript_id,))
            for index, action_text in enumerate(extract_action_items(artifact.raw_text or ""), start=1):
                conn.execute(
                    """
                    INSERT INTO transcript_action_items (id, transcript_id, action_text, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (f"tact_{artifact.transcript_id}_{index}", artifact.transcript_id, action_text, utc_now()),
                )
            for index, decision_text in enumerate(extract_decisions(artifact.raw_text or ""), start=1):
                conn.execute(
                    """
                    INSERT INTO transcript_decisions (id, transcript_id, decision_text, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (f"tdcs_{artifact.transcript_id}_{index}", artifact.transcript_id, decision_text, utc_now()),
                )
            results.append({"transcript_id": artifact.transcript_id, "source": artifact.source})
    return results


def import_manual_transcript(
    *,
    file_path: Path,
    title: str,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    source_event_id: str | None = None,
) -> dict:
    raw_text = file_path.read_text(encoding="utf-8")
    artifact = TranscriptArtifact(
        transcript_id=f"trn_manual_{file_path.stem}",
        source="manual",
        source_transcript_id=str(file_path),
        title=title,
        started_at=started_at,
        ended_at=ended_at,
        source_event_id=source_event_id,
        raw_text=raw_text,
    )
    return ingest_artifacts([artifact])[0]
