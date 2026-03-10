"""Local transcript ingestion for Granola and manual imports."""

from __future__ import annotations

import json
import platform
import re
from datetime import datetime, timedelta
from pathlib import Path

from .db import transaction, utc_now
from .models import NormalizedAttendee, TranscriptArtifact
from .transcript_store import extract_action_items, extract_decisions, write_transcript_artifact


def _find_latest_cache(granola_dir: Path) -> Path | None:
    candidates = sorted(
        granola_dir.glob("cache-v*.json"),
        key=lambda path: int(re.search(r"v(\d+)", path.name).group(1)) if re.search(r"v(\d+)", path.name) else 0,
        reverse=True,
    )
    return candidates[0] if candidates else None


def granola_cache_path() -> Path:
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        base = home / "Library" / "Application Support" / "Granola"
    elif system == "Windows":
        base = Path.home() / "AppData" / "Roaming" / "Granola"
    else:
        base = home / ".config" / "Granola"
    return _find_latest_cache(base) or base / "cache-v3.json"


def _read_granola_cache(path: Path | None = None) -> dict:
    target = path or granola_cache_path()
    raw = json.loads(target.read_text(encoding="utf-8"))
    cache = json.loads(raw.get("cache", "{}"))
    return cache.get("state", {})


def _normalize_granola_artifacts(cache_state: dict, *, days_back: int = 30) -> list[TranscriptArtifact]:
    documents = cache_state.get("documents", {})
    transcripts = cache_state.get("transcripts", {})
    cutoff = datetime.now() - timedelta(days=days_back)
    artifacts: list[TranscriptArtifact] = []
    for meeting_id, document in documents.items():
        if document.get("type") != "meeting":
            continue
        created_at_raw = document.get("created_at")
        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00")) if created_at_raw else None
        if created_at and created_at.replace(tzinfo=None) < cutoff:
            continue
        transcript_entries = transcripts.get(meeting_id, [])
        raw_text = "\n".join(entry.get("text", "") for entry in transcript_entries if entry.get("text")).strip()
        if not raw_text:
            continue
        attendees = []
        for attendee in document.get("people", {}).get("attendees", []):
            name = (
                attendee.get("details", {}).get("person", {}).get("name", {}).get("fullName")
                or attendee.get("name")
                or attendee.get("email")
            )
            attendees.append(NormalizedAttendee(name=name, email=attendee.get("email")))
        artifacts.append(
            TranscriptArtifact(
                transcript_id=f"trn_{meeting_id}",
                source="granola",
                source_transcript_id=meeting_id,
                title=document.get("title") or "Untitled Meeting",
                started_at=created_at,
                ended_at=None,
                attendees=attendees,
                raw_text=raw_text,
            )
        )
    return artifacts


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


def ingest_granola_local(*, cache_path: Path | None = None, days_back: int = 30) -> list[dict]:
    state = _read_granola_cache(cache_path)
    artifacts = _normalize_granola_artifacts(state, days_back=days_back)
    return ingest_artifacts(artifacts)


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
