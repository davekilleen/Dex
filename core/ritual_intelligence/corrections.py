"""Correction logging for Ritual Intelligence actions."""

from __future__ import annotations

import json
import uuid

from .db import utc_now


def record_correction(conn, *, action_type: str, target_type: str, target_id: str, payload: dict | None = None) -> None:
    conn.execute(
        """
        INSERT INTO corrections (id, action_type, target_type, target_id, payload, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            f"corr_{uuid.uuid4().hex[:16]}",
            action_type,
            target_type,
            target_id,
            json.dumps(payload or {}, sort_keys=True),
            utc_now(),
        ),
    )
