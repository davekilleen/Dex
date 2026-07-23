from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.entity_engine import cooling
from core.entity_engine.contract import (
    merge_frontmatter_text,
    render_company_page,
    render_person_page,
)

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def _touch(ts: str, source_id: str) -> dict:
    return {
        "ts": ts,
        "type": "meeting",
        "direction": "none",
        "source": {"id": source_id},
    }


def _write_entity(
    vault: Path,
    *,
    name: str,
    entity_type: str,
    touches: list[dict],
) -> Path:
    if entity_type == "person":
        path = (
            vault
            / "05-Areas"
            / "People"
            / "External"
            / f"{name.replace(' ', '_')}.md"
        )
        rendered = render_person_page(
            name,
            emails=[f"{name.split()[0].lower()}@example.com"],
            location="external",
        )
    else:
        path = vault / "05-Areas" / "Companies" / f"{name.replace(' ', '_')}.md"
        rendered = render_company_page(name, domains=["example.org"])
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = merge_frontmatter_text(
        path,
        rendered,
        {
            "touches": touches,
            "last_touched": max(
                (str(touch["ts"])[:10] for touch in touches),
                default=None,
            ),
        },
    )
    assert merged is not None
    path.write_text(merged, encoding="utf-8")
    return path


def _report(vault: Path, *, limit: int = 5) -> dict:
    return cooling.cooling_report(
        vault,
        now=NOW,
        limit=limit,
        people_dir=vault / "05-Areas" / "People",
        companies_dir=vault / "05-Areas" / "Companies",
    )


def test_cooling_report_excludes_zero_touch_and_one_engagement_entities(
    tmp_path: Path,
) -> None:
    _write_entity(
        tmp_path,
        name="Zero Touch",
        entity_type="person",
        touches=[],
    )
    _write_entity(
        tmp_path,
        name="One Meeting",
        entity_type="person",
        touches=[_touch("2026-01-01", "meeting-one")],
    )

    report = _report(tmp_path)

    assert report["cold"] == []
    assert report["counts"] == {"person": 0, "company": 0, "total": 0}
    assert "Zero Touch" not in {item["name"] for item in report["cold"]}


def test_consequential_gate_counts_distinct_engagement_days(
    tmp_path: Path,
) -> None:
    _write_entity(
        tmp_path,
        name="Same Day Duplicate",
        entity_type="person",
        touches=[
            _touch("2026-01-01", "granola-meeting-id"),
            _touch("2026-01-01", "meeting-note-basename"),
        ],
    )

    assert _report(tmp_path)["cold"] == []


def test_cooling_report_returns_and_ranks_cold_people_and_companies(
    tmp_path: Path,
) -> None:
    person = _write_entity(
        tmp_path,
        name="Jane Example",
        entity_type="person",
        touches=[
            _touch("2026-04-01", "person-one"),
            _touch("2026-05-01", "person-two"),
        ],
    )
    company = _write_entity(
        tmp_path,
        name="Acme Example",
        entity_type="company",
        touches=[
            _touch("2025-12-01", "company-one"),
            _touch("2026-01-01", "company-two"),
        ],
    )

    report = _report(tmp_path)

    assert report["generated_at"] == NOW.isoformat()
    assert report["counts"] == {"person": 1, "company": 1, "total": 2}
    assert [item["name"] for item in report["cold"]] == [
        "Acme Example",
        "Jane Example",
    ]
    assert report["cold"][0] == {
        "name": "Acme Example",
        "type": "company",
        "page": company.relative_to(tmp_path).as_posix(),
        "days_since_engagement": 203,
        "last_engagement": "2026-01-01",
        "reason": "last engagement was 203 days ago",
    }
    assert report["cold"][1]["page"] == person.relative_to(tmp_path).as_posix()


def test_cli_writes_json_feed_atomically(tmp_path: Path, monkeypatch) -> None:
    _write_entity(
        tmp_path,
        name="Jane Example",
        entity_type="person",
        touches=[
            _touch("2026-04-01", "person-one"),
            _touch("2026-05-01", "person-two"),
        ],
    )
    monkeypatch.chdir(tmp_path)

    assert cooling.main(["--now", NOW.isoformat()]) == 0

    feed = tmp_path / "System" / ".dex" / "entity-cooling.json"
    assert json.loads(feed.read_text(encoding="utf-8"))["cold"][0]["name"] == (
        "Jane Example"
    )
    assert list(feed.parent.glob(".entity-cooling.json.*.tmp")) == []


def test_line_format_handles_details_counts_and_empty() -> None:
    small = {
        "counts": {"person": 1, "company": 1, "total": 2},
        "cold": [
            {"name": "Jane Example", "type": "person", "days_since_engagement": 47},
            {"name": "Acme Example", "type": "company", "days_since_engagement": 63},
        ],
    }
    large = {
        "counts": {"person": 2, "company": 2, "total": 4},
        "cold": [{}, {}, {}, {}],
    }

    assert cooling.format_line(small) == (
        "❄️ Going cold: Jane Example (person, 47d), "
        "Acme Example (account, 63d)"
    )
    assert cooling.format_line(large) == (
        '❄️ Going cold: 2 people, 2 accounts — say "who\'s going cold" '
        "for the list"
    )
    assert cooling.format_line(
        {"counts": {"person": 0, "company": 0, "total": 0}, "cold": []}
    ) == ""

