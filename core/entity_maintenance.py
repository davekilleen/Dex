"""Maintenance commands for canonical entity page metadata."""

from __future__ import annotations

import argparse
from pathlib import Path

from core.paths import COMPANIES_DIR, PEOPLE_DIR
from core.utils.entity_pages import parse_entity_page, upsert_frontmatter


def _fields_for(page: Path, entity_type: str) -> tuple[dict, bool]:
    parsed = parse_entity_page(page)
    if parsed["quarantined"]:
        return {}, True
    if entity_type == "person":
        keys = (
            "name",
            "role",
            "company",
            "company_page",
            "emails",
            "aliases",
            "location",
            "last_interaction",
        )
        fields = {key: parsed[key] for key in keys}
        fields["name"] = fields["name"] or page.stem.replace("_", " ")
        fields["location"] = fields["location"] or "unknown"
    else:
        keys = ("name", "domains", "website", "status")
        fields = {key: parsed[key] for key in keys}
        fields["name"] = fields["name"] or page.stem.replace("_", " ").replace("-", " ")
    fields["type"] = entity_type
    return fields, False


def normalize(*, dry_run: bool = False) -> dict[str, int]:
    """Add canonical frontmatter to all non-quarantined entity pages."""
    counts = {"scanned": 0, "updated": 0, "unchanged": 0, "quarantined": 0, "skipped": 0}
    for directory, entity_type in ((PEOPLE_DIR, "person"), (COMPANIES_DIR, "company")):
        if not directory.exists():
            continue
        for page in directory.rglob("*.md"):
            if page.name.lower() == "readme.md":
                counts["skipped"] += 1
                continue
            counts["scanned"] += 1
            fields, quarantined = _fields_for(page, entity_type)
            if quarantined:
                counts["quarantined"] += 1
            elif dry_run:
                needs_update = upsert_frontmatter(page, fields, dry_run=True)
                counts["updated" if needs_update else "unchanged"] += 1
            elif upsert_frontmatter(page, fields):
                counts["updated"] += 1
            else:
                counts["unchanged"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.entity_maintenance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    normalize_parser = subparsers.add_parser("normalize")
    normalize_parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    counts = normalize(dry_run=args.dry_run)
    label = "dry-run" if args.dry_run else "normalize"
    print(f"{label}: " + " ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
