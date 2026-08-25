"""Versioned, data-driven descriptors for the harnesses Dex can meet.

The JSON registry is deliberately the source consumed by non-Python launchers
as well as this small Python convenience API.  A descriptor describes what a
harness actually exposes; it does not turn an unverified integration into a
promise of parity.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = Path(__file__).with_name("registry.json")
PROFILES_PATH = Path(__file__).with_name("profiles")
REGISTRY_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class CapabilityRow:
    """One JSON-safe capability result for a harness."""

    id: str
    status: str
    tier: int
    notes: str = ""
    mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": self.id,
            "status": self.status,
            "tier": self.tier,
            "mode": self.mode or _default_mode(self.status),
        }
        if self.notes:
            row["notes"] = self.notes
        return row


@dataclass(frozen=True)
class CapabilityProfile:
    """Immutable view of one registry descriptor."""

    id: str
    name: str
    vendor: str
    summary: str
    support_level: str
    capabilities: tuple[CapabilityRow, ...]
    modes: tuple[str, ...]
    detection: Mapping[str, tuple[str, ...]]
    adapter: Mapping[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()

    @property
    def display_name(self) -> str:
        """Compatibility alias used by provisioning/report consumers."""
        return self.name

    def capability_rows(self) -> tuple[dict[str, Any], ...]:
        """Return independent dictionaries suitable for JSON or reports."""
        return tuple(row.to_dict() for row in self.capabilities)

    def to_dict(self) -> dict[str, Any]:
        """Return a deep, JSON-serializable descriptor copy."""
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "vendor": self.vendor,
            "summary": self.summary,
            "support_level": self.support_level,
            "capabilities": list(self.capability_rows()),
            "modes": list(self.modes),
            "detection": {key: list(values) for key, values in self.detection.items()},
            "adapter": copy_json(self.adapter),
            "limitations": list(self.limitations),
            "evidence": list(self.evidence),
        }


def _tuple_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)


def copy_json(value: Any) -> Any:
    """Copy registry data without exposing mutable loader state."""
    return json.loads(json.dumps(value, sort_keys=True))


def _default_mode(status: str) -> str:
    if status == "scheduled":
        return "automatic"
    if status in {"partial", "companion", "internal"}:
        return "guided"
    if status in {"none", "not-verified"}:
        return "unavailable"
    return "on_demand"


def _normalise_rows(value: Any) -> tuple[CapabilityRow, ...]:
    rows: list[CapabilityRow] = []
    if isinstance(value, Mapping):
        items = [
            {"id": key, **(entry if isinstance(entry, Mapping) else {"status": entry})}
            for key, entry in value.items()
        ]
    elif isinstance(value, list):
        items = value
    else:
        items = []
    for entry in items:
        if not isinstance(entry, Mapping):
            continue
        identifier = entry.get("id")
        status = entry.get("status")
        if not isinstance(identifier, str) or not identifier:
            continue
        if not isinstance(status, str) or not status:
            status = "not-verified"
        tier = entry.get("tier", 0)
        if isinstance(tier, bool) or not isinstance(tier, int) or tier < 0:
            tier = 0
        notes = entry.get("notes", "")
        mode = entry.get("mode", "")
        if not isinstance(mode, str) or mode not in {"automatic", "on_demand", "guided", "unavailable"}:
            mode = _default_mode(status)
        rows.append(CapabilityRow(identifier, status, tier, notes if isinstance(notes, str) else "", mode))
    return tuple(rows)


def _profile_from_dict(payload: Mapping[str, Any]) -> CapabilityProfile:
    identifier = payload.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("harness descriptor has no id")
    name = payload.get("name", identifier)
    vendor = payload.get("vendor", "")
    summary = payload.get("summary", payload.get("description", ""))
    support = payload.get("support_level", "not-verified")
    for field_name, value in (("name", name), ("vendor", vendor), ("summary", summary), ("support_level", support)):
        if not isinstance(value, str):
            raise ValueError(f"harness descriptor {identifier!r} has non-string {field_name}")
    detection_value = payload.get("detection", {})
    detection: dict[str, tuple[str, ...]] = {}
    if isinstance(detection_value, Mapping):
        for key, value in detection_value.items():
            if isinstance(key, str):
                detection[key] = _tuple_strings(value)
    return CapabilityProfile(
        id=identifier,
        name=name,
        vendor=vendor,
        summary=summary,
        support_level=support,
        capabilities=_normalise_rows(payload.get("capabilities", payload.get("capability_rows"))),
        modes=_tuple_strings(payload.get("modes")),
        detection=detection,
        adapter=copy_json(payload.get("adapter", {})) if isinstance(payload.get("adapter", {}), Mapping) else {},
        limitations=_tuple_strings(payload.get("limitations")),
        evidence=_tuple_strings(payload.get("evidence")),
    )


def _load_profiles() -> tuple[CapabilityProfile, ...]:
    try:
        payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Cannot load harness registry: {REGISTRY_PATH}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise RuntimeError(f"Unsupported harness registry schema: {REGISTRY_PATH}")
    entries = payload.get("profiles")
    if not isinstance(entries, list):
        raise RuntimeError("Harness registry profiles must be an array")
    profiles = tuple(_profile_from_dict(entry) for entry in entries if isinstance(entry, Mapping))
    if len({profile.id for profile in profiles}) != len(profiles):
        raise RuntimeError("Harness registry contains duplicate ids")
    if tuple(profile.id for profile in profiles) != tuple(sorted(profile.id for profile in profiles)):
        raise RuntimeError("Harness registry profiles must be sorted by id")
    return profiles


def list_profiles() -> tuple[CapabilityProfile, ...]:
    """Return all known descriptors in deterministic id order."""
    return _load_profiles()


def get_profile(profile_id: str) -> CapabilityProfile:
    """Return one descriptor, raising ``KeyError`` for an unknown id."""
    if not isinstance(profile_id, str) or not profile_id:
        raise KeyError(profile_id)
    for profile in list_profiles():
        if profile.id == profile_id:
            return profile
    raise KeyError(profile_id)


def _normalise_explicit(explicit: str | Iterable[str] | None) -> tuple[str, ...]:
    if explicit is None:
        return ()
    values = (explicit.split(",") if isinstance(explicit, str) else explicit)
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise TypeError("explicit harness ids must be strings")
        # CLI ``--explicit`` is repeatable, while callers may pass a single
        # comma-separated string or a mixed list of both forms.
        for candidate in value.split(","):
            identifier = candidate.strip()
            if not identifier:
                continue
            if identifier not in result:
                result.append(identifier)
    return tuple(result)


def _path_values(paths: Iterable[Path | str] | Path | str | None) -> tuple[str, ...]:
    if paths is None:
        return ()
    if isinstance(paths, (Path, str)):
        paths = (paths,)
    result: list[str] = []
    for path in paths:
        if isinstance(path, Path):
            result.append(path.as_posix())
        elif isinstance(path, str):
            result.append(path)
    return tuple(result)


def detect_harnesses(
    env: Mapping[str, str] | None = None,
    paths: Iterable[Path | str] | Path | str | None = None,
    explicit: str | Iterable[str] | None = None,
    *,
    explicit_ids: str | Iterable[str] | None = None,
) -> tuple[CapabilityProfile, ...]:
    """Detect harnesses from explicit ids, environment markers, or paths.

    Detection is advisory and deterministic: explicit ids win, while automatic
    detection returns profiles in registry order and never invents a fallback.
    """
    requested = _normalise_explicit(explicit if explicit is not None else explicit_ids)
    if requested:
        return tuple(get_profile(identifier) for identifier in requested)
    environment = env if env is not None else os.environ
    marker_values = {str(key).upper(): str(value) for key, value in environment.items()}
    path_values = _path_values(paths)
    lowered_paths = tuple(value.lower() for value in path_values)
    detected: list[CapabilityProfile] = []
    for profile in list_profiles():
        env_markers = profile.detection.get("env", ())
        path_markers = profile.detection.get("paths", ())
        env_hit = any(marker.upper() in marker_values for marker in env_markers)
        path_hit = any(marker.lower() in path for marker in path_markers for path in lowered_paths)
        if env_hit or path_hit:
            detected.append(profile)
    return tuple(detected)


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Inspect Dex harness capability descriptors.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list", help="list all known harnesses")
    list_parser.add_argument("--format", choices=("json", "ids"), default="json")
    detect_parser = subparsers.add_parser("detect", help="detect harnesses from markers")
    detect_parser.add_argument("--format", choices=("json", "ids"), default="json")
    detect_parser.add_argument("--explicit", action="append", help="explicit id (repeatable or comma-separated)")
    detect_parser.add_argument("--path", action="append", help="path marker (repeatable)")
    args = parser.parse_args()
    if args.command == "list":
        profiles = list_profiles()
    else:
        explicit = args.explicit or None
        profiles = detect_harnesses(explicit=explicit, paths=args.path or None)
    if args.format == "ids":
        print(json.dumps([profile.id for profile in profiles], separators=(",", ":")))
    else:
        print(json.dumps([profile.to_dict() for profile in profiles], sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
