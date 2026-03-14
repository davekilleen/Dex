"""Read-only compatibility matching for existing manual meeting notes."""

from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from core.paths import LEGACY_MEETINGS_DIR, TRACKED_MEETINGS_DIR

from .db import utc_now


def _normalize(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _score_candidate(occurrence: dict, path: Path) -> float:
    meeting_date = datetime.fromisoformat(occurrence["starts_at"]).date().isoformat()
    normalized_title = _normalize(occurrence["title"])
    stem = _normalize(path.stem)
    ratio = SequenceMatcher(None, normalized_title, stem).ratio()
    if meeting_date in path.name:
        ratio += 0.2
    return round(min(ratio, 1.0), 2)


def _candidate_files() -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    if TRACKED_MEETINGS_DIR.exists():
        candidates.extend(("tracked_existing", path) for path in TRACKED_MEETINGS_DIR.glob("*.md"))
    if LEGACY_MEETINGS_DIR.exists():
        candidates.extend(("legacy_read_only", path) for path in LEGACY_MEETINGS_DIR.rglob("*.md"))
    return candidates


def ensure_manual_note_link(conn, occurrence_id: str) -> dict | None:
    existing = conn.execute(
        "SELECT note_path, source_kind, confidence FROM manual_note_links WHERE occurrence_id = ?",
        (occurrence_id,),
    ).fetchone()
    if existing:
        return dict(existing)

    occurrence = conn.execute("SELECT * FROM occurrences WHERE id = ?", (occurrence_id,)).fetchone()
    if occurrence is None:
        raise ValueError(f"Unknown occurrence: {occurrence_id}")
    occurrence = dict(occurrence)

    ranked = []
    for source_kind, path in _candidate_files():
        ranked.append((source_kind, path, _score_candidate(occurrence, path)))
    ranked.sort(key=lambda item: item[2], reverse=True)
    if not ranked:
        return None

    best_kind, best_path, best_score = ranked[0]
    second_score = ranked[1][2] if len(ranked) > 1 else 0.0
    if best_score < 0.9 or (best_score - second_score) < 0.05:
        return None

    conn.execute(
        """
        INSERT INTO manual_note_links (occurrence_id, note_path, source_kind, confidence, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (occurrence_id, str(best_path), best_kind, best_score, utc_now(), utc_now()),
    )
    conn.execute(
        "UPDATE occurrences SET note_path = ?, note_path_kind = ?, updated_at = ? WHERE id = ?",
        (str(best_path), best_kind, utc_now(), occurrence_id),
    )
    return {"note_path": str(best_path), "source_kind": best_kind, "confidence": best_score}
