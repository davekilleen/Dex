"""Explicit contact-page promotion for suggested contacts."""

from __future__ import annotations

import os

from core.paths import PEOPLE_DIR
from core.utils.page_generators import generate_person_page

from .calendar_ingest import get_internal_domains
from .db import DatabaseReadOnlyError, utc_now


def _safe_name(value: str) -> str:
    return "_".join(part for part in value.replace("/", " ").split() if part)


def create_contact_page(conn, contact_id: str) -> dict:
    contact = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    if contact is None:
        raise ValueError(f"Unknown contact: {contact_id}")
    if contact["page_path"]:
        return {"status": "exists", "contact_id": contact_id, "page_path": contact["page_path"]}

    internal_domains = get_internal_domains()
    target_dir = PEOPLE_DIR / ("Internal" if contact["domain"] in internal_domains else "External")
    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(target_dir, os.W_OK):
        raise DatabaseReadOnlyError(f"Contact page directory is not writable: {target_dir}")

    base_name = _safe_name(contact["name"] or contact["email"] or contact_id)
    page_path = target_dir / f"{base_name}.md"
    content = generate_person_page(
        base_name,
        company=contact["domain"].split(".")[0].title() if contact["domain"] else None,
        email=contact["email"],
        notes="Created from a Ritual Intelligence contact suggestion.",
    )
    page_path.write_text(content, encoding="utf-8")
    conn.execute(
        "UPDATE contacts SET page_path = ?, updated_at = ? WHERE id = ?",
        (str(page_path), utc_now(), contact_id),
    )
    conn.execute(
        "UPDATE contact_suggestions SET status = 'created', updated_at = ? WHERE contact_id = ?",
        (utc_now(), contact_id),
    )
    return {"status": "created", "contact_id": contact_id, "page_path": str(page_path)}
