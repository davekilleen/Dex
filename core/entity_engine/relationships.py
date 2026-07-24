"""Read-only proposal feed for typed entity relationships.

The feed is a disposable projection of entity-page frontmatter. Files remain
truth, and only relationships whose status is ``suggested`` are surfaced.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import paths

from .contract import parse_entity_page


def _path_for_root(configured: Path, vault_root: Path) -> Path:
    return vault_root / configured.relative_to(paths.VAULT_ROOT)


def _entity_pages(vault_root: Path) -> list[Path]:
    directories = (
        _path_for_root(paths.PEOPLE_DIR, vault_root),
        _path_for_root(paths.COMPANIES_DIR, vault_root),
    )
    return sorted(
        (
            page
            for directory in directories
            if directory.is_dir()
            for page in directory.rglob("*.md")
            if page.is_file()
        ),
        key=lambda page: page.relative_to(vault_root).as_posix(),
    )


def relationships_report(
    vault_root: str | Path,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Project suggested relationships from entity pages into the feed schema."""
    if not isinstance(now, datetime):
        raise TypeError("now must be a datetime")

    root = Path(vault_root)
    suggestions: list[dict[str, Any]] = []
    for page in _entity_pages(root):
        parsed = parse_entity_page(page)
        if parsed.get("quarantined"):
            continue
        for relationship in parsed.get("relationships") or ():
            if relationship.get("status") != "suggested":
                continue
            relationship_date = str(relationship["date"])
            source = relationship["source"]
            suggestions.append(
                {
                    "src_ref": f"[[{parsed['name']}]]",
                    "src_path": page.relative_to(root).as_posix(),
                    "type": relationship["type"],
                    "target_ref": relationship["target"],
                    "source": {
                        "kind": source["kind"],
                        "id": source["id"],
                        "date": relationship_date,
                    },
                    "first_seen": relationship_date,
                }
            )

    suggestions.sort(
        key=lambda item: (
            str(item["src_path"]).casefold(),
            str(item["type"]),
            str(item["target_ref"]).casefold(),
            str(item["source"]["date"]),
            str(item["source"]["id"]),
        )
    )
    return {
        "schema": 1,
        "generated_at": now.isoformat(),
        "suggestions": suggestions,
    }


def _display_ref(value: Any) -> str:
    ref = str(value or "").strip()
    if ref.startswith("[[") and ref.endswith("]]"):
        ref = ref[2:-2].split("|", 1)[-1]
    return ref.replace("_", " ")


def format_line(report: Mapping[str, Any]) -> str:
    """Render the compact daily-plan relationships line."""
    suggestions = report.get("suggestions")
    if not isinstance(suggestions, Sequence) or isinstance(
        suggestions,
        (str, bytes),
    ):
        return ""
    if not suggestions:
        return ""
    if len(suggestions) > 3:
        return (
            f"🔗 Relationships to confirm: {len(suggestions)} suggestions — "
            'say "relationship radar" to review'
        )

    details = []
    for suggestion in suggestions[:3]:
        if not isinstance(suggestion, Mapping):
            continue
        src_ref = _display_ref(suggestion.get("src_ref"))
        target_ref = _display_ref(suggestion.get("target_ref"))
        relation_type = str(suggestion.get("type") or "").strip()
        if src_ref and target_ref and relation_type:
            details.append(f"{src_ref} → {target_ref} ({relation_type})")
    return (
        f"🔗 Relationships to confirm: {', '.join(details)}"
        if details
        else ""
    )


def _write_feed(vault_root: Path, report: Mapping[str, Any]) -> Path:
    destination = _path_for_root(paths.DEX_RUNTIME_DIR, vault_root)
    destination /= "entity-relationships.json"
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
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.entity_engine.relationships",
        description=__doc__,
    )
    parser.add_argument("--now", type=_parse_now)
    parser.add_argument("--format", choices=("json", "line"), default="json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    now = args.now or datetime.now(timezone.utc)
    report = relationships_report(Path.cwd(), now=now)
    _write_feed(Path.cwd(), report)
    if args.format == "line":
        line = format_line(report)
        if line:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
