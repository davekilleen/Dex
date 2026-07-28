"""Local transcript ingestion for manual file and folder imports."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .db import transaction, utc_now
from .models import TranscriptArtifact
from .transcript_store import extract_action_items, extract_decisions, write_transcript_artifact

SUPPORTED_TRANSCRIPT_SUFFIXES = frozenset({".md", ".txt", ".vtt", ".srt"})


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


def _manual_transcript_imported(file_path: Path) -> bool:
    with transaction(create=True) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM transcripts
            WHERE source = 'manual' AND source_transcript_id = ?
            LIMIT 1
            """,
            (str(file_path),),
        ).fetchone()
    return row is not None


def _is_utf8_text_file(file_path: Path) -> bool:
    raw = file_path.read_bytes()
    if b"\x00" in raw:
        return False
    raw.decode("utf-8")
    return True


def import_manual_transcript_folder(*, folder_path: Path) -> dict:
    """Import supported transcript files below a folder without crossing symlinks."""
    requested_root = Path(folder_path).expanduser()
    if requested_root.is_symlink():
        raise ValueError(f"Transcript folder must not be a symlink: {requested_root}")
    if not requested_root.is_dir():
        raise ValueError(f"Transcript folder does not exist: {requested_root}")
    root = requested_root.resolve(strict=True)

    report = {"imported": 0, "skipped": 0, "failed": 0, "files": []}
    for current_root, directory_names, file_names in os.walk(
        root,
        followlinks=False,
    ):
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not (Path(current_root) / name).is_symlink()
        )
        for file_name in sorted(file_names):
            candidate = Path(current_root) / file_name
            if candidate.suffix.lower() not in SUPPORTED_TRANSCRIPT_SUFFIXES:
                continue

            if candidate.is_symlink():
                report["skipped"] += 1
                report["files"].append(
                    {"path": str(candidate), "status": "skipped"}
                )
                continue

            try:
                canonical_path = candidate.resolve(strict=True)
            except OSError:
                report["skipped"] += 1
                report["files"].append(
                    {"path": str(candidate), "status": "skipped"}
                )
                continue
            if not canonical_path.is_relative_to(root) or not canonical_path.is_file():
                report["skipped"] += 1
                report["files"].append(
                    {"path": str(candidate), "status": "skipped"}
                )
                continue

            try:
                if _manual_transcript_imported(canonical_path):
                    report["skipped"] += 1
                    report["files"].append(
                        {"path": str(canonical_path), "status": "skipped"}
                    )
                    continue
                if not _is_utf8_text_file(canonical_path):
                    report["skipped"] += 1
                    report["files"].append(
                        {"path": str(canonical_path), "status": "skipped"}
                    )
                    continue
            except (OSError, UnicodeError):
                report["skipped"] += 1
                report["files"].append(
                    {"path": str(canonical_path), "status": "skipped"}
                )
                continue
            except Exception:
                report["failed"] += 1
                report["files"].append(
                    {"path": str(canonical_path), "status": "failed"}
                )
                continue

            try:
                import_manual_transcript(
                    file_path=canonical_path,
                    title=canonical_path.stem,
                )
            except Exception:
                report["failed"] += 1
                report["files"].append(
                    {"path": str(canonical_path), "status": "failed"}
                )
                continue
            report["imported"] += 1
            report["files"].append(
                {"path": str(canonical_path), "status": "imported"}
            )
    return report
