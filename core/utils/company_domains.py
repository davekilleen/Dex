"""Shared company-domain normalization helpers."""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
FREEMAIL_DOMAINS = frozenset(json.loads((DATA_DIR / "freemail_domains.json").read_text()))
MULTI_PART_TLDS = frozenset(json.loads((DATA_DIR / "multi_part_tlds.json").read_text()))


def _normalise(domain: object) -> str:
    return str(domain or "").strip().lower().lstrip("@").rstrip(".")


def registrable_domain(domain: object) -> str:
    """Return the registrable portion of a hostname."""
    labels = [label for label in _normalise(domain).split(".") if label]
    if len(labels) < 2:
        return ".".join(labels)
    suffix = ".".join(labels[-2:])
    return ".".join(labels[-3:]) if suffix in MULTI_PART_TLDS and len(labels) >= 3 else suffix


def is_freemail(domain: object) -> bool:
    """Return whether a hostname belongs to a consumer mail provider."""
    return registrable_domain(domain) in FREEMAIL_DOMAINS


def company_name_from_domain(domain: object) -> str:
    """Derive a readable company name from a registrable domain."""
    registrable = registrable_domain(domain)
    label = registrable.split(".", 1)[0] if registrable else ""
    return " ".join(part.capitalize() for part in label.replace("_", "-").split("-") if part)
