"""Recurring ritual suggestion and prep targeting logic."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from .db import transaction, utc_now


def _score_occurrence_count(count: int) -> float:
    if count <= 1:
        return 0.0
    if count == 2:
        return 0.85
    if count == 3:
        return 0.9
    return 0.95


def refresh_ritual_suggestions() -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=28)).isoformat()
    with transaction(create=True) as conn:
        rows = conn.execute(
            """
            SELECT series_key, MIN(title) AS title, COUNT(*) AS occurrence_count
            FROM occurrences
            WHERE starts_at >= ?
              AND state != 'cancelled'
            GROUP BY series_key
            HAVING COUNT(*) >= 2
            ORDER BY occurrence_count DESC, title ASC
            """,
            (cutoff,),
        ).fetchall()
        suggestions: list[dict] = []
        for row in rows:
            score = _score_occurrence_count(row["occurrence_count"])
            series = conn.execute(
                "SELECT id, status FROM ritual_series WHERE series_key = ?",
                (row["series_key"],),
            ).fetchone()
            series_id = series["id"] if series else f"ritual_{hashlib.sha1(row['series_key'].encode('utf-8')).hexdigest()[:16]}"
            status = series["status"] if series else "suggested"
            reason = f"Recurring {row['occurrence_count']} times in the last 4 weeks"
            conn.execute(
                """
                INSERT INTO ritual_series (
                  id, series_key, title, occurrence_count, recurring_pattern_score, status, reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(series_key) DO UPDATE SET
                  title = excluded.title,
                  occurrence_count = excluded.occurrence_count,
                  recurring_pattern_score = excluded.recurring_pattern_score,
                  reason = excluded.reason,
                  updated_at = excluded.updated_at
                """,
                (series_id, row["series_key"], row["title"], row["occurrence_count"], score, status, reason, utc_now(), utc_now()),
            )
            suggestions.append(
                {
                    "series_id": series_id,
                    "series_key": row["series_key"],
                    "title": row["title"],
                    "occurrence_count": row["occurrence_count"],
                    "recurring_pattern_score": score,
                    "reason": reason,
                    "status": status,
                }
            )
        return [suggestion for suggestion in suggestions if suggestion["status"] == "suggested"]


def list_ritual_suggestions() -> list[dict]:
    return refresh_ritual_suggestions()


def _upcoming_confirmed_occurrence_ids(conn, *, now: datetime | None = None) -> list[str]:
    current = now or datetime.now().astimezone()
    today = current.date()
    days_until_end_of_week = 6 - current.weekday()
    horizon_end = current + timedelta(days=days_until_end_of_week)
    if current.weekday() == 4:
        horizon_end = current + timedelta(days=days_until_end_of_week + 7)

    rows = conn.execute(
        """
        SELECT o.id
        FROM occurrences o
        JOIN ritual_series rs ON rs.id = o.ritual_series_id
        WHERE rs.status = 'confirmed'
          AND o.state != 'cancelled'
          AND o.starts_at >= ?
          AND o.starts_at <= ?
        ORDER BY o.starts_at ASC
        """,
        (
            datetime.combine(today, datetime.min.time(), tzinfo=current.tzinfo).isoformat(),
            horizon_end.isoformat(),
        ),
    ).fetchall()
    return [row["id"] for row in rows]


def upcoming_confirmed_occurrence_ids(*, now: datetime | None = None) -> list[str]:
    with transaction(create=True) as conn:
        return _upcoming_confirmed_occurrence_ids(conn, now=now)
