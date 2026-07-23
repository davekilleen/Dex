"""Canonical Python authority for Dex person and company Markdown pages."""

from .contract import (
    CANONICAL_FIELD_ORDER,
    CANONICAL_FIELDS,
    COMPANY_FIELDS,
    PERSON_FIELDS,
    V2_FIELDS,
    ensure_region,
    parse_entity_page,
    render_company_page,
    render_person_page,
    render_update_log,
    replace_machine_region,
)
from .write import (
    Result,
    create_page_if_absent,
    fingerprint_page,
    mutate_page,
    replace_machine_region_in_file,
    upsert_frontmatter,
)

__all__ = [
    "CANONICAL_FIELD_ORDER",
    "CANONICAL_FIELDS",
    "COMPANY_FIELDS",
    "PERSON_FIELDS",
    "V2_FIELDS",
    "Result",
    "create_page_if_absent",
    "ensure_region",
    "fingerprint_page",
    "mutate_page",
    "parse_entity_page",
    "render_company_page",
    "render_person_page",
    "render_update_log",
    "replace_machine_region",
    "replace_machine_region_in_file",
    "upsert_frontmatter",
]
