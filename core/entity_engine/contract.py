"""Pure parsing, rendering, and transformation rules for Dex entity pages."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from core.paths import COMPANIES_DIR, PEOPLE_DIR

PERSON_FIELDS = (
    "type",
    "name",
    "role",
    "company",
    "company_page",
    "emails",
    "aliases",
    "location",
    "last_interaction",
)
COMPANY_FIELDS = ("type", "name", "domains", "website", "status")
CANONICAL_FIELD_ORDER = tuple(dict.fromkeys(PERSON_FIELDS + COMPANY_FIELDS))
CANONICAL_FIELDS = frozenset(CANONICAL_FIELD_ORDER)
RELATIONSHIP_TYPES = (
    "works_at",
    "reports_to",
    "part_of",
    "stakeholder_on",
    "deal_with",
    "related_to",
)
RELATIONSHIP_STATUSES = frozenset({"suggested", "confirmed"})
V2_FIELDS = frozenset(
    {
        "dex_pinned",
        "dex_last_written",
        "dex_dismissed_relationships",
        "last_touched",
        "touches",
        "relationships",
    }
)
_OWNED_FIELD_ORDER = CANONICAL_FIELD_ORDER + ("relationships",)
_OWNED_FIELDS = CANONICAL_FIELDS | {"relationships"}
_LIST_FIELDS = frozenset({"emails", "aliases", "domains"})
_SCALAR_FIELDS = CANONICAL_FIELDS - _LIST_FIELDS
_FIELD_LABELS = {
    "type": "type",
    "name": "name",
    "role": "role",
    "company": "company",
    "company page": "company_page",
    "email": "emails",
    "emails": "emails",
    "aliases": "aliases",
    "location": "location",
    "last interaction": "last_interaction",
    "last interaction date": "last_interaction",
    "website": "website",
    "domain": "domains",
    "domains": "domains",
    "status": "status",
    "stage": "status",
}
_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)^---[ \t]*\r?$(?:\r?\n)?",
    re.MULTILINE | re.DOTALL,
)
_PIPE_ROW_RE = re.compile(
    r"^\s*\|\s*(?:\*\*)?([^|*]+?)(?:\*\*)?\s*\|\s*(.*?)\s*\|\s*$"
)
_INLINE_RE = re.compile(r"^\s*\*\*([^*:\n]+):\*\*\s*(.*?)\s*$")

_REGION_HEADINGS = {
    "recent-interactions": "Recent Interactions",
    "key-contacts": "Key Contacts",
    "meeting-history": "Meeting History",
    "context-summary": "Key Context",
    "related-tasks": "Related Tasks",
    "relationships": "Relationships",
    "update-log": "Update Log",
}
_REGION_ORDER = (
    "recent-interactions",
    "key-contacts",
    "meeting-history",
    "context-summary",
    "related-tasks",
    "relationships",
    "update-log",
    "page-metadata",
)
_ADOPT_EXISTING_SECTION = frozenset(
    {"key-contacts", "meeting-history", "related-tasks"}
)
_LEGACY_PAGE_METADATA_RE = re.compile(
    r"(?m)(?:^\*Created:[^\r\n]*\*[ \t]*\r?\n)?"
    r"^\*Updated:[^\r\n]*\*[ \t]*(?:\r?\n[ \t]*)*\Z"
)


def _empty_result() -> dict[str, Any]:
    return {
        "type": None,
        "name": None,
        "role": None,
        "company": None,
        "company_page": None,
        "emails": [],
        "aliases": [],
        "location": None,
        "last_interaction": None,
        "domains": [],
        "website": None,
        "status": None,
        "touches": [],
        "last_touched": None,
        "quarantined": False,
        "source_formats": [],
    }


def _normalise_scalar(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    text = str(value).strip()
    return text or None


def _normalise_list(value: Any, *, lowercase: bool = False) -> list[str] | None:
    if value is None:
        return None
    values = value if isinstance(value, list) else str(value).split(",")
    result = []
    for item in values:
        scalar = _normalise_scalar(item)
        if scalar:
            result.append(scalar.lower() if lowercase else scalar)
    return result


def _normalise_field(key: str, value: Any) -> Any:
    if key in _LIST_FIELDS:
        return _normalise_list(value, lowercase=key in {"emails", "domains"})
    value = _normalise_scalar(value)
    if key == "type":
        return value if value in {"person", "company"} else None
    if key == "location":
        return value if value in {"internal", "external", "unknown"} else None
    if key == "last_interaction" and value and not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", value
    ):
        return None
    return value


def _relationship_error(message: str, *, strict: bool) -> None:
    if strict:
        raise ValueError(message)


def fold(value: Any) -> str:
    """Return the canonical comparison identity for user-visible text."""
    return unicodedata.normalize("NFC", str(value)).casefold()


def relationship_edge_key(relationship: Mapping[str, Any]) -> str:
    """Derive the stable identity for one relationship entry."""
    return f"{relationship['type']}::{fold(relationship['target'])}"


def _normalise_dismissed_relationships(
    value: Any,
    *,
    strict: bool = False,
) -> list[dict[str, str]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        _relationship_error(
            "dex_dismissed_relationships must be a list",
            strict=strict,
        )
        return None
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, Mapping):
            _relationship_error(
                "dismissed relationship entries must be objects",
                strict=strict,
            )
            continue
        raw_key = _normalise_scalar(entry.get("key"))
        dismissed_date = _normalise_scalar(entry.get("date"))
        if raw_key is None or "::" not in raw_key:
            _relationship_error(
                "dismissed relationship key must be an edge key",
                strict=strict,
            )
            continue
        relation_type, target = raw_key.split("::", 1)
        if relation_type not in RELATIONSHIP_TYPES or not target:
            _relationship_error(
                f"invalid dismissed relationship key: {raw_key}",
                strict=strict,
            )
            continue
        if dismissed_date is None or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}",
            dismissed_date,
        ):
            _relationship_error(
                "dismissed relationship date must be YYYY-MM-DD",
                strict=strict,
            )
            continue
        key = f"{relation_type}::{fold(target)}"
        if key not in seen:
            seen.add(key)
            result.append({"key": key, "date": dismissed_date})
    return result


def _normalise_relationships(
    value: Any,
    *,
    strict: bool = False,
) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        _relationship_error("relationships must be a list", strict=strict)
        return None

    result: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            _relationship_error(
                "relationship entries must be objects",
                strict=strict,
            )
            continue
        relation_type = _normalise_scalar(entry.get("type"))
        if relation_type not in RELATIONSHIP_TYPES:
            _relationship_error(
                f"unknown relationship type: {relation_type or '<missing>'}",
                strict=strict,
            )
            continue
        target = _normalise_scalar(entry.get("target"))
        if target is None:
            _relationship_error(
                "relationship target must be a non-empty string",
                strict=strict,
            )
            continue
        status = _normalise_scalar(entry.get("status"))
        if status not in RELATIONSHIP_STATUSES:
            _relationship_error(
                f"invalid relationship status: {status or '<missing>'}",
                strict=strict,
            )
            continue
        source = entry.get("source")
        if not isinstance(source, Mapping):
            _relationship_error(
                "relationship source must be an object",
                strict=strict,
            )
            continue
        source_kind = _normalise_scalar(source.get("kind"))
        source_id = _normalise_scalar(source.get("id"))
        if source_kind is None or source_id is None:
            _relationship_error(
                "relationship source requires kind and id",
                strict=strict,
            )
            continue
        relationship_date = _normalise_scalar(entry.get("date"))
        if relationship_date is None or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}",
            relationship_date,
        ):
            _relationship_error(
                "relationship date must be YYYY-MM-DD",
                strict=strict,
            )
            continue
        result.append(
            {
                "type": relation_type,
                "target": target,
                "status": status,
                "source": _yaml_safe(dict(source)),
                "date": relationship_date,
            }
        )
    return result


def _normalise_owned_field(
    key: str,
    value: Any,
    *,
    strict: bool = False,
) -> Any:
    if key == "relationships":
        return _normalise_relationships(value, strict=strict)
    return _normalise_field(key, value)


def _normalise_v2_field(key: str, value: Any) -> Any:
    if key in {"dex_pinned", "dex_last_written"}:
        return dict(value) if isinstance(value, dict) else None
    if key == "touches":
        return _yaml_safe(value) if isinstance(value, list) else None
    if key == "relationships":
        return _normalise_relationships(value)
    if key == "dex_dismissed_relationships":
        return _normalise_dismissed_relationships(value)
    return _normalise_scalar(value)


def _legacy_fields(
    body: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    pipe: dict[str, Any] = {}
    inline: dict[str, Any] = {}
    formats: list[str] = []
    for raw_line in body.splitlines():
        match = _PIPE_ROW_RE.match(raw_line)
        if match:
            label = re.sub(r"\s+", " ", match.group(1)).strip().lower().rstrip(":")
            field = _FIELD_LABELS.get(label)
            if field and match.group(2).strip() and field not in pipe:
                pipe[field] = match.group(2).strip()
                if "pipe_table" not in formats:
                    formats.append("pipe_table")
            continue
        match = _INLINE_RE.match(raw_line)
        if match:
            label = re.sub(r"\s+", " ", match.group(1)).strip().lower()
            field = _FIELD_LABELS.get(label)
            if field and match.group(2).strip() and field not in inline:
                inline[field] = match.group(2).strip()
                if "inline_bold" not in formats:
                    formats.append("inline_bold")
    return pipe, inline, formats


def _split_frontmatter(
    text: str,
) -> tuple[dict[str, Any] | None, str, bool, bool]:
    if not text.startswith("---"):
        return None, text, False, False
    match = _FRONTMATTER_RE.match(text)
    if not match:
        body_start = text.find("\n")
        return (
            None,
            text[body_start + 1 :] if body_start >= 0 else "",
            True,
            True,
        )
    body = text[match.end() :]
    try:
        loaded = yaml.safe_load(match.group(1))
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise yaml.YAMLError("frontmatter must be a mapping")
        return loaded, body, True, False
    except yaml.YAMLError:
        return None, body, True, True


def _infer_type(path: Path, values: dict[str, Any]) -> str | None:
    if values.get("type") in {"person", "company"}:
        return values["type"]
    try:
        path.resolve().relative_to(PEOPLE_DIR.resolve())
        return "person"
    except ValueError:
        pass
    try:
        path.resolve().relative_to(COMPANIES_DIR.resolve())
        return "company"
    except ValueError:
        pass
    if any(
        values.get(key)
        for key in ("role", "company", "company_page", "emails", "last_interaction")
    ):
        return "person"
    if any(values.get(key) for key in ("domains", "website", "status")):
        return "company"
    return None


def parse_entity_page(path: str | Path) -> dict[str, Any]:
    """Parse a page using frontmatter, pipe-table, then inline-bold precedence."""
    page_path = Path(path)
    text = page_path.read_text(encoding="utf-8-sig")
    frontmatter, body, had_frontmatter, quarantined = _split_frontmatter(text)
    pipe, inline, legacy_formats = _legacy_fields(body)
    result = _empty_result()
    result["quarantined"] = quarantined
    if had_frontmatter:
        result["source_formats"].append("frontmatter")
    result["source_formats"].extend(legacy_formats)

    for key in CANONICAL_FIELDS:
        candidates = []
        if frontmatter is not None and key in frontmatter:
            candidates.append(frontmatter[key])
        if key in pipe:
            candidates.append(pipe[key])
        if key in inline:
            candidates.append(inline[key])
        for candidate in candidates:
            value = _normalise_field(key, candidate)
            if value is not None:
                result[key] = value
                break

    if frontmatter is not None and not quarantined:
        touches = _normalise_v2_field("touches", frontmatter.get("touches"))
        last_touched = _normalise_v2_field(
            "last_touched", frontmatter.get("last_touched")
        )
        if touches is not None:
            result["touches"] = touches
        if last_touched is not None:
            result["last_touched"] = last_touched
        relationships = _normalise_v2_field(
            "relationships",
            frontmatter.get("relationships"),
        )
        if relationships is not None:
            result["relationships"] = relationships

    result["type"] = _infer_type(page_path, result)
    if result["type"] and not result["name"]:
        heading = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
        result["name"] = (
            heading.group(1).strip()
            if heading
            else page_path.stem.replace("_", " ")
        )
    return result


def _yaml_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, dict):
        return {key: _yaml_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_yaml_safe(item) for item in value]
    return value


def merge_frontmatter_text(
    page_path: Path,
    original: str,
    fields: Mapping[str, Any],
    *,
    relationship_removed_keys: Iterable[str] = (),
) -> str | None:
    """Return pin-aware merged text, or ``None`` for quarantined frontmatter."""
    parsed, body, _had_frontmatter, quarantined = _split_frontmatter(original)
    if quarantined:
        return None
    merged = dict(parsed or {})

    had_pins = isinstance(merged.get("dex_pinned"), dict)
    had_last_written = isinstance(merged.get("dex_last_written"), dict)
    pinned = dict(merged["dex_pinned"]) if had_pins else {}
    last_written = (
        dict(merged["dex_last_written"]) if had_last_written else {}
    )
    ownership_enabled = (
        had_pins
        or had_last_written
        or any(key in fields for key in V2_FIELDS)
    )
    relationship_write = "relationships" in fields
    migrate_pinned_relationships = (
        relationship_write
        and _normalise_scalar(pinned.get("relationships")) == "user"
    )
    if relationship_write:
        pinned.pop("relationships", None)

    supplied_pins = _normalise_v2_field(
        "dex_pinned", fields.get("dex_pinned")
    )
    if supplied_pins is not None:
        pinned.update(
            (key, value)
            for key, value in supplied_pins.items()
            if (
                key in _OWNED_FIELDS
                and key != "relationships"
                and _normalise_scalar(value)
            )
        )
    supplied_last_written = _normalise_v2_field(
        "dex_last_written", fields.get("dex_last_written")
    )
    if supplied_last_written is not None:
        for key, value in supplied_last_written.items():
            if key not in _OWNED_FIELDS:
                continue
            normalised = _normalise_owned_field(key, value, strict=True)
            if normalised is not None or (
                value is None and key in _SCALAR_FIELDS
            ):
                last_written[key] = normalised

    pipe, inline, _formats = _legacy_fields(body)

    def explicit_current_value(key: str) -> Any:
        candidates = []
        if parsed is not None and key in parsed:
            candidates.append(parsed[key])
        if key in pipe:
            candidates.append(pipe[key])
        if key in inline:
            candidates.append(inline[key])
        for candidate in candidates:
            normalised = _normalise_field(key, candidate)
            if normalised is not None or (
                candidate is None and key in _SCALAR_FIELDS
            ):
                return normalised
        return [] if key in _LIST_FIELDS else None

    effective_current = {
        key: explicit_current_value(key) for key in CANONICAL_FIELD_ORDER
    }
    effective_current["relationships"] = (
        _normalise_relationships(
            parsed.get("relationships") if parsed is not None else None
        )
        or []
    )
    effective_current["type"] = _infer_type(page_path, effective_current)
    if effective_current["type"] and not effective_current["name"]:
        heading = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
        effective_current["name"] = (
            heading.group(1).strip()
            if heading
            else page_path.stem.replace("_", " ")
        )

    def has_nonempty_raw_value(key: str) -> bool:
        candidates = []
        if parsed is not None and key in parsed:
            candidates.append(parsed[key])
        if key in pipe:
            candidates.append(pipe[key])
        if key in inline:
            candidates.append(inline[key])
        for candidate in candidates:
            if candidate is None:
                continue
            if isinstance(candidate, str) and not candidate.strip():
                continue
            if isinstance(candidate, (dict, list)) and not candidate:
                continue
            return True
        return False

    implicit_bootstrap = (
        ownership_enabled
        and not had_pins
        and not had_last_written
        and supplied_last_written is None
    )
    if implicit_bootstrap:
        for key in _OWNED_FIELD_ORDER:
            if key == "relationships":
                continue
            if has_nonempty_raw_value(key):
                pinned.setdefault(key, "user")

    for key, previous in last_written.items():
        if key not in _OWNED_FIELDS or key == "relationships" or key in pinned:
            continue
        normalised_previous = _normalise_owned_field(key, previous)
        if normalised_previous is None and not (
            previous is None and key in _SCALAR_FIELDS
        ):
            continue
        if effective_current[key] != normalised_previous:
            pinned[key] = "user"

    if relationship_write:
        current = effective_current["relationships"]
        if migrate_pinned_relationships:
            current = [
                {**relationship, "status": "confirmed"}
                for relationship in current
            ]
        incoming = _normalise_relationships(
            fields["relationships"],
            strict=True,
        )
        assert incoming is not None
        previous_raw = last_written.get("relationships")
        previous = _normalise_relationships(previous_raw)
        reliable_snapshot = (
            "relationships" in last_written and previous is not None
        )
        dismissed = (
            _normalise_dismissed_relationships(
                merged.get("dex_dismissed_relationships")
            )
            or []
        )
        supplied_dismissed = _normalise_dismissed_relationships(
            fields.get("dex_dismissed_relationships"),
            strict="dex_dismissed_relationships" in fields,
        )
        if supplied_dismissed is not None:
            dismissed = supplied_dismissed
        dismissed_by_key = {entry["key"]: entry for entry in dismissed}
        explained_removals = {str(key) for key in relationship_removed_keys}
        current_by_key = {
            relationship_edge_key(relationship): relationship
            for relationship in current
        }
        incoming_by_key: dict[str, dict[str, Any]] = {}
        for relationship in incoming:
            incoming_by_key.setdefault(
                relationship_edge_key(relationship),
                relationship,
            )

        if reliable_snapshot:
            assert previous is not None
            for relationship in previous:
                key = relationship_edge_key(relationship)
                if (
                    key not in current_by_key
                    and key not in explained_removals
                    and key not in dismissed_by_key
                ):
                    dismissed_by_key[key] = {
                        "key": key,
                        "date": date.today().isoformat(),
                    }

        proposed: list[dict[str, Any]] = []
        proposed_keys: set[str] = set()

        def append(relationship: dict[str, Any]) -> None:
            key = relationship_edge_key(relationship)
            if key in proposed_keys:
                return
            proposed_keys.add(key)
            proposed.append(relationship)

        if not reliable_snapshot:
            for relationship in current:
                key = relationship_edge_key(relationship)
                if relationship["status"] == "confirmed" or (
                    key not in dismissed_by_key
                ):
                    append(relationship)
        else:
            for relationship in current:
                key = relationship_edge_key(relationship)
                if relationship["status"] == "confirmed" and not (
                    key in explained_removals and key not in incoming_by_key
                ):
                    append(relationship)
                elif key in incoming_by_key and key not in dismissed_by_key:
                    append(incoming_by_key[key])

        for relationship in incoming:
            key = relationship_edge_key(relationship)
            if key in dismissed_by_key or key in proposed_keys:
                continue
            append(relationship)

        merged["relationships"] = proposed
        last_written["relationships"] = proposed
        if dismissed_by_key:
            merged["dex_dismissed_relationships"] = list(
                dismissed_by_key.values()
            )
        else:
            merged.pop("dex_dismissed_relationships", None)

    for key, value in fields.items():
        if key in {"relationships", "dex_dismissed_relationships"}:
            continue
        if key not in _OWNED_FIELDS or key in pinned:
            continue
        if value is None and key in _SCALAR_FIELDS:
            merged[key] = None
            if ownership_enabled:
                last_written[key] = None
            continue
        normalised = _normalise_owned_field(key, value, strict=True)
        if normalised is not None:
            merged[key] = normalised
            if ownership_enabled:
                last_written[key] = normalised

    for key in ("last_touched", "touches"):
        if key not in fields:
            continue
        normalised = _normalise_v2_field(key, fields[key])
        if normalised is not None:
            merged[key] = normalised
    if ownership_enabled:
        merged["dex_pinned"] = pinned
        merged["dex_last_written"] = last_written

    dumped = yaml.safe_dump(
        _yaml_safe(merged),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    return f"---\n{dumped}\n---\n{body}"


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _string_list(
    values: list[str] | None,
    *,
    lowercase: bool = False,
) -> str:
    clean = _normalise_list(values or [], lowercase=lowercase) or []
    return "[" + ", ".join(_quoted(value) for value in clean) + "]"


def render_person_page(
    name: str,
    role: str | None = None,
    company: str | None = None,
    emails: list[str] | None = None,
    aliases: list[str] | None = None,
    location: str = "unknown",
    notes: str | None = None,
) -> str:
    """Render a canonical person page."""
    clean_emails = _string_list(emails, lowercase=True)
    clean_aliases = _string_list(aliases)
    clean_location = (
        location
        if location in {"internal", "external", "unknown"}
        else "unknown"
    )
    fields = [
        "---",
        "type: person",
        f"name: {_quoted(name)}",
        f"role: {_quoted(role) if role else 'null'}",
        f"company: {_quoted(company) if company else 'null'}",
        "company_page: null",
        f"emails: {clean_emails}",
        f"aliases: {clean_aliases}",
        f"location: {clean_location}",
        "last_interaction: null",
        "dex_pinned: {}",
        "dex_last_written:",
        "  type: person",
        f"  name: {_quoted(name)}",
        f"  role: {_quoted(role) if role else 'null'}",
        f"  company: {_quoted(company) if company else 'null'}",
        "  company_page: null",
        f"  emails: {clean_emails}",
        f"  aliases: {clean_aliases}",
        f"  location: {clean_location}",
        "  last_interaction: null",
        "---",
        f"# {name}",
        "",
        "## Notes",
        "",
    ]
    if notes:
        fields.extend([notes, ""])
    fields.extend(
        [
            "## Recent Interactions",
            "",
            "<!-- dex:auto:recent-interactions -->",
            "<!-- /dex:auto -->",
            "",
            "## Key Context",
            "",
            "## Relationships",
            "",
            "<!-- dex:auto:relationships -->",
            "<!-- /dex:auto -->",
            "",
            "## Update Log",
            "",
            "<!-- dex:auto:update-log -->",
            "<!-- /dex:auto -->",
        ]
    )
    return "\n".join(fields) + "\n"


def render_company_page(
    name: str,
    domains: list[str] | None = None,
    website: str | None = None,
    status: str = "Prospect",
) -> str:
    """Render a canonical company page."""
    clean_domains = _string_list(domains, lowercase=True)
    return "\n".join(
        [
            "---",
            "type: company",
            f"name: {_quoted(name)}",
            f"domains: {clean_domains}",
            f"website: {_quoted(website) if website else 'null'}",
            f"status: {_quoted(status)}",
            "dex_pinned: {}",
            "dex_last_written:",
            "  type: company",
            f"  name: {_quoted(name)}",
            f"  domains: {clean_domains}",
            f"  website: {_quoted(website) if website else 'null'}",
            f"  status: {_quoted(status)}",
            "---",
            f"# {name}",
            "",
            "## Key Contacts",
            "",
            "<!-- dex:auto:key-contacts -->",
            "<!-- /dex:auto -->",
            "",
            "## Meeting History",
            "",
            "<!-- dex:auto:meeting-history -->",
            "<!-- /dex:auto -->",
            "",
            "## Notes",
            "",
            "## Relationships",
            "",
            "<!-- dex:auto:relationships -->",
            "<!-- /dex:auto -->",
            "",
            "## Update Log",
            "",
            "<!-- dex:auto:update-log -->",
            "<!-- /dex:auto -->",
            "",
        ]
    )


def _region_markers(slug: str) -> tuple[str, str]:
    return f"<!-- dex:auto:{slug} -->", "<!-- /dex:auto -->"


def _region_bounds(text: str, slug: str) -> tuple[int, int] | None:
    start, end = _region_markers(slug)
    start_index = text.find(start)
    if start_index < 0:
        return None
    end_index = text.find(end, start_index + len(start))
    if end_index < 0:
        raise ValueError(f"machine region has no closing marker: {slug}")
    return start_index, end_index + len(end)


def replace_machine_region(text: str, slug: str, new_content: str) -> str:
    """Replace one named machine-owned region, preserving its markers."""
    start, end = _region_markers(slug)
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(text):
        raise ValueError(f"machine region not found: {slug}")
    content = new_content.strip("\r\n")
    replacement = (
        f"{start}\n{content}\n{end}" if content else f"{start}\n{end}"
    )
    return pattern.sub(lambda _match: replacement, text, count=1)


def _region_rank(slug: str) -> int:
    try:
        return _REGION_ORDER.index(slug)
    except ValueError:
        return len(_REGION_ORDER)


def ensure_region(text: str, slug: str) -> str:
    """Idempotently add one managed region without disturbing user text."""
    if _region_bounds(text, slug) is not None:
        return text

    start, end = _region_markers(slug)
    if slug == "page-metadata":
        metadata_match = _LEGACY_PAGE_METADATA_RE.search(text)
        if metadata_match:
            existing = metadata_match.group(0).strip("\r\n")
            prefix = text[: metadata_match.start()].rstrip("\r\n")
            return f"{prefix}\n\n{start}\n{existing}\n{end}\n"
        prefix = text.rstrip("\r\n")
        return f"{prefix}\n\n{start}\n{end}\n" if prefix else f"{start}\n{end}\n"

    heading = _REGION_HEADINGS.get(slug, slug.replace("-", " ").title())
    heading_pattern = re.compile(
        rf"^##[ \t]+{re.escape(heading)}[ \t]*$",
        re.MULTILINE,
    )
    heading_match = heading_pattern.search(text)
    if heading_match:
        if slug not in _ADOPT_EXISTING_SECTION:
            prefix = text[: heading_match.end()].rstrip("\r\n")
            suffix = text[heading_match.end() :].lstrip("\r\n")
            managed = f"{start}\n{end}"
            return (
                f"{prefix}\n\n{managed}\n\n{suffix}"
                if suffix
                else f"{prefix}\n\n{managed}\n"
            )
        next_heading = re.search(
            r"^##[ \t]+.+$",
            text[heading_match.end() :],
            re.MULTILINE,
        )
        section_end = (
            heading_match.end() + next_heading.start()
            if next_heading
            else len(text)
        )
        existing = text[heading_match.end() : section_end].strip("\r\n")
        managed = f"{start}\n{existing}\n{end}" if existing else f"{start}\n{end}"
        prefix = text[: heading_match.end()].rstrip("\r\n")
        suffix = text[section_end:].lstrip("\r\n")
        return (
            f"{prefix}\n\n{managed}\n\n{suffix}"
            if suffix
            else f"{prefix}\n\n{managed}\n"
        )

    section = f"## {heading}\n\n{start}\n{end}"
    insertion_points = []
    rank = _region_rank(slug)
    for later_slug in _REGION_ORDER:
        if _region_rank(later_slug) <= rank:
            continue
        later_heading = _REGION_HEADINGS.get(later_slug)
        if later_heading is None:
            continue
        match = re.search(
            rf"^##[ \t]+{re.escape(later_heading)}[ \t]*$",
            text,
            re.MULTILINE,
        )
        if match:
            insertion_points.append(match.start())
    if insertion_points:
        insertion = min(insertion_points)
        prefix = text[:insertion].rstrip("\r\n")
        suffix = text[insertion:].lstrip("\r\n")
        return f"{prefix}\n\n{section}\n\n{suffix}"
    prefix = text.rstrip("\r\n")
    return f"{prefix}\n\n{section}\n" if prefix else f"{section}\n"


def ordered_region_slugs(slugs: Iterable[str]) -> tuple[str, ...]:
    """Deduplicate region slugs and return their canonical application order."""
    return tuple(sorted(set(slugs), key=lambda slug: (_region_rank(slug), slug)))


def _display_scalar(value: Any) -> str | None:
    scalar = _normalise_scalar(value)
    if scalar is None:
        return None
    return re.sub(r"\s+", " ", scalar)


def render_relationships(
    relationships: Iterable[Mapping[str, Any]] | None,
) -> str:
    """Render deterministic grouped relationship rows without doing I/O."""
    normalised = _normalise_relationships(
        list(relationships or ()),
        strict=True,
    )
    assert normalised is not None
    type_rank = {
        relation_type: index
        for index, relation_type in enumerate(RELATIONSHIP_TYPES)
    }
    normalised.sort(
        key=lambda relationship: (
            type_rank[relationship["type"]],
            fold(relationship["target"]),
            relationship["target"],
            relationship["status"],
            relationship["date"],
            json.dumps(
                relationship["source"],
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    )

    groups: list[str] = []
    for relation_type in RELATIONSHIP_TYPES:
        rows = [
            relationship
            for relationship in normalised
            if relationship["type"] == relation_type
        ]
        if not rows:
            continue
        lines = [f"### {relation_type}"]
        for relationship in rows:
            suffix = (
                " (suggested)"
                if relationship["status"] == "suggested"
                else ""
            )
            lines.append(f"- {relationship['target']}{suffix}")
        groups.append("\n".join(lines))
    return "\n\n".join(groups)


def _source_label(value: Any) -> str | None:
    if isinstance(value, Mapping):
        title = _display_scalar(value.get("title") or value.get("name"))
        source_id = _display_scalar(value.get("id"))
        if title and source_id:
            return f"{title} [{source_id}]"
        return title or (f"[{source_id}]" if source_id else None)
    return _display_scalar(value)


def _direction_label(value: Any, touch_type: str) -> str | None:
    direction = _display_scalar(value)
    if touch_type == "mention":
        return "mention"
    if touch_type == "meeting" and direction == "none":
        return "two-way"
    return {"in": "inbound", "out": "outbound", "none": "none"}.get(
        direction or ""
    )


def render_update_log(
    *,
    touches: Iterable[Mapping[str, Any]] | None = None,
    relationship_provenance: Iterable[Mapping[str, Any]] | None = None,
    creation_metadata: Mapping[str, Any] | None = None,
) -> str:
    """Render the sole deterministic update-log projection from Markdown facts."""
    entries: list[tuple[str, str]] = []

    if creation_metadata:
        timestamp = _display_scalar(
            creation_metadata.get("created_at") or creation_metadata.get("ts")
        )
        source = _source_label(creation_metadata.get("source"))
        if timestamp:
            line = f"- {timestamp[:10]} — created"
            if source:
                line += f" — {source}"
            entries.append((timestamp, line))

    for relationship in relationship_provenance or ():
        timestamp = _display_scalar(
            relationship.get("recorded_at")
            or relationship.get("ts")
            or relationship.get("date")
        )
        relation_type = _display_scalar(relationship.get("type"))
        target = _display_scalar(
            relationship.get("target")
            or relationship.get("target_path")
            or relationship.get("target_ref")
        )
        if not timestamp or not relation_type or not target:
            continue
        line = (
            f"- {timestamp[:10]} — relationship · {relation_type} — {target}"
        )
        source = _source_label(relationship.get("source"))
        if source:
            line += f" — {source}"
        entries.append((timestamp, line))

    for touch in touches or ():
        timestamp = _display_scalar(touch.get("ts"))
        touch_type = _display_scalar(touch.get("type"))
        source = _source_label(touch.get("source"))
        if not timestamp or not touch_type or not source:
            continue
        direction = _direction_label(touch.get("direction"), touch_type)
        line = f"- {timestamp[:10]} — {touch_type}"
        if direction:
            line += f" · {direction}"
        line += f" — {source}"
        nature = _display_scalar(touch.get("nature"))
        if nature:
            line += f" — {nature}"
        entries.append((timestamp, line))

    entries.sort(key=lambda entry: (entry[0], entry[1]))
    return "\n".join(line for _timestamp, line in entries)
