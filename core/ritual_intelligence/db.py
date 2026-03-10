"""SQLite bootstrap and safety checks for Ritual Intelligence."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from core.paths import DEX_RUNTIME_DIR, RITUAL_INTELLIGENCE_DB_FILE, SYSTEM_DIR


class RitualIntelligenceError(RuntimeError):
    """Base runtime error for Ritual Intelligence."""


class VaultStateError(RitualIntelligenceError):
    """Raised when the active vault cannot host the runtime."""


class DatabaseReadOnlyError(RitualIntelligenceError):
    """Raised when the runtime DB cannot be created or written."""


class DatabaseCorruptError(RitualIntelligenceError):
    """Raised when the runtime DB exists but is invalid/corrupt."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_db_path() -> Path:
    return RITUAL_INTELLIGENCE_DB_FILE


def ensure_runtime_dir() -> Path:
    """Create the vault-local runtime directory if safe to do so."""
    if not SYSTEM_DIR.exists():
        raise VaultStateError(
            f"Missing System directory for active vault: {SYSTEM_DIR}. Ritual Intelligence requires a Dex vault."
        )
    if not SYSTEM_DIR.is_dir():
        raise VaultStateError(f"System path is not a directory: {SYSTEM_DIR}")
    if not os.access(SYSTEM_DIR, os.W_OK):
        raise DatabaseReadOnlyError(f"System directory is not writable: {SYSTEM_DIR}")

    if not DEX_RUNTIME_DIR.exists():
        try:
            DEX_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DatabaseReadOnlyError(f"Unable to create runtime directory: {DEX_RUNTIME_DIR}") from exc

    if not os.access(DEX_RUNTIME_DIR, os.W_OK):
        raise DatabaseReadOnlyError(f"Runtime directory is not writable: {DEX_RUNTIME_DIR}")
    return DEX_RUNTIME_DIR


def _validate_database(conn: sqlite3.Connection) -> None:
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise DatabaseCorruptError(f"Ritual Intelligence database is corrupt: {get_db_path()}") from exc

    if not result or result[0] != "ok":
        raise DatabaseCorruptError(f"Ritual Intelligence database failed integrity check: {get_db_path()}")


