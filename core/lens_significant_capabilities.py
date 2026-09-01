"""Canonical, reviewed significant-capability coverage for Dex Lens.

This module owns the small Core-side registry that groups the exact catalogue
and MCP identities discovered elsewhere in the repository.  It deliberately
does not copy capability availability into the registry: availability and
impact remain publisher-owned facts in the ordinary Lens catalogue registries
and discovery candidates.  Validation resolves those identities at check time
and fails closed when a registry reference drifts.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

from core.lens_catalog_discovery import (
    LensDiscoveryError,
    discover_active_skills,
    discover_mcp_servers,
    discover_scheduled_automations,
    discover_system_engines,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "core/lens-catalog/significant-capabilities.json"
CATALOG_REGISTRY_PATH = Path("core/lens-catalog/registry.json")
ENRICHED_REGISTRY_PATH = Path("core/lens-catalog/enriched-registry.json")
REGISTRY_VERSION = 1
PROVIDER_SOURCE_PACKAGE = "@nangohq/providers"
PROVIDER_SOURCE_VERSION = "0.70.5"

_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,80}$")
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_IMPACT_TIERS = frozenset({"core", "high", "medium", "niche"})
_AVAILABILITIES = frozenset({"active", "dormant", "parked"})
_ASSESSMENT_PROFILES = frozenset(
    {
        "catalogue",
        "mcp",
        "mcp-tool",
        "filesystem",
        "source-component",
        "provider",
        "scheduled-automation",
        "health",
        "doctor",
    }
)
_COMPONENT_TYPES = frozenset({"capability", "mcp-tool", "nango-provider", "source-component"})
_SOURCE_COMPONENT_IDS = frozenset(
    {
        "meeting-processing",
        "people-company-context",
        "work-task-continuity",
        "external-task-sync",
        "connection-manager-catalog",
        "pipedrive-pipeline",
        "daily-planning",
        "session-memory",
        "doctor-health",
        "vault-backup",
        "lifecycle-safe-rewind",
        "capability-adoption",
        "privacy-feedback",
        "career-evidence",
    }
)
_FAMILY_IDS = (
    "meeting-follow-through",
    "living-people-company-context",
    "durable-task-continuity",
    "external-task-interoperability",
    "connected-work-context",
    "pipedrive-pipeline-continuity",
    "daily-weekly-operating-rhythm",
    "durable-work-memory",
    "proactive-health-and-recovery",
    "backup-and-restore-confidence",
    "safe-change-and-rewind",
    "capability-discovery-and-adoption",
    "privacy-safe-feedback-loop",
    "career-growth-evidence",
)

ProviderResolver = Callable[[str], object]


class SignificantCapabilityRegistryError(ValueError):
    """The reviewed significant-capability registry is not safe to consume."""


def _strict_json(path: Path) -> object:
    """Read JSON while rejecting duplicate keys and non-finite numbers."""

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise SignificantCapabilityRegistryError(f"{path} repeats JSON field {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                SignificantCapabilityRegistryError(f"{path} contains non-finite JSON number {value}")
            ),
        )
    except SignificantCapabilityRegistryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SignificantCapabilityRegistryError(f"cannot read {path}: {error}") from error


def _mapping(value: object, *, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SignificantCapabilityRegistryError(f"{context} must be a JSON object")
    return value


def _exact_fields(value: Mapping[str, object], expected: set[str], *, context: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise SignificantCapabilityRegistryError(f"{context} fields are not closed ({'; '.join(details)})")


def _text(value: object, *, context: str, max_length: int = 800) -> str:
    if not isinstance(value, str):
        raise SignificantCapabilityRegistryError(f"{context} must be text")
    if not value.strip():
        raise SignificantCapabilityRegistryError(f"{context} must be non-empty")
    if len(value) > max_length:
        raise SignificantCapabilityRegistryError(f"{context} exceeds {max_length} characters")
    if _CONTROL_RE.search(value):
        raise SignificantCapabilityRegistryError(f"{context} contains control characters")
    return value


def _identifier(value: object, *, context: str) -> str:
    text = _text(value, context=context, max_length=81)
    if _ID_RE.fullmatch(text) is None:
        raise SignificantCapabilityRegistryError(f"{context} must be kebab-case")
    return text


def _text_list(
    value: object,
    *,
    context: str,
    allow_empty: bool = False,
    max_length: int = 800,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SignificantCapabilityRegistryError(f"{context} must be an array")
    if not value and not allow_empty:
        raise SignificantCapabilityRegistryError(f"{context} must be a non-empty array")
    return tuple(_text(item, context=f"{context} item", max_length=max_length) for item in value)


def _unique(values: tuple[str, ...], *, context: str) -> None:
    if len(set(values)) != len(values):
        raise SignificantCapabilityRegistryError(f"{context} contains duplicates")


def _source_component_id(value: object, *, context: str) -> str:
    """Validate the Lens source-component identity (never an executable path)."""

    component_id = _identifier(value, context=context)
    if component_id not in _SOURCE_COMPONENT_IDS:
        raise SignificantCapabilityRegistryError(f"{context} references unknown source component {component_id!r}")
    return component_id


def _read_catalogue_annotations(
    root: Path,
) -> tuple[dict[str, dict[str, object]], set[str]]:
    """Read the existing skill catalogue and return rows plus canonical jobs."""

    payload = _mapping(
        _strict_json(root / CATALOG_REGISTRY_PATH),
        context=str(CATALOG_REGISTRY_PATH),
    )
    _exact_fields(
        payload,
        {"registry_version", "catalog_version", "jobs", "entries"},
        context=str(CATALOG_REGISTRY_PATH),
    )
    if payload.get("registry_version") != 1:
        raise SignificantCapabilityRegistryError(f"{CATALOG_REGISTRY_PATH} has an unsupported registry version")
    raw_jobs = payload.get("jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise SignificantCapabilityRegistryError("catalogue jobs must be a non-empty array")
    jobs: set[str] = set()
    for index, raw_job in enumerate(raw_jobs):
        job = _mapping(raw_job, context=f"catalogue job {index}")
        _exact_fields(
            job,
            {"job_id", "title", "description"},
            context=f"catalogue job {index}",
        )
        job_id = _identifier(job.get("job_id"), context=f"catalogue job {index} job_id")
        if job_id in jobs:
            raise SignificantCapabilityRegistryError(f"duplicate catalogue job {job_id!r}")
        jobs.add(job_id)

    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise SignificantCapabilityRegistryError("catalogue entries must be a non-empty array")
    rows: dict[str, dict[str, object]] = {}
    for index, raw_entry in enumerate(raw_entries):
        entry = _mapping(raw_entry, context=f"catalogue entry {index}")
        entry_id = _identifier(entry.get("id"), context=f"catalogue entry {index} id")
        if entry_id in rows:
            raise SignificantCapabilityRegistryError(f"duplicate catalogue capability {entry_id!r}")
        tier = entry.get("impact_tier")
        availability = entry.get("availability")
        if tier not in _IMPACT_TIERS:
            raise SignificantCapabilityRegistryError(f"catalogue capability {entry_id!r} has an unknown impact tier")
        if availability not in _AVAILABILITIES:
            raise SignificantCapabilityRegistryError(f"catalogue capability {entry_id!r} has an unknown availability")
        rows[entry_id] = {
            "capability_class": entry.get("capability_class"),
            "impact_tier": tier,
            "availability": availability,
        }
    return rows, jobs


def _discover_candidates(
    root: Path,
) -> tuple[dict[str, dict[str, object]], dict[str, tuple[str, ...]], set[str]]:
    """Derive exact current identities from Core discovery and registries.

    The first return value is internal candidate metadata used only to decide
    coverage.  It is never copied into the significant registry or emitted as a
    second availability field.
    """

    try:
        rows, jobs = _read_catalogue_annotations(root)
        active_skills = discover_active_skills(root)
        discovered_active = {candidate.capability_id for candidate in active_skills}
        annotated_active = {
            capability_id
            for capability_id, row in rows.items()
            if row["capability_class"] == "active-skill" and row["availability"] == "active"
        }
        if discovered_active != annotated_active:
            missing = sorted(discovered_active - annotated_active)
            stale = sorted(annotated_active - discovered_active)
            details = []
            if missing:
                details.append("missing active annotations: " + ", ".join(missing))
            if stale:
                details.append("stale active annotations: " + ", ".join(stale))
            raise SignificantCapabilityRegistryError(
                "active skill identities do not match discovery (" + "; ".join(details) + ")"
            )

        enriched_payload = _mapping(
            _strict_json(root / ENRICHED_REGISTRY_PATH),
            context=str(ENRICHED_REGISTRY_PATH),
        )
        _exact_fields(
            enriched_payload,
            {"registry_version", "entries"},
            context=str(ENRICHED_REGISTRY_PATH),
        )
        if enriched_payload.get("registry_version") != 1:
            raise SignificantCapabilityRegistryError(f"{ENRICHED_REGISTRY_PATH} has an unsupported registry version")
        enriched_rows: dict[str, dict[str, object]] = {}
        raw_enriched = enriched_payload.get("entries")
        if not isinstance(raw_enriched, list) or not raw_enriched:
            raise SignificantCapabilityRegistryError(f"{ENRICHED_REGISTRY_PATH} entries must be a non-empty array")
        for index, raw_entry in enumerate(raw_enriched):
            entry = _mapping(raw_entry, context=f"enriched entry {index}")
            entry_id = _identifier(entry.get("id"), context=f"enriched entry {index} id")
            if entry_id in enriched_rows:
                raise SignificantCapabilityRegistryError(f"duplicate enriched capability {entry_id!r}")
            capability_class = entry.get("capability_class")
            if capability_class not in {
                "mcp-server",
                "scheduled-automation",
                "system-engine",
            }:
                raise SignificantCapabilityRegistryError(f"enriched capability {entry_id!r} has an unknown class")
            tier = entry.get("impact_tier")
            availability = entry.get("availability")
            if tier not in _IMPACT_TIERS:
                raise SignificantCapabilityRegistryError(f"enriched capability {entry_id!r} has an unknown impact tier")
            if availability not in _AVAILABILITIES:
                raise SignificantCapabilityRegistryError(
                    f"enriched capability {entry_id!r} has an unknown availability"
                )
            enriched_rows[entry_id] = {
                "capability_class": capability_class,
                "impact_tier": tier,
                "availability": availability,
            }

        discovered_mcp = discover_mcp_servers(root)
        discovered_automations = discover_scheduled_automations(root)
        discovered_engines = discover_system_engines(root)
        discovered_by_class = {
            "mcp-server": {candidate.capability_id for candidate in discovered_mcp},
            "scheduled-automation": {candidate.capability_id for candidate in discovered_automations},
            "system-engine": {candidate.capability_id for candidate in discovered_engines},
        }
        mcp_tools = {candidate.capability_id: tuple(candidate.tools) for candidate in discovered_mcp}
        for capability_class, discovered_ids in discovered_by_class.items():
            annotated_ids = {
                capability_id
                for capability_id, row in enriched_rows.items()
                if row["capability_class"] == capability_class
            }
            if discovered_ids != annotated_ids:
                missing = sorted(discovered_ids - annotated_ids)
                stale = sorted(annotated_ids - discovered_ids)
                details = []
                if missing:
                    details.append("missing: " + ", ".join(missing))
                if stale:
                    details.append("stale: " + ", ".join(stale))
                raise SignificantCapabilityRegistryError(
                    f"{capability_class} identities do not match discovery (" + "; ".join(details) + ")"
                )

        candidates: dict[str, dict[str, object]] = {}
        for capability_id, row in rows.items():
            candidates[capability_id] = dict(row)
        for capability_id, row in enriched_rows.items():
            if capability_id in candidates:
                raise SignificantCapabilityRegistryError(
                    f"capability identity appears in both registries: {capability_id!r}"
                )
            candidates[capability_id] = dict(row)
        return candidates, mcp_tools, jobs
    except LensDiscoveryError as error:
        raise SignificantCapabilityRegistryError(f"candidate discovery failed: {error}") from error


def _default_provider_resolver(
    provider_id: str,
    *,
    release_root: Path,
) -> dict[str, bool]:
    """Resolve provider existence, support, and vetting from Core's own sources.

    The dependency is intentionally not vendored.  A missing package (or a
    package with a different version) is an explicit validation failure rather
    than an invitation to silently accept a guessed provider id.  Support and
    security-review claims come from the shipped connection-manager catalog
    and pin registry, never from the broad Nango catalog alone.
    """

    package_root = release_root / "node_modules/@nangohq/providers"
    package_json = package_root / "package.json"
    if not package_json.is_file():
        raise SignificantCapabilityRegistryError(
            f"pinned provider source is unavailable: install {PROVIDER_SOURCE_PACKAGE} {PROVIDER_SOURCE_VERSION}"
        )
    try:
        package = _mapping(_strict_json(package_json), context=str(package_json))
    except SignificantCapabilityRegistryError as error:
        raise SignificantCapabilityRegistryError(f"pinned provider source is unavailable: {error}") from error
    if package.get("version") != PROVIDER_SOURCE_VERSION:
        raise SignificantCapabilityRegistryError(f"pinned provider source version is not {PROVIDER_SOURCE_VERSION}")

    connection_manager = release_root / "core/integrations/connection-manager"
    catalog_path = connection_manager / "catalog.cjs"
    pins_path = connection_manager / "pinned-providers.cjs"
    for source in (catalog_path, pins_path):
        if source.is_symlink() or not source.is_file():
            raise SignificantCapabilityRegistryError(
                f"pinned provider source is unavailable: {source} is missing or unsafe"
            )

    script = (
        "const providers = require('@nangohq/providers'); "
        "const catalog = require('./core/integrations/connection-manager/catalog.cjs'); "
        "const pins = require('./core/integrations/connection-manager/pinned-providers.cjs'); "
        "if (typeof providers.getProvider !== 'function' || "
        "typeof catalog.getProviderConfig !== 'function' || typeof pins.isVetted !== 'function') "
        "process.exit(3); "
        "const providerId = process.argv[1]; "
        "const provider = providers.getProvider(providerId); "
        "let supported = false; "
        "if (provider) { "
        "try { supported = catalog.getProviderConfig(providerId).supported === true; } catch {} "
        "} "
        "process.stdout.write(JSON.stringify({"
        "exists: Boolean(provider), supported, security_vetted: pins.isVetted(providerId) === true"
        "}));"
    )
    try:
        result = subprocess.run(
            ["node", "-e", script, provider_id],
            cwd=release_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SignificantCapabilityRegistryError(f"pinned provider source is unavailable: {error}") from error
    if result.returncode != 0:
        raise SignificantCapabilityRegistryError("pinned provider source could not resolve provider identities")
    try:
        truth = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SignificantCapabilityRegistryError(
            "pinned provider source returned malformed provider truth"
        ) from error
    normalized = _provider_truth(truth)
    if normalized is None:
        raise SignificantCapabilityRegistryError(
            "pinned provider source returned malformed provider truth"
        )
    return normalized


def _resolve_provider(
    provider_id: str,
    *,
    release_root: Path,
    provider_resolver: ProviderResolver | Mapping[str, object] | None,
) -> dict[str, bool] | None:
    if provider_resolver is None:
        return _default_provider_resolver(provider_id, release_root=release_root)
    if isinstance(provider_resolver, Mapping):
        return _provider_truth(provider_resolver.get(provider_id))
    try:
        result = provider_resolver(provider_id)
    except SignificantCapabilityRegistryError:
        raise
    except Exception as error:  # pragma: no cover - defensive resolver boundary
        raise SignificantCapabilityRegistryError(
            f"pinned provider source resolver failed for {provider_id!r}: {error}"
        ) from error
    return _provider_truth(result)


def _provider_truth(value: object) -> dict[str, bool] | None:
    """Accept only the three literal booleans that make a provider claim safe."""

    if not isinstance(value, Mapping):
        return None
    fields = {"exists", "supported", "security_vetted"}
    if set(value) != fields or any(type(value.get(field)) is not bool for field in fields):
        return None
    return {
        "exists": value["exists"] is True,
        "supported": value["supported"] is True,
        "security_vetted": value["security_vetted"] is True,
    }


def _component_identity(component: Mapping[str, object]) -> tuple[object, ...]:
    """Return the class-discriminated identity defined by the Lens contract."""

    component_type = component.get("component_type")
    identity_fields = {
        "capability": ("capability_id",),
        "mcp-tool": ("server_id", "tool_name"),
        "nango-provider": ("provider_id",),
        "source-component": ("component_id",),
    }
    fields = identity_fields.get(component_type)
    if fields is None:
        return (component_type,)
    return (component_type, *(component.get(field) for field in fields))


def _validation_errors(
    payload: object,
    *,
    release_root: Path,
    provider_resolver: ProviderResolver | Mapping[str, object] | None,
) -> list[str]:
    errors: list[str] = []
    try:
        registry = _mapping(payload, context="significant capability registry")
        _exact_fields(
            registry,
            {
                "registry_version",
                "capability_aliases",
                "families",
                "coverage_exceptions",
            },
            context="significant capability registry",
        )
        if registry.get("registry_version") != REGISTRY_VERSION:
            raise SignificantCapabilityRegistryError(
                "significant capability registry has an unsupported registry version"
            )
        candidates, mcp_tools, jobs = _discover_candidates(release_root)
    except SignificantCapabilityRegistryError as error:
        return [str(error)]

    canonical_ids = set(candidates)
    family_ids_seen: set[str] = set()
    alias_seen: dict[str, str] = {}
    capability_aliases = registry.get("capability_aliases")
    if not isinstance(capability_aliases, list):
        errors.append("capability_aliases must be an array")
        capability_aliases = []
    for index, raw_alias in enumerate(capability_aliases):
        try:
            alias = _mapping(raw_alias, context=f"capability alias {index}")
            _exact_fields(
                alias,
                {"alias", "capability_id"},
                context=f"capability alias {index}",
            )
            alias_name = _identifier(alias.get("alias"), context=f"capability alias {index} alias")
            capability_id = _identifier(
                alias.get("capability_id"),
                context=f"capability alias {index} capability_id",
            )
            if alias_name in alias_seen or alias_name in canonical_ids or alias_name in set(_FAMILY_IDS):
                raise SignificantCapabilityRegistryError(f"duplicate or colliding alias {alias_name!r}")
            alias_seen[alias_name] = f"capability alias {index}"
            if capability_id not in canonical_ids:
                raise SignificantCapabilityRegistryError(
                    f"capability alias {index} references unknown capability {capability_id!r}"
                )
        except SignificantCapabilityRegistryError as error:
            errors.append(str(error))

    families = registry.get("families")
    if not isinstance(families, list) or not families:
        errors.append("families must be a non-empty array")
        families = []
    if {str(item.get("family_id")) for item in families if isinstance(item, Mapping)} != set(_FAMILY_IDS):
        errors.append("families must contain exactly the fourteen reviewed family ids")

    covered_ids: set[str] = set()
    component_seen: dict[tuple[object, ...], str] = {}
    emitted_mcp_tools: dict[str, set[str]] = {}
    for index, raw_family in enumerate(families):
        context = f"family {index}"
        try:
            family = _mapping(raw_family, context=context)
            _exact_fields(
                family,
                {
                    "family_id",
                    "title",
                    "outcome",
                    "jobs",
                    "aliases",
                    "member_capability_ids",
                    "components",
                    "assessment",
                },
                context=context,
            )
            family_id = _identifier(family.get("family_id"), context=f"{context} family_id")
            if family_id in family_ids_seen:
                raise SignificantCapabilityRegistryError(f"duplicate family id {family_id!r}")
            family_ids_seen.add(family_id)
            if family_id not in _FAMILY_IDS:
                raise SignificantCapabilityRegistryError(f"unknown family id {family_id!r}")
            _text(family.get("title"), context=f"{context} title", max_length=140)
            _text(family.get("outcome"), context=f"{context} outcome", max_length=800)

            family_jobs = tuple(
                _identifier(item, context=f"{context} jobs item")
                for item in _text_list(family.get("jobs"), context=f"{context} jobs")
            )
            _unique(family_jobs, context=f"{context} jobs")
            unknown_jobs = sorted(set(family_jobs) - jobs)
            if unknown_jobs:
                raise SignificantCapabilityRegistryError(f"{context} has unknown job(s): {', '.join(unknown_jobs)}")

            family_aliases = tuple(
                _identifier(item, context=f"{context} aliases item")
                for item in _text_list(family.get("aliases"), context=f"{context} aliases", allow_empty=True)
            )
            _unique(family_aliases, context=f"{context} aliases")
            for alias_name in family_aliases:
                if alias_name in alias_seen or alias_name in canonical_ids or alias_name in set(_FAMILY_IDS):
                    raise SignificantCapabilityRegistryError(f"duplicate or colliding alias {alias_name!r}")
                alias_seen[alias_name] = context

            members = tuple(
                _identifier(item, context=f"{context} member_capability_ids item")
                for item in _text_list(
                    family.get("member_capability_ids"),
                    context=f"{context} member_capability_ids",
                )
            )
            _unique(members, context=f"{context} member_capability_ids")
            unknown_members = sorted(set(members) - canonical_ids)
            if unknown_members:
                raise SignificantCapabilityRegistryError(
                    f"{context} has unknown member capability {', '.join(unknown_members)}"
                )
            covered_ids.update(members)

            components = family.get("components")
            if not isinstance(components, list) or not components:
                raise SignificantCapabilityRegistryError(f"{context} components must be a non-empty array")
            family_component_seen: set[tuple[object, ...]] = set()
            for component_index, raw_component in enumerate(components):
                component_context = f"{context} component {component_index}"
                component = _mapping(raw_component, context=component_context)
                component_type = component.get("component_type")
                if component_type not in _COMPONENT_TYPES:
                    raise SignificantCapabilityRegistryError(f"{component_context} has unknown component type")
                identity = _component_identity(component)
                identity_is_hashable = all(isinstance(value, str) for value in identity)
                if identity_is_hashable and (
                    identity in family_component_seen or identity in component_seen
                ):
                    raise SignificantCapabilityRegistryError(f"duplicate component in {component_context}")
                if component_type == "capability":
                    _exact_fields(
                        component,
                        {"component_type", "capability_id"},
                        context=component_context,
                    )
                    component_id = _identifier(
                        component.get("capability_id"),
                        context=f"{component_context} capability_id",
                    )
                    if component_id not in canonical_ids:
                        raise SignificantCapabilityRegistryError(
                            f"{component_context} references unknown capability {component_id!r}"
                        )
                    if component_id not in members:
                        raise SignificantCapabilityRegistryError(
                            f"{component_context} capability is not a family member"
                        )
                elif component_type == "mcp-tool":
                    _exact_fields(
                        component,
                        {"component_type", "server_id", "tool_name"},
                        context=component_context,
                    )
                    server_id = _identifier(
                        component.get("server_id"),
                        context=f"{component_context} server_id",
                    )
                    tool_name = _text(
                        component.get("tool_name"),
                        context=f"{component_context} tool_name",
                        max_length=128,
                    )
                    if _TOOL_RE.fullmatch(tool_name) is None:
                        raise SignificantCapabilityRegistryError(
                            f"{component_context} tool_name is not a valid MCP tool"
                        )
                    if server_id not in mcp_tools:
                        raise SignificantCapabilityRegistryError(
                            f"{component_context} references unknown MCP server {server_id!r}"
                        )
                    if tool_name not in mcp_tools[server_id]:
                        raise SignificantCapabilityRegistryError(
                            f"{component_context} references unknown MCP tool {server_id}/{tool_name}"
                        )
                    if server_id not in members:
                        raise SignificantCapabilityRegistryError(
                            f"{component_context} MCP server is not a family member"
                        )
                    emitted_mcp_tools.setdefault(server_id, set()).add(tool_name)
                elif component_type == "nango-provider":
                    _exact_fields(
                        component,
                        {
                            "component_type",
                            "provider_id",
                            "source_package",
                            "source_version",
                            "dex_support",
                            "security_vetted",
                        },
                        context=component_context,
                    )
                    provider_id = _identifier(
                        component.get("provider_id"),
                        context=f"{component_context} provider_id",
                    )
                    if component.get("source_package") != PROVIDER_SOURCE_PACKAGE:
                        raise SignificantCapabilityRegistryError(
                            f"{component_context} source_package must be {PROVIDER_SOURCE_PACKAGE!r}"
                        )
                    if component.get("source_version") != PROVIDER_SOURCE_VERSION:
                        raise SignificantCapabilityRegistryError(
                            f"{component_context} source_version must be {PROVIDER_SOURCE_VERSION!r}"
                        )
                    if component.get("dex_support") not in {"supported", "unsupported"}:
                        raise SignificantCapabilityRegistryError(
                            f"{component_context} dex_support is not a closed value"
                        )
                    if type(component.get("security_vetted")) is not bool:
                        raise SignificantCapabilityRegistryError(f"{component_context} security_vetted must be boolean")
                    provider_truth = _resolve_provider(
                        provider_id,
                        release_root=release_root,
                        provider_resolver=provider_resolver,
                    )
                    if provider_truth is None or provider_truth["exists"] is not True:
                        raise SignificantCapabilityRegistryError(
                            f"{component_context} references unknown provider {provider_id!r}"
                        )
                    expected_support = "supported" if provider_truth["supported"] else "unsupported"
                    if component.get("dex_support") != expected_support:
                        raise SignificantCapabilityRegistryError(
                            f"{component_context} dex_support does not match authoritative provider truth"
                        )
                    if component.get("security_vetted") is not provider_truth["security_vetted"]:
                        raise SignificantCapabilityRegistryError(
                            f"{component_context} security_vetted does not match authoritative provider truth"
                        )
                else:
                    _exact_fields(
                        component,
                        {"component_type", "component_id"},
                        context=component_context,
                    )
                    _source_component_id(
                        component.get("component_id"),
                        context=f"{component_context} component_id",
                    )

                identity = _component_identity(component)
                if not identity_is_hashable and (
                    identity in family_component_seen or identity in component_seen
                ):
                    raise SignificantCapabilityRegistryError(f"duplicate component in {component_context}")
                family_component_seen.add(identity)
                component_seen[identity] = component_context

            assessment = _mapping(family.get("assessment"), context=f"{context} assessment")
            mode = assessment.get("mode")
            if mode == "automatic":
                _exact_fields(
                    assessment,
                    {"mode", "profile"},
                    context=f"{context} assessment",
                )
                profile = assessment.get("profile")
                if profile not in _ASSESSMENT_PROFILES:
                    raise SignificantCapabilityRegistryError(f"{context} assessment profile is unknown")
            elif mode == "manual-only":
                _exact_fields(
                    assessment,
                    {"mode", "reason"},
                    context=f"{context} assessment",
                )
                _text(
                    assessment.get("reason"),
                    context=f"{context} assessment reason",
                    max_length=800,
                )
            else:
                raise SignificantCapabilityRegistryError(f"{context} assessment mode is malformed")
        except SignificantCapabilityRegistryError as error:
            errors.append(str(error))

    exceptions = registry.get("coverage_exceptions")
    exception_ids: set[str] = set()
    if not isinstance(exceptions, list):
        errors.append("coverage_exceptions must be an array")
        exceptions = []
    for index, raw_exception in enumerate(exceptions):
        context = f"coverage exception {index}"
        try:
            exception = _mapping(raw_exception, context=context)
            _exact_fields(
                exception,
                {"capability_id", "reason"},
                context=context,
            )
            capability_id = _identifier(
                exception.get("capability_id"),
                context=f"{context} capability_id",
            )
            if capability_id in exception_ids:
                raise SignificantCapabilityRegistryError(f"duplicate coverage exception {capability_id!r}")
            exception_ids.add(capability_id)
            candidate = candidates.get(capability_id)
            if candidate is None:
                raise SignificantCapabilityRegistryError(
                    f"coverage exception references unknown capability {capability_id!r}"
                )
            if candidate["availability"] != "active" or candidate["impact_tier"] not in {
                "core",
                "high",
            }:
                raise SignificantCapabilityRegistryError(
                    f"coverage exception {capability_id!r} must target an active core/high capability"
                )
            _text(exception.get("reason"), context=f"{context} reason", max_length=800)
        except SignificantCapabilityRegistryError as error:
            errors.append(str(error))

    if set(family_ids_seen) == set(_FAMILY_IDS):
        all_mcp_ids = set(mcp_tools)
        for server_id, expected_tools in mcp_tools.items():
            actual_tools = emitted_mcp_tools.get(server_id, set())
            missing_tools = sorted(set(expected_tools) - actual_tools)
            extra_tools = sorted(actual_tools - set(expected_tools))
            if missing_tools or extra_tools:
                details: list[str] = []
                if missing_tools:
                    details.append("missing " + ", ".join(missing_tools))
                if extra_tools:
                    details.append("unknown " + ", ".join(extra_tools))
                errors.append(f"MCP tool coverage mismatch for {server_id}: " + "; ".join(details))
        missing_mcp = sorted(all_mcp_ids - covered_ids - exception_ids)
        if missing_mcp:
            errors.append("MCP servers are not mapped to a family or reviewed exception: " + ", ".join(missing_mcp))
        active_core_high = {
            capability_id
            for capability_id, candidate in candidates.items()
            if candidate["availability"] == "active" and candidate["impact_tier"] in {"core", "high"}
        }
        uncovered = sorted(active_core_high - covered_ids - exception_ids)
        if uncovered:
            errors.append(
                "active core/high capability is neither family-covered nor explicitly excepted: " + ", ".join(uncovered)
            )
    return errors


def iter_significant_registry_errors(
    payload: object,
    *,
    release_root: Path | None = None,
    provider_resolver: ProviderResolver | Mapping[str, object] | None = None,
) -> Iterator[str]:
    """Yield all validation errors without raising on the first one."""

    root = (release_root or REPO_ROOT).resolve()
    yield from _validation_errors(
        payload,
        release_root=root,
        provider_resolver=provider_resolver,
    )


def validate_significant_capability_registry(
    payload: object,
    *,
    release_root: Path | None = None,
    provider_resolver: ProviderResolver | Mapping[str, object] | None = None,
) -> None:
    """Validate one in-memory registry, raising one fail-closed error."""

    errors = tuple(
        iter_significant_registry_errors(
            payload,
            release_root=release_root,
            provider_resolver=provider_resolver,
        )
    )
    if errors:
        raise SignificantCapabilityRegistryError("; ".join(errors))


def load_significant_capability_registry(
    release_root: Path | None = None,
    *,
    registry_path: Path | None = None,
    provider_resolver: ProviderResolver | Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Load and validate the canonical registry from a release tree."""

    root = (release_root or REPO_ROOT).resolve()
    path = registry_path or (root / REGISTRY_PATH.relative_to(REPO_ROOT))
    if not path.is_absolute():
        path = root / path
    payload = _strict_json(path)
    validate_significant_capability_registry(
        payload,
        release_root=root,
        provider_resolver=provider_resolver,
    )
    return dict(_mapping(payload, context=str(path)))


# Short aliases make the boundary convenient for release-path callers while
# retaining the explicit names used by focused tests and code review.
load_registry = load_significant_capability_registry
validate_registry = validate_significant_capability_registry


__all__ = [
    "CATALOG_REGISTRY_PATH",
    "ENRICHED_REGISTRY_PATH",
    "PROVIDER_SOURCE_PACKAGE",
    "PROVIDER_SOURCE_VERSION",
    "REGISTRY_PATH",
    "SignificantCapabilityRegistryError",
    "iter_significant_registry_errors",
    "load_registry",
    "load_significant_capability_registry",
    "validate_registry",
    "validate_significant_capability_registry",
]
