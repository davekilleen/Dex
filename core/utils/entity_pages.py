"""Shared parsing and rendering for Dex person and company pages."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

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
CANONICAL_FIELDS = frozenset(PERSON_FIELDS + COMPANY_FIELDS)
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
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)^---[ \t]*\r?$(?:\r?\n)?", re.MULTILINE | re.DOTALL)
_PIPE_ROW_RE = re.compile(r"^\s*\|\s*(?:\*\*)?([^|*]+?)(?:\*\*)?\s*\|\s*(.*?)\s*\|\s*$")
_INLINE_RE = re.compile(r"^\s*\*\*([^*:\n]+):\*\*\s*(.*?)\s*$")


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
    if key == "last_interaction" and value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    return value


def _legacy_fields(body: str) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
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


def _split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str, bool, bool]:
    if not text.startswith("---"):
        return None, text, False, False
    match = _FRONTMATTER_RE.match(text)
    if not match:
        body_start = text.find("\n")
        return None, text[body_start + 1 :] if body_start >= 0 else "", True, True
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
    if any(values.get(key) for key in ("role", "company", "company_page", "emails", "last_interaction")):
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

    result["type"] = _infer_type(page_path, result)
    if result["type"] and not result["name"]:
        heading = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
        result["name"] = heading.group(1).strip() if heading else page_path.stem.replace("_", " ")
    return result


def _yaml_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, dict):
        return {key: _yaml_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_yaml_safe(item) for item in value]
    return value


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        if existing_mode is not None:
            os.chmod(temp_name, existing_mode)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def upsert_frontmatter(path: str | Path, fields: dict[str, Any], *, dry_run: bool = False) -> bool:
    """Merge canonical fields into frontmatter while preserving unknown keys."""
    page_path = Path(path)
    original = page_path.read_text(encoding="utf-8-sig")
    parsed, body, _had_frontmatter, quarantined = _split_frontmatter(original)
    if quarantined:
        return False
    merged = dict(parsed or {})
    for key, value in fields.items():
        if key in CANONICAL_FIELDS:
            if value is None and key in _SCALAR_FIELDS:
                merged[key] = None
                continue
            normalised = _normalise_field(key, value)
            if normalised is not None:
                merged[key] = normalised
    dumped = yaml.safe_dump(
        _yaml_safe(merged), allow_unicode=True, sort_keys=False, default_flow_style=False
    ).rstrip()
    updated = f"---\n{dumped}\n---\n{body}"
    if updated == original:
        return False
    if dry_run:
        return True
    _atomic_write(page_path, updated)
    return True


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _string_list(values: list[str] | None, *, lowercase: bool = False) -> str:
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
    fields = [
        "---",
        "type: person",
        f"name: {_quoted(name)}",
        f"role: {_quoted(role) if role else 'null'}",
        f"company: {_quoted(company) if company else 'null'}",
        "company_page: null",
        f"emails: {_string_list(emails, lowercase=True)}",
        f"aliases: {_string_list(aliases)}",
        f"location: {location if location in {'internal', 'external', 'unknown'} else 'unknown'}",
        "last_interaction: null",
        "---",
        f"# {name}",
        "",
        "## Notes",
        "",
    ]
    if notes:
        fields.extend([notes, ""])
    fields.extend([
        "## Recent Interactions",
        "",
        "<!-- dex:auto:recent-interactions -->",
        "<!-- /dex:auto -->",
        "",
        "## Key Context",
        "",
    ])
    return "\n".join(fields) + "\n"


def render_company_page(
    name: str,
    domains: list[str] | None = None,
    website: str | None = None,
    status: str = "Prospect",
) -> str:
    """Render a canonical company page."""
    return "\n".join(
        [
            "---",
            "type: company",
            f"name: {_quoted(name)}",
            f"domains: {_string_list(domains, lowercase=True)}",
            f"website: {_quoted(website) if website else 'null'}",
            f"status: {_quoted(status)}",
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
            "",
        ]
    )


def replace_machine_region(text: str, slug: str, new_content: str) -> str:
    """Replace one named machine-owned region, preserving its markers."""
    start = f"<!-- dex:auto:{slug} -->"
    end = "<!-- /dex:auto -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    if not pattern.search(text):
        raise ValueError(f"machine region not found: {slug}")
    content = new_content.strip("\r\n")
    replacement = f"{start}\n{content}\n{end}" if content else f"{start}\n{end}"
    return pattern.sub(lambda _match: replacement, text, count=1)


def replace_machine_region_in_file(path: str | Path, slug: str, new_content: str) -> bool:
    """Atomically replace a named machine region in a page."""
    page_path = Path(path)
    original = page_path.read_text(encoding="utf-8")
    updated = replace_machine_region(original, slug, new_content)
    if updated == original:
        return False
    _atomic_write(page_path, updated)
    return True
