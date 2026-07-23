from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.entity_engine import relationships
from core.entity_engine.contract import (
    merge_frontmatter_text,
    render_company_page,
    render_person_page,
)

NOW = datetime(2026, 7, 24, 9, 30, tzinfo=timezone.utc)


def _relationship(
    *,
    relation_type: str,
    target: str,
    status: str,
    source_id: str,
    date: str,
) -> dict:
    return {
        "type": relation_type,
        "target": target,
        "status": status,
        "source": {"kind": "meeting", "id": source_id},
        "date": date,
    }


def _write_entity(
    vault: Path,
    *,
    name: str,
    entity_type: str,
    page_name: str,
    relationships: list[dict],
) -> Path:
    if entity_type == "person":
        path = vault / "05-Areas" / "People" / "External" / f"{page_name}.md"
        rendered = render_person_page(
            name,
            emails=[f"{page_name.casefold()}@example.com"],
            location="external",
        )
    else:
        path = vault / "05-Areas" / "Companies" / f"{page_name}.md"
        rendered = render_company_page(name, domains=["example.org"])
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = merge_frontmatter_text(
        path,
        rendered,
        {"relationships": relationships},
    )
    assert merged is not None
    path.write_text(merged, encoding="utf-8")
    return path


def test_feed_contains_only_suggested_relationships_with_schema_shape(
    tmp_path: Path,
) -> None:
    person = _write_entity(
        tmp_path,
        name="Jane Example",
        entity_type="person",
        page_name="Jane_Example",
        relationships=[
            _relationship(
                relation_type="works_at",
                target="[[Acme]]",
                status="suggested",
                source_id="meeting-123",
                date="2026-07-23",
            ),
            _relationship(
                relation_type="reports_to",
                target="[[Alex Boss]]",
                status="confirmed",
                source_id="meeting-456",
                date="2026-07-22",
            ),
        ],
    )
    _write_entity(
        tmp_path,
        name="Acme",
        entity_type="company",
        page_name="Acme",
        relationships=[
            _relationship(
                relation_type="related_to",
                target="[[Partner Co]]",
                status="confirmed",
                source_id="meeting-789",
                date="2026-07-21",
            ),
        ],
    )

    report = relationships.relationships_report(tmp_path, now=NOW)

    assert report == {
        "schema": 1,
        "generated_at": NOW.isoformat(),
        "suggestions": [
            {
                "src_ref": "[[Jane Example]]",
                "src_path": person.relative_to(tmp_path).as_posix(),
                "type": "works_at",
                "target_ref": "[[Acme]]",
                "source": {
                    "kind": "meeting",
                    "id": "meeting-123",
                    "date": "2026-07-23",
                },
                "first_seen": "2026-07-23",
            }
        ],
    }


def test_cli_writes_empty_feed_atomically(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_entity(
        tmp_path,
        name="Jane Example",
        entity_type="person",
        page_name="Jane_Example",
        relationships=[],
    )
    monkeypatch.chdir(tmp_path)

    assert relationships.main(["--now", NOW.isoformat()]) == 0

    feed = tmp_path / "System" / ".dex" / "entity-relationships.json"
    assert json.loads(feed.read_text(encoding="utf-8")) == {
        "schema": 1,
        "generated_at": NOW.isoformat(),
        "suggestions": [],
    }
    assert list(feed.parent.glob(".entity-relationships.json.*.tmp")) == []


def test_line_format_handles_details_counts_and_empty() -> None:
    small = {
        "suggestions": [
            {
                "src_ref": "[[Jane Example]]",
                "type": "works_at",
                "target_ref": "[[Acme]]",
            },
            {
                "src_ref": "[[Alex Boss]]",
                "type": "reports_to",
                "target_ref": "[[Jane_Example]]",
            },
        ]
    }
    large = {"suggestions": [{}, {}, {}, {}]}

    assert relationships.format_line(small) == (
        "🔗 Relationships to confirm: Jane Example → Acme (works_at), "
        "Alex Boss → Jane Example (reports_to)"
    )
    assert relationships.format_line(large) == (
        '🔗 Relationships to confirm: 4 suggestions — say "relationship radar" '
        "to review"
    )
    assert relationships.format_line({"suggestions": []}) == ""
