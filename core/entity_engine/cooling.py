"""Read-only cooling report and JSON feed for consequential relationships.

The feed written to ``System/.dex/entity-cooling.json`` has this stable shape::

    {
      "generated_at": "<ISO datetime>",
      "counts": {"person": 0, "company": 0, "total": 0},
      "cold": [{
        "name": "...",
        "type": "person|company",
        "page": "<vault-relative path>",
        "days_since_engagement": 0,
        "last_engagement": "YYYY-MM-DD",
        "reason": "..."
      }]
    }

Batch sync identifies a meeting touch by Granola meeting id, while the
post-meeting hook uses the meeting-note basename. That bounded source-id
divergence loses no data, and same-day double counting is neutralized here by
requiring engagement on at least two distinct dates.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import index
from .temperature import classify_temperature

_FEED_RELATIVE_PATH = Path("System/.dex/entity-cooling.json")


def _engagement_date(touch: Mapping[str, Any]) -> str | None:
    touch_type = str(touch.get("type") or "").casefold()
    direction = str(touch.get("direction") or "").casefold()
    if not (
        (touch_type == "meeting" and direction in {"", "none"})
        or direction == "in"
    ):
        return None
    timestamp = touch.get("ts")
    if not isinstance(timestamp, str):
        return None
    candidate = timestamp[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def _load_nodes(vault_root: Path) -> list[dict[str, Any]]:
    by_node: dict[str, dict[str, Any]] = {}
    with closing(index.connect(index.database_path(vault_root))) as connection:
        rows = connection.execute(
            """
            SELECT
                n.id, n.type, n.name, n.source_path,
                t.ts, t.touch_type, t.direction, t.source, t.nature
            FROM nodes AS n
            JOIN source_files AS f ON f.path = n.source_path
            LEFT JOIN touches AS t ON t.node_id = n.id
            WHERE f.quarantined = 0
            ORDER BY n.id, t.ts, t.touch_type, t.source
            """
        )
        for (
            node_id,
            entity_type,
            name,
            source_path,
            timestamp,
            touch_type,
            direction,
            source,
            nature,
        ) in rows:
            node = by_node.setdefault(
                node_id,
                {
                    "id": node_id,
                    "type": entity_type,
                    "name": name,
                    "source_path": source_path,
                    "touches": [],
                },
            )
            if timestamp is not None:
                node["touches"].append(
                    {
                        "ts": timestamp,
                        "type": touch_type,
                        "direction": direction,
                        "source": {"id": source},
                        "nature": nature,
                    }
                )
    return list(by_node.values())


def cooling_report(
    vault_root: str | Path,
    *,
    now: datetime | date,
    limit: int = 5,
    people_dir: str | Path | None = None,
    companies_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return cold, consequential entities from a freshly reconciled index."""
    if not isinstance(now, (date, datetime)):
        raise TypeError("now must be a date or datetime")
    if limit < 0:
        raise ValueError("limit must be non-negative")

    root = Path(vault_root)
    index.reconcile(
        root,
        people_dir=people_dir,
        companies_dir=companies_dir,
    )

    cold: list[dict[str, Any]] = []
    counts = defaultdict(int)
    for node in _load_nodes(root):
        touches = node["touches"]
        classification = classify_temperature(
            touches,
            entity_type=node["type"],
            now=now,
        )
        engagement_days = {
            engagement_date
            for touch in touches
            if (engagement_date := _engagement_date(touch)) is not None
        }
        if (
            classification["temperature"] != "cold"
            or len(engagement_days) < 2
            or classification["touch_count"] == 0
        ):
            continue
        counts[node["type"]] += 1
        cold.append(
            {
                "name": node["name"],
                "type": node["type"],
                "page": node["source_path"],
                "days_since_engagement": classification[
                    "days_since_engagement"
                ],
                "last_engagement": classification["last_engagement"],
                "reason": classification["reason"],
            }
        )

    cold.sort(
        key=lambda item: (
            -int(item["days_since_engagement"]),
            str(item["name"]).casefold(),
        )
    )
    person_count = counts["person"]
    company_count = counts["company"]
    return {
        "generated_at": now.isoformat(),
        "counts": {
            "person": person_count,
            "company": company_count,
            "total": person_count + company_count,
        },
        "cold": cold[:limit],
    }


def _count_label(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def format_line(report: Mapping[str, Any]) -> str:
    """Render the compact daily-plan cooling line."""
    cold = report.get("cold")
    counts = report.get("counts")
    if not isinstance(cold, Sequence) or isinstance(cold, (str, bytes)):
        return ""
    if not isinstance(counts, Mapping):
        return ""
    total = int(counts.get("total") or 0)
    if total == 0:
        return ""
    if total > 3:
        people = int(counts.get("person") or 0)
        companies = int(counts.get("company") or 0)
        parts = []
        if people:
            parts.append(_count_label(people, "person", "people"))
        if companies:
            parts.append(_count_label(companies, "account", "accounts"))
        return (
            f"❄️ Going cold: {', '.join(parts)} — "
            'say "who\'s going cold" for the list'
        )

    details = []
    for item in cold[:3]:
        if not isinstance(item, Mapping):
            continue
        entity_label = "account" if item.get("type") == "company" else "person"
        details.append(
            f"{item.get('name')} ({entity_label}, "
            f"{item.get('days_since_engagement')}d)"
        )
    return f"❄️ Going cold: {', '.join(details)}" if details else ""


def _write_feed(vault_root: Path, report: Mapping[str, Any]) -> Path:
    destination = vault_root / _FEED_RELATIVE_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _parse_now(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.entity_engine.cooling",
        description=__doc__,
    )
    parser.add_argument("--now", type=_parse_now)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--format", choices=("json", "line"), default="json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = args.now or datetime.now(timezone.utc)
    report = cooling_report(Path.cwd(), now=now, limit=args.limit)
    _write_feed(Path.cwd(), report)
    if args.format == "line":
        line = format_line(report)
        if line:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
