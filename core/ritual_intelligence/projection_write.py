"""Projection writer for tracked meeting notes and daily logs."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from core.paths import MEETING_DAILY_LOGS_DIR, TRACKED_MEETINGS_DIR

from .db import DatabaseReadOnlyError, utc_now
from .prep_state import extract_prep_block, prep_hash, replace_prep_block


def _ensure_projection_dirs() -> None:
    for directory in (TRACKED_MEETINGS_DIR, MEETING_DAILY_LOGS_DIR):
        parent = directory.parent
        if not parent.exists():
            raise DatabaseReadOnlyError(f"Missing parent directory for Ritual Intelligence projections: {parent}")
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
        if not os.access(directory, os.W_OK):
            raise DatabaseReadOnlyError(f"Projection directory is not writable: {directory}")


def _slug_title(title: str) -> str:
    return "".join(ch if ch.isalnum() or ch in (" ", "-", "_") else "" for ch in title).strip() or "Meeting"


def tracked_note_path(occurrence: dict) -> Path:
    starts_at = datetime.fromisoformat(occurrence["starts_at"])
    title = _slug_title(occurrence["title"])
    return TRACKED_MEETINGS_DIR / f"{starts_at.date().isoformat()} - {title}.md"


def _render_note_shell(occurrence: dict, prep_markdown: str) -> str:
    starts_at = datetime.fromisoformat(occurrence["starts_at"]).date().isoformat()
    ritual_line = f"ritual_id: {occurrence['ritual_series_id']}\n" if occurrence.get("ritual_series_id") else ""
    return (
        f"---\n"
        f"date: {starts_at}\n"
        f"title: {occurrence['title']}\n"
        f"{ritual_line}"
        f"status: {occurrence['state']}\n"
        f"---\n\n"
        f"<!-- dex:prep:start -->\n"
        f"{prep_markdown}\n"
        f"<!-- dex:prep:end -->\n\n"
        f"## Notes\n\n"
    )


def write_tracked_meeting_note(conn, occurrence_id: str, prep_markdown: str, *, force_refresh: bool = False) -> dict:
    _ensure_projection_dirs()
    occurrence = conn.execute("SELECT * FROM occurrences WHERE id = ?", (occurrence_id,)).fetchone()
    if occurrence is None:
        raise ValueError(f"Unknown occurrence: {occurrence_id}")
    occurrence = dict(occurrence)
    note_path = Path(occurrence["note_path"]) if occurrence.get("note_path") else tracked_note_path(occurrence)
    generated_hash = prep_hash(prep_markdown)

    if note_path.exists():
        existing_text = note_path.read_text(encoding="utf-8")
        existing_block = extract_prep_block(existing_text)
        if occurrence.get("user_locked") and not force_refresh:
            return {"status": "skipped", "reason": "user_locked", "note_path": str(note_path)}
        if existing_block and occurrence.get("prep_hash") and prep_hash(existing_block) != occurrence.get("prep_hash"):
            conn.execute(
                "UPDATE occurrences SET user_locked = 1, updated_at = ? WHERE id = ?",
                (utc_now(), occurrence_id),
            )
            return {"status": "skipped", "reason": "user_locked", "note_path": str(note_path)}
        rendered = replace_prep_block(existing_text, prep_markdown)
    else:
        rendered = _render_note_shell(occurrence, prep_markdown)

    note_path.write_text(rendered, encoding="utf-8")
    conn.execute(
        """
        UPDATE occurrences
        SET note_path = ?, note_path_kind = 'tracked', prep_hash = ?, prep_generated_at = ?, last_generated_brief = ?,
            user_locked = 0, updated_at = ?
        WHERE id = ?
        """,
        (str(note_path), generated_hash, utc_now(), prep_markdown, utc_now(), occurrence_id),
    )
    return {"status": "written", "note_path": str(note_path)}


def write_daily_log(conn, meeting_date: str) -> dict:
    _ensure_projection_dirs()
    log_path = MEETING_DAILY_LOGS_DIR / f"{meeting_date}.md"
    rows = conn.execute(
        """
        SELECT id, title, starts_at, ends_at, capture_mode, note_path
        FROM occurrences
        WHERE substr(starts_at, 1, 10) = ?
          AND state != 'cancelled'
        ORDER BY starts_at ASC
        """,
        (meeting_date,),
    ).fetchall()
    lines = [f"## {meeting_date}"]
    for row in rows:
        start = datetime.fromisoformat(row["starts_at"]).strftime("%H:%M")
        line = f"- {start} {row['title']}"
        if row["capture_mode"] == "tracked meeting" and row["note_path"]:
            note_name = Path(row["note_path"]).name
            line += f" -> [[{note_name}]]"
        lines.append(line)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for row in rows:
        conn.execute(
            "UPDATE occurrences SET daily_log_path = ?, updated_at = ? WHERE id = ?",
            (str(log_path), utc_now(), row["id"]),
        )
    return {"status": "written", "daily_log_path": str(log_path), "occurrence_count": len(rows)}
