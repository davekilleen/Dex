"""Contact suggestion rules and suggestion-state updates."""

from __future__ import annotations

from .db import utc_now


def refresh_contact_suggestions_for_occurrence(conn, occurrence_id: str) -> list[dict]:
    occurrence = conn.execute("SELECT * FROM occurrences WHERE id = ?", (occurrence_id,)).fetchone()
    if occurrence is None:
        raise ValueError(f"Unknown occurrence: {occurrence_id}")
    occurrence = dict(occurrence)

    rows = conn.execute(
        """
        SELECT oc.contact_id, c.name, c.email, c.suggestion_state
        FROM occurrence_contacts oc
        JOIN contacts c ON c.id = oc.contact_id
        WHERE oc.occurrence_id = ?
        """,
        (occurrence_id,),
    ).fetchall()

    suggestions: list[dict] = []
    for row in rows:
        if row["suggestion_state"] != "active":
            continue
        stats = conn.execute(
            """
            SELECT COUNT(DISTINCT o.id) AS tracked_count,
                   COUNT(DISTINCT substr(o.starts_at, 1, 7)) AS month_count,
                   COUNT(DISTINCT strftime('%Y-%W', o.starts_at)) AS week_count
            FROM occurrence_contacts oc
            JOIN occurrences o ON o.id = oc.occurrence_id
            WHERE oc.contact_id = ?
              AND o.capture_mode = 'tracked meeting'
            """,
            (row["contact_id"],),
        ).fetchone()
        transcript_signal = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM occurrence_contacts oc
            JOIN transcripts t ON t.occurrence_id = oc.occurrence_id
            WHERE oc.contact_id = ?
              AND t.status = 'matched'
              AND (t.summary_text IS NOT NULL OR t.raw_text IS NOT NULL)
            """,
            (row["contact_id"],),
        ).fetchone()["count"]

        qualifies = (
            stats["tracked_count"] >= 2
            and (
                stats["week_count"] >= 2
                or transcript_signal > 0
                or bool(occurrence.get("ritual_series_id"))
            )
        )
        status = "suggested" if qualifies else "dismissed"
        conn.execute(
            """
            INSERT OR REPLACE INTO contact_suggestions (contact_id, occurrence_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (row["contact_id"], occurrence_id, status, utc_now(), utc_now()),
        )
        if qualifies:
            suggestions.append(
                {
                    "contact_id": row["contact_id"],
                    "label": row["name"] or row["email"] or "Unknown contact",
                    "status": status,
                }
            )
    return suggestions
