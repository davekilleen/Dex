#!/usr/bin/env python3
"""Generate the signed Dex Lens catalog envelope from publisher-owned Core data."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import posixpath
import re
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Mapping, Protocol, TypeVar

import jsonschema

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from core.lens_catalog_discovery import (
    LensDiscoveryError,
    discover_active_skills,
    discover_mcp_servers,
    discover_scheduled_automations,
    discover_system_engines,
)
from core.lens_catalog_sources import SkillSourceError, resolve_skill_source

REGISTRY_PATH = Path("core/lens-catalog/registry.json")
ENRICHED_REGISTRY_PATH = Path("core/lens-catalog/enriched-registry.json")
LENS_CATALOG_SCHEMA_PATH = Path("core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json")
PACKAGE_PATH = Path("package.json")
CHANGELOG_PATH = Path("CHANGELOG.md")
HARNESS_REGISTRY_PATH = Path("core/harnesses/registry.json")
HARNESS_PORTABILITY_PATH = Path("core/harnesses/portability.json")
CONTRACT_VERSION = "dex-lens-catalogue-v2"
MINIMUM_LENS_CONTRACT = "0.1.0"
REGISTRY_VERSION = 1
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.]+)?$")
KEBAB = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
CATALOG_ID = re.compile(r"^[a-z][a-z0-9-]{2,80}$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
FOUNDATION_CAPABILITIES = frozenset(
    {
        "ownership-portability",
        "privacy-minimal-disclosure",
        "context-orientation",
        "durable-memory-provenance",
        "scoped-agency-human-control",
        "safe-change-recovery",
        "honest-health-observability",
        "compounding-correctability",
    }
)
CANONICAL_JOB_IDS = (
    "capture-without-friction",
    "start-each-day-focused",
    "track-people-and-relationships",
    "manage-tasks-reliably",
    "reflect-and-improve-continuously",
    "keep-projects-on-track",
    "track-career-growth",
    "evolve-the-system-itself",
)
IMPACT_TIERS = frozenset({"core", "high", "medium", "niche"})


class LensCatalogError(RuntimeError):
    """The publisher-owned registry cannot produce a trusted Lens catalog."""


class _DiscoveredCandidate(Protocol):
    capability_id: str


_CandidateT = TypeVar("_CandidateT", bound=_DiscoveredCandidate)


def _index_discovered_candidates(
    candidates: tuple[_CandidateT, ...], *, capability_class: str
) -> dict[str, _CandidateT]:
    indexed: dict[str, _CandidateT] = {}
    for candidate in candidates:
        if candidate.capability_id in indexed:
            raise LensCatalogError(
                f"{capability_class} discovery produced duplicate capability id {candidate.capability_id!r}"
            )
        indexed[candidate.capability_id] = candidate
    return indexed


def _closed_json(path: Path) -> object:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise LensCatalogError(f"{path} repeats JSON field {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                LensCatalogError(f"{path} contains non-finite JSON number {value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LensCatalogError(f"cannot read {path}: {error}") from error


def _mapping(value: object, *, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise LensCatalogError(f"{context} must be a JSON object")
    return value


def _exact_fields(value: Mapping[str, object], expected: set[str], *, context: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise LensCatalogError(f"{context} fields are not closed ({'; '.join(details)})")


def _text(value: object, *, context: str, max_length: int = 512) -> str:
    if not isinstance(value, str):
        raise LensCatalogError(f"{context} must be text")
    if not value.strip():
        raise LensCatalogError(f"{context} must be non-empty")
    if len(value) > max_length:
        raise LensCatalogError(f"{context} exceeds {max_length} characters")
    if CONTROL.search(value):
        raise LensCatalogError(f"{context} contains control characters")
    return value


def _kebab(value: object, *, context: str) -> str:
    text = _text(value, context=context, max_length=128)
    if KEBAB.fullmatch(text) is None:
        raise LensCatalogError(f"{context} must be kebab-case")
    return text


def _semver(value: object, *, context: str) -> str:
    text = _text(value, context=context, max_length=64)
    if SEMVER.fullmatch(text) is None:
        raise LensCatalogError(f"{context} must be a semantic version")
    return text


def _text_tuple(value: object, *, context: str, max_length: int = 512) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise LensCatalogError(f"{context} must be a non-empty array")
    return tuple(_text(item, context=f"{context} item", max_length=max_length) for item in value)


def _catalog_id_tuple(value: object, *, context: str) -> tuple[str, ...]:
    identifiers = _text_tuple(value, context=context, max_length=81)
    for identifier in identifiers:
        if CATALOG_ID.fullmatch(identifier) is None:
            raise LensCatalogError(f"{context} item must be kebab-case Lens catalogue id")
    if len(set(identifiers)) != len(identifiers):
        raise LensCatalogError(f"{context} contains duplicate Lens catalogue ids")
    return identifiers


def _relative_path(raw_path: object, *, context: str) -> str:
    path = _text(raw_path, context=context, max_length=512)
    if "\\" in path:
        raise LensCatalogError(f"{context} is not a canonical POSIX path: {path!r}")
    normalized = posixpath.normpath(path)
    if (
        normalized != path
        or normalized in ("", ".", "..")
        or normalized.startswith("/")
        or normalized.startswith("../")
    ):
        raise LensCatalogError(f"{context} is not a canonical POSIX path: {path!r}")
    return path


def _release_file(release_root: Path, raw_path: object, *, context: str) -> tuple[str, Path]:
    relative = _relative_path(raw_path, context=context)
    candidate = release_root / relative
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(release_root):
        raise LensCatalogError(f"{context} escapes the release root: {relative!r}")
    if candidate.is_symlink() or not candidate.is_file():
        raise LensCatalogError(f"{context} is missing or not a regular file: {relative}")
    return relative, candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_version(release_root: Path) -> str:
    package = _mapping(_closed_json(release_root / PACKAGE_PATH), context=str(PACKAGE_PATH))
    return _semver(package.get("version"), context="package.json version")


def _changelog_versions(release_root: Path) -> set[str]:
    try:
        text = (release_root / CHANGELOG_PATH).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise LensCatalogError(f"cannot read {CHANGELOG_PATH}: {error}") from error
    return set(re.findall(r"^## \[([0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.]+)?)\]", text, re.MULTILINE))


def _skill_description(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise LensCatalogError(f"cannot read shipped skill source {path}: {error}") from error
    if not text.startswith("---\n"):
        raise LensCatalogError(f"shipped skill source has no frontmatter: {path}")
    lines = text.splitlines()
    for line in lines[1:]:
        if line == "---":
            break
        if line.startswith("description:"):
            return _text(
                line.split(":", 1)[1].strip().strip('"'),
                context=f"{path} description",
                max_length=1024,
            )
    raise LensCatalogError(f"shipped skill source has no description: {path}")


def _human_title(entry_id: str) -> str:
    return " ".join(part.capitalize() for part in entry_id.split("-"))


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _parse_issued_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise LensCatalogError(f"issued_at is not an ISO-8601 timestamp: {value!r}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LensCatalogError("issued_at must include a timezone")
    return parsed.astimezone(UTC).replace(microsecond=0)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _source(entry: Mapping[str, object], release_root: Path, *, context: str) -> dict[str, object]:
    try:
        pin = resolve_skill_source(entry.get("source"), release_root)
    except SkillSourceError as error:
        raise LensCatalogError(f"{context} source identity is invalid: {error}") from error
    return {
        "kind": pin.kind,
        "path": pin.source_path,
        "target_path": pin.target_path,
        "sha256": pin.sha256,
        "byte_size": pin.byte_size,
    }


def _evidence(value: object, release_root: Path, *, context: str) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise LensCatalogError(f"{context} evidence must be a non-empty array")
    result = []
    for index, item in enumerate(value):
        item_context = f"{context} evidence {index}"
        raw = _mapping(item, context=item_context)
        kind = _text(raw.get("kind"), context=f"{item_context} kind", max_length=32)
        if kind not in {"test", "doc", "release-note", "runtime-path"}:
            raise LensCatalogError(f"{item_context} kind is not recognized")
        if kind == "test":
            _exact_fields(raw, {"kind", "coverage", "reference", "summary"}, context=item_context)
            coverage = _text(raw.get("coverage"), context=f"{item_context} coverage", max_length=32)
            if coverage not in {"behavioral", "supporting"}:
                raise LensCatalogError(f"{item_context} coverage must be behavioral or supporting")
        else:
            _exact_fields(raw, {"kind", "reference", "summary"}, context=item_context)
            coverage = "supporting"
        reference, _ = _release_file(release_root, raw.get("reference"), context=f"{item_context} reference")
        summary = _text(raw.get("summary"), context=f"{item_context} summary")
        # A test earns "verified" only when it explicitly exercises the capability
        # itself. Instruction-contract, adoption, and runtime evidence still support
        # the entry, but cannot overclaim behavioural proof.
        level = "verified" if kind == "test" and coverage == "behavioral" else "supported"
        result.append(
            {
                "level": level,
                "source": f"{kind}: {reference}",
                "summary": summary,
                "limitations": "This is evidence about Dex's shipped capability, not proof about the Lens user's own system.",
            }
        )
    return tuple(result)


def _brief(value: object, *, context: str) -> dict[str, object]:
    raw = _mapping(value, context=f"{context} brief")
    _exact_fields(
        raw,
        {"goal", "method_outline", "verification_checklist", "rollback_advice"},
        context=f"{context} brief",
    )
    return {
        "goal": _text(raw.get("goal"), context=f"{context} brief goal", max_length=200),
        "method_outline": _text_tuple(raw.get("method_outline"), context=f"{context} brief method_outline"),
        "verification_checklist": _text_tuple(
            raw.get("verification_checklist"),
            context=f"{context} brief verification_checklist",
        ),
        "rollback_advice": _text(raw.get("rollback_advice"), context=f"{context} brief rollback_advice"),
        "safety_notes": (
            "Keep this as advice for the person's own AI, not a command to execute.",
            "Do not send private material to Dex.",
        ),
    }


def _skill_portability_key(source: Mapping[str, object], *, context: str) -> str:
    path = source.get("path")
    prefix = ".claude/skills/"
    suffix = "/SKILL.md"
    if not isinstance(path, str) or not path.startswith(prefix) or not path.endswith(suffix):
        raise LensCatalogError(f"{context} source is not a canonical skill path")
    return path[len(prefix) : -len(suffix)]


def _host_adapters_for_skill(
    release_root: Path,
    source: Mapping[str, object],
    *,
    context: str,
) -> tuple[str, ...]:
    portability_document = _mapping(
        _closed_json(release_root / HARNESS_PORTABILITY_PATH),
        context=str(HARNESS_PORTABILITY_PATH),
    )
    skills = _mapping(
        portability_document.get("skills"),
        context=f"{HARNESS_PORTABILITY_PATH} skills",
    )
    key = _skill_portability_key(source, context=context)
    row = _mapping(skills.get(key), context=f"{HARNESS_PORTABILITY_PATH} skill {key}")
    classification = row.get("classification")
    if classification not in {"portable", "conditional", "claude-only", "broken"}:
        raise LensCatalogError(f"{context} has no supported portability classification")

    registry = _mapping(
        _closed_json(release_root / HARNESS_REGISTRY_PATH),
        context=str(HARNESS_REGISTRY_PATH),
    )
    profiles = registry.get("profiles")
    if not isinstance(profiles, list):
        raise LensCatalogError(f"{HARNESS_REGISTRY_PATH} profiles must be an array")
    capable: list[str] = []
    claude_native: list[str] = []
    for profile in profiles:
        if not isinstance(profile, Mapping) or not isinstance(profile.get("id"), str):
            raise LensCatalogError(f"{HARNESS_REGISTRY_PATH} contains a malformed profile")
        rows = profile.get("capabilities")
        if not isinstance(rows, list):
            raise LensCatalogError(f"{HARNESS_REGISTRY_PATH} profile capabilities must be an array")
        skills_row = next(
            (row for row in rows if isinstance(row, Mapping) and row.get("id") == "agent-skills"),
            None,
        )
        if not isinstance(skills_row, Mapping) or skills_row.get("status") not in {"native", "portable"}:
            continue
        capable.append(profile["id"])
        adapter = profile.get("adapter")
        if isinstance(adapter, Mapping) and adapter.get("kind") == "claude-plugin":
            claude_native.append(profile["id"])
    if classification in {"portable", "conditional"}:
        adapters = capable
    else:
        # Preserve the existing Claude-only floor for skills whose body is not
        # portable yet; the portability reason remains the authority for the
        # limitation and prevents claiming other hosts.
        adapters = claude_native
    if not adapters:
        raise LensCatalogError(f"{context} resolves to no host adapters")
    return tuple(adapters)


def _compatibility(
    value: object,
    *,
    context: str,
    host_adapters: tuple[str, ...],
) -> dict[str, object]:
    raw = _mapping(value, context=f"{context} compatibility")
    _exact_fields(
        raw,
        {"host_requirements", "needs_hooks", "needs_mcp", "platforms"},
        context=f"{context} compatibility",
    )
    platforms = tuple(_text_tuple(raw.get("platforms"), context=f"{context} compatibility platforms", max_length=32))
    unknown_platforms = sorted(set(platforms) - {"macos", "linux", "windows"})
    if unknown_platforms:
        raise LensCatalogError(f"{context} compatibility has unknown platforms: {', '.join(unknown_platforms)}")
    for key in ("needs_hooks", "needs_mcp"):
        if type(raw.get(key)) is not bool:
            raise LensCatalogError(f"{context} compatibility {key} must be true or false")
    return {
        "host_adapters": host_adapters,
        "foundation_capabilities": (),
        "minimum_lens_contract": MINIMUM_LENS_CONTRACT,
        "platforms": platforms,
        "needs_hooks": raw["needs_hooks"],
        "needs_mcp": raw["needs_mcp"],
        "host_requirements": _catalog_id_tuple(
            raw.get("host_requirements"),
            context=f"{context} compatibility host_requirements",
        ),
        "limitations": ("Lens must still verify the host system locally before recommending use.",),
    }


def _validate_against_lens_schema(
    release_root: Path,
    envelope: Mapping[str, object],
    *,
    schema_path: Path | None = None,
    required_lens_version: str | None = None,
) -> None:
    selected_schema = schema_path or release_root / LENS_CATALOG_SCHEMA_PATH
    schema = _mapping(_closed_json(selected_schema), context=str(selected_schema))
    if required_lens_version is not None and schema.get("x-dex-lens-minimum-version") != required_lens_version:
        raise LensCatalogError(
            f"enriched catalogue schema must declare x-dex-lens-minimum-version {required_lens_version}"
        )
    wire_envelope = json.loads(_canonical_json(envelope))
    try:
        jsonschema.Draft202012Validator(schema).validate(wire_envelope)
    except jsonschema.ValidationError as error:
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        label = "enriched catalogue" if required_lens_version is not None else "emitted Lens catalogue"
        raise LensCatalogError(f"{label} violates the supplied Lens schema at {path}: {error.message}") from error


def _build_catalogue(
    release_root: Path,
    *,
    include_dormant: bool = False,
    enriched: bool = False,
) -> tuple[int, str, dict[str, object]]:
    registry = _mapping(_closed_json(release_root / REGISTRY_PATH), context=str(REGISTRY_PATH))
    _exact_fields(registry, {"registry_version", "catalog_version", "jobs", "entries"}, context=str(REGISTRY_PATH))
    if registry["registry_version"] != REGISTRY_VERSION:
        raise LensCatalogError(f"{REGISTRY_PATH} has an unsupported registry version")
    catalog_version = registry["catalog_version"]
    if type(catalog_version) is not int or catalog_version <= 0:
        raise LensCatalogError("catalog_version must be a positive integer")

    release_version = _package_version(release_root)
    released_versions = _changelog_versions(release_root)
    if release_version not in released_versions:
        raise LensCatalogError(f"package version {release_version} has no shipped source in CHANGELOG.md")

    jobs_raw = registry["jobs"]
    if not isinstance(jobs_raw, list) or not jobs_raw:
        raise LensCatalogError("jobs must be a non-empty array")
    jobs = []
    seen_jobs: set[str] = set()
    for index, raw_job in enumerate(jobs_raw):
        context = f"job {index}"
        job = _mapping(raw_job, context=context)
        _exact_fields(job, {"job_id", "title", "description"}, context=context)
        job_id = _kebab(job.get("job_id"), context=f"{context} job_id")
        if job_id in seen_jobs:
            raise LensCatalogError(f"duplicate job id {job_id!r}")
        seen_jobs.add(job_id)
        jobs.append(
            {
                "job_id": job_id,
                "label": _text(job.get("title"), context=f"{context} title", max_length=96),
                "description": _text(job.get("description"), context=f"{context} description"),
                "confirmed_gap_signals": (f"The Lens session finds a gap related to {job_id.replace('-', ' ')}.",),
            }
        )
    if tuple(job["job_id"] for job in jobs) != CANONICAL_JOB_IDS:
        raise LensCatalogError("jobs must contain the documented eight Jobs to Be Done in canonical order")

    entries_raw = registry["entries"]
    if not isinstance(entries_raw, list) or not entries_raw:
        raise LensCatalogError("entries must be a non-empty array")
    classified_entries: list[tuple[int, str, str, Mapping[str, object]]] = []
    seen_entries: set[str] = set()
    for index, raw_entry in enumerate(entries_raw):
        context = f"entry {index}"
        entry = _mapping(raw_entry, context=context)
        _exact_fields(
            entry,
            {
                "id",
                "capability_class",
                "impact_tier",
                "availability",
                "source",
                "value",
                "jobs_served",
                "foundation_capabilities",
                "prerequisites",
                "trade_offs",
                "evidence",
                "brief",
                "compatibility",
                "docs_url",
                "since_release",
                "changed_in",
            },
            context=context,
        )
        entry_id = _kebab(entry.get("id"), context=f"{context} id")
        if entry_id in seen_entries:
            raise LensCatalogError(f"duplicate entry id {entry_id!r}")
        seen_entries.add(entry_id)
        capability_class = _text(
            entry.get("capability_class"), context=f"{context} capability_class", max_length=32
        )
        if capability_class != "active-skill":
            raise LensCatalogError(f"{context} capability_class must be active-skill")
        impact_tier = _text(entry.get("impact_tier"), context=f"{context} impact_tier", max_length=16)
        if impact_tier not in IMPACT_TIERS:
            raise LensCatalogError(f"{context} impact_tier must be core, high, medium, or niche")
        availability = _text(entry.get("availability"), context=f"{context} availability", max_length=16)
        if availability not in {"active", "dormant"}:
            raise LensCatalogError(f"{context} availability must be active or dormant")
        classified_entries.append((index, entry_id, availability, entry))

    try:
        discovered = discover_active_skills(release_root)
    except LensDiscoveryError as error:
        raise LensCatalogError(f"active skill discovery failed: {error}") from error
    discovered_by_id = {candidate.capability_id: candidate for candidate in discovered}
    active_annotations = {
        entry_id: (index, entry)
        for index, entry_id, availability, entry in classified_entries
        if availability == "active"
    }
    vendored_annotations = sorted(entry_id for entry_id in active_annotations if entry_id.startswith("anthropic-"))
    if vendored_annotations:
        raise LensCatalogError(
            "active skill annotations must not be a vendored skill: " + ", ".join(vendored_annotations)
        )
    missing_annotations = sorted(set(discovered_by_id) - set(active_annotations))
    stale_annotations = sorted(set(active_annotations) - set(discovered_by_id))
    if missing_annotations or stale_annotations:
        details = []
        if missing_annotations:
            details.append("missing annotations: " + ", ".join(missing_annotations))
        if stale_annotations:
            details.append("stale annotations: " + ", ".join(stale_annotations))
        raise LensCatalogError("active skill annotations do not match discovery (" + "; ".join(details) + ")")

    dormant_entries = [item for item in classified_entries if item[2] == "dormant"]
    ordered_entries = [
        (active_annotations[candidate.capability_id][0], candidate.capability_id, "active", active_annotations[candidate.capability_id][1])
        for candidate in discovered
    ] + dormant_entries

    entries = []
    seen_targets: dict[str, str] = {}
    for index, entry_id, availability, entry in ordered_entries:
        context = f"entry {index}"
        source = _source(entry, release_root, context=context)
        expected_target = f".claude/skills/{entry_id}/SKILL.md"
        if source["target_path"] != expected_target:
            raise LensCatalogError(f"{context} resolved source target must match entry id {entry_id!r}")
        if availability == "active" and source["kind"] != "active-skill":
            raise LensCatalogError(f"{context} active annotation must use an active-skill source")
        if availability == "dormant" and source["kind"] == "active-skill":
            raise LensCatalogError(f"{context} dormant annotation must use a dormant skill source")
        target_owner = seen_targets.setdefault(str(source["target_path"]), entry_id)
        if target_owner != entry_id:
            raise LensCatalogError(f"{context} resolved source target duplicates entry {target_owner!r}")
        jobs_served = _catalog_id_tuple(entry.get("jobs_served"), context=f"{context} jobs_served")
        for job_id in jobs_served:
            if job_id not in seen_jobs:
                raise LensCatalogError(f"{context} has unknown job reference: {job_id}")
        foundations = _text_tuple(
            entry.get("foundation_capabilities"), context=f"{context} foundation_capabilities", max_length=128
        )
        for foundation in foundations:
            if foundation not in FOUNDATION_CAPABILITIES:
                raise LensCatalogError(f"{context} has unknown foundation reference: {foundation}")
        since_release = _semver(entry.get("since_release"), context=f"{context} since_release")
        if since_release not in released_versions:
            raise LensCatalogError(f"{context} since_release has no shipped source in CHANGELOG.md: {since_release}")
        changed_in = entry.get("changed_in")
        if not isinstance(changed_in, list):
            raise LensCatalogError(f"{context} changed_in must be an array")
        changed = tuple(_semver(item, context=f"{context} changed_in item") for item in changed_in)
        for version in changed:
            if version not in released_versions:
                raise LensCatalogError(f"{context} changed_in has no shipped source in CHANGELOG.md: {version}")
        compatibility = _compatibility(
            entry.get("compatibility"),
            context=context,
            host_adapters=_host_adapters_for_skill(
                release_root,
                source,
                context=context,
            ),
        )
        if availability == "dormant" and not include_dormant:
            continue
        summary = (
            discovered_by_id[entry_id].description
            if availability == "active"
            else _skill_description(release_root / str(source["path"]))
        )
        entries.append(
            {
                "capability_id": entry_id,
                "title": _human_title(entry_id),
                "summary": summary,
                "capability_class": entry["capability_class"],
                "impact_tier": entry["impact_tier"],
                "availability": availability,
                "value": _text(entry.get("value"), context=f"{context} value"),
                "jobs": jobs_served,
                "prerequisites": _text_tuple(entry.get("prerequisites"), context=f"{context} prerequisites"),
                "trade_offs": _text_tuple(entry.get("trade_offs"), context=f"{context} trade_offs"),
                "evidence": _evidence(entry.get("evidence"), release_root, context=context),
                "brief": _brief(entry.get("brief"), context=context),
                "compatibility": {
                    **compatibility,
                    "foundation_capabilities": foundations,
                },
                "portable_brief": _brief(entry.get("brief"), context=context),
                "docs_url": _text(entry.get("docs_url"), context=f"{context} docs_url", max_length=256),
                "since_release": since_release,
                "changed_in": changed,
                "source": source,
                "version_hash": f"sha256:{source['sha256']}",
                "core_release": f"v{release_version}",
                "release_provenance": "core-release",
            }
        )

    catalogue = {
        "jobs_taxonomy": jobs,
        "capabilities": [
            {
                **(
                    {
                        "capability_class": entry["capability_class"],
                        "impact_tier": entry["impact_tier"],
                        "availability": entry["availability"],
                    }
                    if enriched
                    else {}
                ),
                "capability_id": entry["capability_id"],
                "title": entry["title"],
                "summary": entry["summary"],
                "value": entry["value"],
                "jobs": entry["jobs"],
                "prerequisites": entry["prerequisites"],
                "trade_offs": entry["trade_offs"],
                "evidence": entry["evidence"],
                "compatibility": entry["compatibility"],
                "docs_url": entry["docs_url"],
                "since_release": entry["since_release"],
                "changed_in": entry["changed_in"],
                "release_provenance": entry["release_provenance"],
                "portable_brief": entry["portable_brief"],
            }
            for entry in entries
        ],
        "portable_brief": {
            "format": "markdown",
            "audience": "the person's own AI system",
            "safety_boundary": "Brief only: Lens presents adaptation guidance and never applies Dex changes automatically.",
        },
    }
    return catalog_version, release_version, catalogue


def _preview_title(capability_id: str) -> str:
    words = capability_id.removeprefix("com.dex.").replace(".", "-").split("-")
    return " ".join({"dex": "Dex", "mcp": "MCP"}.get(word, word.capitalize()) for word in words)


def _preview_evidence(source_paths: tuple[str, ...], *, title: str) -> tuple[dict[str, str], ...]:
    return (
        {
            "level": "supported",
            "source": f"runtime-path: {source_paths[0]}",
            "summary": f"The shipped source tree contains the reviewed {title} implementation.",
            "limitations": "Source presence proves Dex ships the implementation, not that it is configured or healthy on a Lens user's system.",
        },
    )


def _build_enriched_catalogue(release_root: Path) -> tuple[int, str, dict[str, object]]:
    catalog_version, release_version, catalogue = _build_catalogue(
        release_root,
        include_dormant=True,
        enriched=True,
    )
    registry = _mapping(
        _closed_json(release_root / ENRICHED_REGISTRY_PATH),
        context=str(ENRICHED_REGISTRY_PATH),
    )
    _exact_fields(registry, {"registry_version", "entries"}, context=str(ENRICHED_REGISTRY_PATH))
    if registry.get("registry_version") != 1:
        raise LensCatalogError(f"{ENRICHED_REGISTRY_PATH} has an unsupported registry version")

    try:
        discovered = {
            "mcp-server": _index_discovered_candidates(
                discover_mcp_servers(release_root), capability_class="mcp-server"
            ),
            "scheduled-automation": _index_discovered_candidates(
                discover_scheduled_automations(release_root),
                capability_class="scheduled-automation",
            ),
            "system-engine": _index_discovered_candidates(
                discover_system_engines(release_root), capability_class="system-engine"
            ),
        }
    except LensDiscoveryError as error:
        raise LensCatalogError(f"enriched capability discovery failed: {error}") from error

    annotations_raw = registry.get("entries")
    if not isinstance(annotations_raw, list) or not annotations_raw:
        raise LensCatalogError(f"{ENRICHED_REGISTRY_PATH} entries must be a non-empty array")
    annotations: dict[str, tuple[str, Mapping[str, object], int]] = {}
    annotated_by_class = {capability_class: set() for capability_class in discovered}
    existing_capability_ids = {entry["capability_id"] for entry in catalogue["capabilities"]}
    for index, raw_annotation in enumerate(annotations_raw):
        context = f"enriched entry {index}"
        annotation = _mapping(raw_annotation, context=context)
        _exact_fields(
            annotation,
            {
                "id",
                "capability_class",
                "impact_tier",
                "availability",
                "value",
                "jobs_served",
                "prerequisites",
                "trade_offs",
            },
            context=context,
        )
        capability_id = _text(annotation.get("id"), context=f"{context} id", max_length=81)
        if CATALOG_ID.fullmatch(capability_id) is None:
            raise LensCatalogError(f"{context} id must be a Lens catalogue id")
        if capability_id in annotations:
            raise LensCatalogError(f"duplicate enriched entry id {capability_id!r}")
        if capability_id in existing_capability_ids:
            raise LensCatalogError(f"{context} duplicates existing capability id {capability_id!r}")
        capability_class = _text(
            annotation.get("capability_class"), context=f"{context} capability_class", max_length=32
        )
        if capability_class not in discovered:
            raise LensCatalogError(f"{context} has an unsupported capability_class")
        impact_tier = _text(annotation.get("impact_tier"), context=f"{context} impact_tier", max_length=16)
        if impact_tier not in IMPACT_TIERS:
            raise LensCatalogError(f"{context} impact_tier must be core, high, medium, or niche")
        availability = _text(annotation.get("availability"), context=f"{context} availability", max_length=16)
        if availability not in {"active", "parked"}:
            raise LensCatalogError(f"{context} availability must be active or parked")
        annotations[capability_id] = (capability_class, annotation, index)
        annotated_by_class[capability_class].add(capability_id)

    for capability_class, candidates in discovered.items():
        missing = sorted(set(candidates) - annotated_by_class[capability_class])
        stale = sorted(annotated_by_class[capability_class] - set(candidates))
        if missing or stale:
            details = []
            if missing:
                details.append("missing annotations: " + ", ".join(missing))
            if stale:
                details.append("stale annotations: " + ", ".join(stale))
            raise LensCatalogError(
                f"{capability_class} annotations do not match discovery (" + "; ".join(details) + ")"
            )

    known_jobs = {job["job_id"] for job in catalogue["jobs_taxonomy"]}
    preview_entries = list(catalogue["capabilities"])
    for capability_id, (capability_class, annotation, index) in annotations.items():
        context = f"enriched entry {index}"
        candidate = discovered[capability_class][capability_id]
        expected_availability = getattr(candidate, "availability", "active")
        if annotation["availability"] != expected_availability:
            raise LensCatalogError(
                f"{context} availability {annotation['availability']!r} does not match discovered {expected_availability!r}"
            )
        jobs = _catalog_id_tuple(annotation.get("jobs_served"), context=f"{context} jobs_served")
        for job_id in jobs:
            if job_id not in known_jobs:
                raise LensCatalogError(f"{context} has unknown job reference: {job_id}")
        title = _preview_title(capability_id)
        if capability_class == "mcp-server":
            source_paths = (candidate.source_path,)
            summary = (
                f"{candidate.server_name} exposes {candidate.tool_count} local MCP tools; "
                f"examples include {', '.join(candidate.example_tools)}."
            )
            class_fields = {
                "server_name": candidate.server_name,
                "tool_count": candidate.tool_count,
                "example_tools": candidate.example_tools,
                "source_paths": source_paths,
            }
        elif capability_class == "scheduled-automation":
            source_paths = candidate.source_paths
            summary = f"Runs {candidate.program_target} {candidate.cadence}."
            class_fields = {
                "automation_label": candidate.automation_label,
                "cadence": candidate.cadence,
                "source_paths": source_paths,
                "installer_path": candidate.installer_path,
                "program_target": candidate.program_target,
                "run_at_load": candidate.run_at_load,
            }
        else:
            source_paths = candidate.source_paths
            state = " Parked: it is not wired into the live product." if candidate.availability == "parked" else ""
            summary = f"Groups {candidate.component_count} shipped source components.{state}"
            class_fields = {
                "source_paths": source_paths,
                "component_count": candidate.component_count,
                "example_components": candidate.example_components,
            }
        preview_entries.append(
            {
                "capability_id": capability_id,
                "capability_class": capability_class,
                "impact_tier": annotation["impact_tier"],
                "availability": annotation["availability"],
                "title": title,
                "summary": summary,
                "value": _text(annotation.get("value"), context=f"{context} value", max_length=1200),
                "jobs": jobs,
                "prerequisites": _text_tuple(
                    annotation.get("prerequisites"), context=f"{context} prerequisites"
                ),
                "trade_offs": _text_tuple(annotation.get("trade_offs"), context=f"{context} trade_offs"),
                "evidence": _preview_evidence(source_paths, title=title),
                "release_provenance": "core-release",
                **class_fields,
            }
        )
    catalogue["capabilities"] = preview_entries
    return catalog_version + 1, release_version, catalogue


def _signature(payload: str, *, signing_key_env: str, key_id: str, test_deterministic: bool) -> str:
    secret = os.environ.get(signing_key_env, "")
    if not secret:
        raise LensCatalogError(f"environment secret {signing_key_env} is not set")
    try:
        key_bytes = base64.b64decode(secret, validate=True)
    except ValueError as error:
        raise LensCatalogError(f"environment secret {signing_key_env} is not base64") from error
    if test_deterministic:
        if os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
            raise LensCatalogError("deterministic test signature mode is disabled in CI")
        digest = hashlib.sha512(key_bytes + b"\0" + payload.encode("utf-8")).digest()
        return base64.b64encode(digest).decode("ascii")
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as error:
        raise LensCatalogError("cryptography>=42 is required to sign the Dex Lens catalog on this runner") from error
    try:
        private_key = serialization.load_pem_private_key(key_bytes, password=None)
    except ValueError as error:
        raise LensCatalogError(
            f"Ed25519 signing failed for key_id {key_id!r}; CI secret must contain a base64 PEM private key"
        ) from error
    if not isinstance(private_key, Ed25519PrivateKey):
        raise LensCatalogError(f"signing key_id {key_id!r} is not an Ed25519 private key")
    return base64.b64encode(private_key.sign(payload.encode("utf-8"))).decode("ascii")


def generate_lens_catalog(
    release_root: Path,
    *,
    output_dir: Path,
    issued_at: str | None = None,
    sign: bool = False,
    signing_key_env: str = "DEX_LENS_CATALOG_ED25519_PRIVATE_KEY_B64",
    key_id: str = "dex-core-lens-1",
    test_deterministic_signature: bool = False,
    enriched: bool = False,
) -> tuple[Path, Path]:
    release_root = release_root.resolve()
    issued = _parse_issued_at(issued_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    if enriched:
        catalog_version, release_version, catalogue = _build_enriched_catalogue(release_root)
    else:
        catalog_version, release_version, catalogue = _build_catalogue(release_root)
    metadata = {
        "contract_version": CONTRACT_VERSION,
        "catalog_version": catalog_version,
        "produced_at": issued.isoformat().replace("+00:00", "Z"),
        "expires_at": (issued + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "producer": (
            f"Dex Core enriched release pipeline v{release_version}"
            if enriched
            else f"Dex Core release pipeline v{release_version}"
        ),
        "core_release": f"v{release_version}",
        "key_id": key_id,
    }
    signed_payload = {"metadata": metadata, "catalogue": catalogue}
    _validate_against_lens_schema(
        release_root,
        {**signed_payload, "signature": "schema-validation-placeholder"},
        required_lens_version="0.1.9" if enriched else None,
    )
    payload = _canonical_json(signed_payload)
    signature = ""
    if sign:
        signature = _signature(
            payload,
            signing_key_env=signing_key_env,
            key_id=key_id,
            test_deterministic=test_deterministic_signature,
        )
    envelope = {**signed_payload, "signature": signature}
    encoded = (_canonical_json(envelope) + "\n").encode("utf-8")
    destination = output_dir / f"dex-lens-catalog-v{release_version}.json"
    latest = output_dir / "dex-lens-catalog-latest.json"
    _atomic_write(destination, encoded)
    _atomic_write(latest, encoded)
    digest_line = f"{hashlib.sha256(encoded).hexdigest()}  {destination.name}\n".encode("utf-8")
    _atomic_write(destination.with_suffix(destination.suffix + ".sha256"), digest_line)
    latest_digest_line = f"{hashlib.sha256(encoded).hexdigest()}  {latest.name}\n".encode("utf-8")
    _atomic_write(latest.with_suffix(latest.suffix + ".sha256"), latest_digest_line)
    return destination, latest


def generate_enriched_preview(
    release_root: Path,
    *,
    output_dir: Path,
    lens_schema: Path,
    issued_at: str | None = None,
    key_id: str = "dex-core-lens-1",
) -> Path:
    """Write one unsigned, non-release preview for the Lens 0.1.9 contract."""

    release_root = release_root.resolve()
    issued = _parse_issued_at(issued_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    catalog_version, release_version, catalogue = _build_enriched_catalogue(release_root)
    metadata = {
        "contract_version": CONTRACT_VERSION,
        "catalog_version": catalog_version,
        "produced_at": issued.isoformat().replace("+00:00", "Z"),
        "expires_at": (issued + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "producer": f"Dex Core enriched preview v{release_version}",
        "core_release": f"v{release_version}",
        "key_id": key_id,
    }
    envelope = {
        "metadata": metadata,
        "catalogue": catalogue,
        "signature": "UNSIGNED-PREVIEW-NOT-FOR-PUBLICATION",
    }
    _validate_against_lens_schema(
        release_root,
        envelope,
        schema_path=lens_schema.resolve(),
        required_lens_version="0.1.9",
    )
    destination = output_dir / "dex-lens-catalog-enriched-preview.json"
    _atomic_write(destination, (_canonical_json(envelope) + "\n").encode("utf-8"))
    return destination


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--release-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--issued-at")
    parser.add_argument("--sign", action="store_true")
    parser.add_argument("--signing-key-env", default="DEX_LENS_CATALOG_ED25519_PRIVATE_KEY_B64")
    parser.add_argument("--key-id", default="dex-core-lens-1")
    parser.add_argument("--test-deterministic-signature", action="store_true")
    parser.add_argument("--enriched", action="store_true")
    parser.add_argument("--enriched-preview", action="store_true")
    parser.add_argument("--lens-schema", type=Path)
    args = parser.parse_args(raw_argv)

    try:
        if args.enriched and args.enriched_preview:
            raise LensCatalogError("--enriched and --enriched-preview are mutually exclusive")
        if args.enriched_preview:
            if args.sign:
                raise LensCatalogError("enriched previews cannot be signed or published")
            signing_options = ("--signing-key-env", "--test-deterministic-signature", "--key-id")
            if any(
                argument == option or argument.startswith(f"{option}=")
                for argument in raw_argv
                for option in signing_options
            ):
                raise LensCatalogError("enriched previews cannot use signing options")
            if args.lens_schema is None:
                raise LensCatalogError("--enriched-preview requires --lens-schema from Dex Lens 0.1.9 or newer")
            preview = generate_enriched_preview(
                args.release_root,
                output_dir=args.output_dir,
                lens_schema=args.lens_schema,
                issued_at=args.issued_at,
                key_id=args.key_id,
            )
            print(f"Wrote unsigned preview {preview}")
            return 0
        if args.lens_schema is not None:
            raise LensCatalogError("--lens-schema is only valid with --enriched-preview")
        versioned, latest = generate_lens_catalog(
            args.release_root,
            output_dir=args.output_dir,
            issued_at=args.issued_at,
            sign=args.sign,
            signing_key_env=args.signing_key_env,
            key_id=args.key_id,
            test_deterministic_signature=args.test_deterministic_signature,
            enriched=args.enriched,
        )
    except LensCatalogError as error:
        parser.exit(1, f"Dex Lens catalog generation failed: {error}\n")
    print(f"Wrote {versioned}")
    print(f"Wrote {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