def connect(*, create: bool = True) -> sqlite3.Connection:
    """Open the vault-local runtime DB with explicit safety checks."""
    db_path = get_db_path()
    if create:
        ensure_runtime_dir()
    elif not db_path.exists():
        raise VaultStateError(f"Ritual Intelligence database does not exist: {db_path}")

    if db_path.exists() and not os.access(db_path, os.W_OK):
        raise DatabaseReadOnlyError(f"Ritual Intelligence database is read-only: {db_path}")

    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.OperationalError as exc:
        raise DatabaseReadOnlyError(f"Unable to open Ritual Intelligence database: {db_path}") from exc

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _validate_database(conn)
    return conn


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS occurrences (
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      starts_at TEXT NOT NULL,
      ends_at TEXT,
      state TEXT NOT NULL,
      capture_mode TEXT NOT NULL,
      provider TEXT NOT NULL,
      source_series_id TEXT,
      series_key TEXT,
      ritual_series_id TEXT,
      note_path TEXT,
      note_path_kind TEXT,
      daily_log_path TEXT,
      one_off_prep INTEGER NOT NULL DEFAULT 0,
      user_locked INTEGER NOT NULL DEFAULT 0,
      prep_hash TEXT,
      prep_generated_at TEXT,
      last_generated_brief TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_occurrences_starts_at ON occurrences(starts_at)",
    "CREATE INDEX IF NOT EXISTS idx_occurrences_series_key ON occurrences(series_key)",
    """
    CREATE TABLE IF NOT EXISTS source_events (
      provider TEXT NOT NULL,
      source_event_id TEXT NOT NULL,
      occurrence_id TEXT NOT NULL,
      source_series_id TEXT,
      calendar_id TEXT,
      last_seen_at TEXT NOT NULL,
      raw_payload TEXT,
      PRIMARY KEY(provider, source_event_id),
      FOREIGN KEY(occurrence_id) REFERENCES occurrences(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ritual_series (
      id TEXT PRIMARY KEY,
      series_key TEXT NOT NULL UNIQUE,
      title TEXT NOT NULL,
      occurrence_count INTEGER NOT NULL DEFAULT 0,
      recurring_pattern_score REAL NOT NULL DEFAULT 0,
      status TEXT NOT NULL,
      reason TEXT,
      confirmed_at TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS manual_note_links (
      occurrence_id TEXT PRIMARY KEY,
      note_path TEXT NOT NULL,
      source_kind TEXT NOT NULL,
      confidence REAL NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(occurrence_id) REFERENCES occurrences(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transcripts (
      id TEXT PRIMARY KEY,
      source TEXT NOT NULL,
      source_transcript_id TEXT NOT NULL,
      title TEXT NOT NULL,
      started_at TEXT,
      ended_at TEXT,
      source_event_id TEXT,
      attendees_json TEXT,
      occurrence_id TEXT,
      status TEXT NOT NULL,
      occurrenceMatchConfidence REAL,
      raw_path TEXT,
      summary_path TEXT,
      raw_text TEXT,
      summary_text TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(source, source_transcript_id),
      FOREIGN KEY(occurrence_id) REFERENCES occurrences(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transcript_negative_matches (
      transcript_id TEXT NOT NULL,
      occurrence_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      PRIMARY KEY(transcript_id, occurrence_id),
      FOREIGN KEY(transcript_id) REFERENCES transcripts(id) ON DELETE CASCADE,
      FOREIGN KEY(occurrence_id) REFERENCES occurrences(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transcript_action_items (
      id TEXT PRIMARY KEY,
      transcript_id TEXT NOT NULL,
      owner_name TEXT,
      owner_email TEXT,
      action_text TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'open',
      created_at TEXT NOT NULL,
      FOREIGN KEY(transcript_id) REFERENCES transcripts(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transcript_decisions (
      id TEXT PRIMARY KEY,
      transcript_id TEXT NOT NULL,
      decision_text TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(transcript_id) REFERENCES transcripts(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contacts (
      id TEXT PRIMARY KEY,
      name TEXT,
      email TEXT UNIQUE,
      normalized_name TEXT,
      domain TEXT,
      page_path TEXT,
      suggestion_state TEXT NOT NULL DEFAULT 'active',
      last_dismissed_occurrence_id TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS occurrence_contacts (
      occurrence_id TEXT NOT NULL,
      contact_id TEXT NOT NULL,
      attendee_name TEXT,
      attendee_email TEXT,
      attendee_type TEXT,
      is_external INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(occurrence_id, contact_id),
      FOREIGN KEY(occurrence_id) REFERENCES occurrences(id) ON DELETE CASCADE,
      FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contact_suggestions (
      contact_id TEXT NOT NULL,
      occurrence_id TEXT NOT NULL,
      status TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(contact_id, occurrence_id),
      FOREIGN KEY(contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
      FOREIGN KEY(occurrence_id) REFERENCES occurrences(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS corrections (
      id TEXT PRIMARY KEY,
      action_type TEXT NOT NULL,
      target_type TEXT NOT NULL,
      target_id TEXT NOT NULL,
      payload TEXT,
      created_at TEXT NOT NULL
    )
    """,
)


def bootstrap_database(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    """Ensure the vault-local runtime DB exists and has the required schema."""
    owned = conn is None
    if owned:
        conn = connect(create=True)
    for statement in SCHEMA:
        conn.execute(statement)
    conn.commit()
    return conn


@contextmanager
def transaction(*, create: bool = True) -> Iterator[sqlite3.Connection]:
    """Context manager with commit/rollback semantics."""
    conn = bootstrap_database() if create else connect(create=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
