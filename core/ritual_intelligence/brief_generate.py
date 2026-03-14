"""Deterministic ritual brief generation for tracked meetings."""

from __future__ import annotations

from datetime import datetime


def _since_last_time(conn, occurrence: dict) -> list[str]:
    if not occurrence.get("ritual_series_id"):
        return ["- No confirmed prior ritual session yet."]

    row = conn.execute(
        """
        SELECT starts_at, title
        FROM occurrences
        WHERE ritual_series_id = ?
          AND starts_at < ?
          AND state != 'cancelled'
        ORDER BY starts_at DESC
        LIMIT 1
        """,
        (occurrence["ritual_series_id"], occurrence["starts_at"]),
    ).fetchone()
    if not row:
        return ["- No prior occurrence found."]
    previous_date = datetime.fromisoformat(row["starts_at"]).date().isoformat()
    return [f"- Previous session: {previous_date}"]


def _talking_points(conn, occurrence: dict) -> list[str]:
    points = [f"- Review agenda for {occurrence['title']}"]
    if occurrence.get("ritual_series_id"):
        transcript = conn.execute(
            """
            SELECT t.summary_text
            FROM occurrences o
            JOIN transcripts t ON t.occurrence_id = o.id
            WHERE o.ritual_series_id = ?
              AND o.starts_at < ?
              AND o.state != 'cancelled'
              AND t.status = 'matched'
              AND t.summary_text IS NOT NULL
            ORDER BY o.starts_at DESC, t.updated_at DESC
            LIMIT 1
            """,
            (occurrence["ritual_series_id"], occurrence["starts_at"]),
        ).fetchone()
    else:
        transcript = conn.execute(
            """
            SELECT summary_text
            FROM transcripts
            WHERE occurrence_id = ?
              AND status = 'matched'
              AND summary_text IS NOT NULL
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (occurrence["id"],),
        ).fetchone()
    if transcript and transcript["summary_text"]:
        points.append(f"- Transcript continuity: {transcript['summary_text'].splitlines()[0]}")
    else:
        points.append("- No transcript continuity yet.")
    return points


def render_contact_suggestions(conn, occurrence: dict) -> str:
    rows = conn.execute(
        """
        SELECT c.id, COALESCE(c.name, c.email, 'Unknown contact') AS label, cs.status
        FROM contact_suggestions cs
        JOIN contacts c ON c.id = cs.contact_id
        WHERE cs.occurrence_id = ?
          AND cs.status = 'suggested'
          AND c.suggestion_state = 'active'
        ORDER BY label ASC
        """,
        (occurrence["id"],),
    ).fetchall()
    if not rows:
        return ""
    lines = ["", "### Suggested contact pages"]
    for row in rows:
        lines.append(f"- {row['label']} — [Create page] [Not now] [Never suggest]")
    return "\n".join(lines)


def generate_brief_markdown(conn, occurrence_id: str) -> str:
    occurrence = conn.execute("SELECT * FROM occurrences WHERE id = ?", (occurrence_id,)).fetchone()
    if occurrence is None:
        raise ValueError(f"Unknown occurrence: {occurrence_id}")
    occurrence = dict(occurrence)

    lines = [
        "## Prep (AI-generated)",
        "",
        "### Since Last Time",
        *_since_last_time(conn, occurrence),
        "",
        "### Talking Points",
        *_talking_points(conn, occurrence),
        "",
        "### Capture Template",
        "- Decisions made:",
        "- Actions for me:",
        "- Actions for them:",
        "- Key takeaway:",
    ]
    suggestion_block = render_contact_suggestions(conn, occurrence)
    if suggestion_block:
        lines.append(suggestion_block)
    return "\n".join(lines).strip()
