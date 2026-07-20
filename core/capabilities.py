"""Registry-backed state and provisioning for optional Dex capability rooms.

The generated portable-vault contract is the only room manifest.  This module
adds user state from ``System/user-profile.yaml`` and a generic provisioning
convention; it deliberately contains no room-specific folder, skill, MCP, or
feature lists.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT_PATH = (
    REPO_ROOT / "packages/dex-contracts/dist/portable-vault.contract.json"
)
DORMANT_CATALOG = Path(".claude/skills/_available/capabilities")


class CapabilityError(ValueError):
    """Base error for invalid capability registry or profile state."""


class UnknownCapability(CapabilityError):
    """Raised when a room is not declared by the portable contract."""


def _load_contract(contract_path: Path | str | None = None) -> dict[str, Any]:
    path = Path(contract_path or DEFAULT_CONTRACT_PATH)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityError(f"Could not read capability registry: {path}") from exc
    registry = parsed.get("capabilities")
    if not isinstance(registry, dict):
        raise CapabilityError("Portable contract has no capabilities registry")
    return parsed


def room_ids(*, contract_path: Path | str | None = None) -> tuple[str, ...]:
    """Return capability ids exactly as declared by the portable contract."""
    registry = _load_contract(contract_path)["capabilities"]
    return tuple(registry)


def surfaces_for(
    room: str,
    *,
    contract_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return a copy of one room's contract-declared surfaces."""
    registry = _load_contract(contract_path)["capabilities"]
    surfaces = registry.get(room)
    if not isinstance(surfaces, dict):
        raise UnknownCapability(f"Unknown capability room: {room}")
    return json.loads(json.dumps(surfaces))


def _read_profile(
    profile_path: Path | str,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    path = Path(profile_path)
    if not path.exists():
        return {}
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        if strict:
            raise CapabilityError(f"Could not safely read profile: {path}") from exc
        return {}
    if not isinstance(parsed, dict):
        if strict:
            raise CapabilityError(f"Profile must contain an object: {path}")
        return {}
    return parsed


def enabled(
    room: str,
    *,
    profile_path: Path | str | None = None,
    contract_path: Path | str | None = None,
) -> bool:
    """Answer whether ``room`` is enabled, failing safely to the contract default.

    ``quarter_goals`` has one backward-compatible read path: when the new key is
    absent, legacy ``quarterly_planning.enabled`` is honored.  Any explicit new
    value wins.  Writes are one-way through :func:`set_enabled`, which creates
    the new key and keeps the old config switch aligned for legacy consumers.
    """
    surfaces = surfaces_for(room, contract_path=contract_path)
    path = Path(profile_path or REPO_ROOT / "System/user-profile.yaml")
    profile = _read_profile(path)
    capability_state = profile.get("capabilities")
    room_state = (
        capability_state.get(room) if isinstance(capability_state, Mapping) else None
    )
    if isinstance(room_state, Mapping) and isinstance(room_state.get("enabled"), bool):
        return room_state["enabled"]

    legacy_config = surfaces.get("config")
    if isinstance(legacy_config, str):
        legacy = profile.get(legacy_config)
        if isinstance(legacy, Mapping) and isinstance(legacy.get("enabled"), bool):
            return legacy["enabled"]

    default = surfaces.get("default_enabled", False)
    return default if isinstance(default, bool) else False


def _within(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise CapabilityError(f"Capability path escapes vault: {relative_path}") from exc
    return candidate


def _copy_missing(source: Path, target: Path, created: list[str], vault_root: Path) -> None:
    if source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            _copy_missing(child, target / child.name, created, vault_root)
        return
    if source.is_file() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        created.append(target.relative_to(vault_root).as_posix())


def _preflight_room_assets(
    root: Path,
    room: str,
    surfaces: Mapping[str, Any],
) -> Path:
    dormant = _within(root, (DORMANT_CATALOG / room).as_posix())
    for skill in surfaces.get("skills", []):
        source = dormant / "skills" / str(skill)
        if not source.is_dir():
            raise CapabilityError(
                f"Dormant skill is missing for {room}: {source.relative_to(root)}"
            )
    return dormant


def reconcile_room(
    room: str,
    room_enabled: bool,
    *,
    vault_root: Path | str,
    contract_path: Path | str | None = None,
) -> dict[str, Any]:
    """Surface or hide a room without ever deleting its user-owned folders."""
    if not isinstance(room_enabled, bool):
        raise CapabilityError("enabled state must be true or false")
    root = Path(vault_root).resolve()
    surfaces = surfaces_for(room, contract_path=contract_path)
    dormant = (
        _preflight_room_assets(root, room, surfaces)
        if room_enabled
        else _within(root, (DORMANT_CATALOG / room).as_posix())
    )
    created: list[str] = []
    surfaced: list[str] = []
    hidden: list[str] = []

    if room_enabled:
        for relative_folder in surfaces.get("folders", []):
            target = _within(root, str(relative_folder))
            source = dormant / "folders" / str(relative_folder)
            existed = target.exists()
            target.mkdir(parents=True, exist_ok=True)
            if not existed:
                created.append(target.relative_to(root).as_posix())
            _copy_missing(source, target, created, root)

        for skill in surfaces.get("skills", []):
            source = dormant / "skills" / str(skill)
            target = _within(root, f".claude/skills/{skill}")
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            surfaced.append(target.relative_to(root).as_posix())
    else:
        # Capability folders are vault-owned user content.  They are intentionally
        # left untouched.  Only release-owned active skill copies are unsurfaced.
        for skill in surfaces.get("skills", []):
            target = _within(root, f".claude/skills/{skill}")
            if target.exists():
                shutil.rmtree(target)
                hidden.append(target.relative_to(root).as_posix())

    return {
        "room": room,
        "enabled": room_enabled,
        "created": created,
        "skills_surfaced": surfaced,
        "skills_hidden": hidden,
        "user_content_deleted": False,
    }


def reconcile_all(
    vault_root: Path | str,
    *,
    profile_path: Path | str | None = None,
    contract_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Reconcile every contract-declared room against the current profile."""
    root = Path(vault_root).resolve()
    profile = Path(profile_path or root / "System/user-profile.yaml")
    return [
        reconcile_room(
            room,
            enabled(room, profile_path=profile, contract_path=contract_path),
            vault_root=root,
            contract_path=contract_path,
        )
        for room in room_ids(contract_path=contract_path)
    ]


def _atomic_yaml_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def set_enabled(
    room: str,
    room_enabled: bool,
    *,
    vault_root: Path | str,
    profile_path: Path | str | None = None,
    contract_path: Path | str | None = None,
) -> dict[str, Any]:
    """Persist one room state and immediately reconcile its surfaced assets."""
    if not isinstance(room_enabled, bool):
        raise CapabilityError("enabled state must be true or false")
    surfaces = surfaces_for(room, contract_path=contract_path)
    root = Path(vault_root).resolve()
    if room_enabled:
        # Fail before changing profile state or creating the room when a shipped
        # release asset is incomplete.
        _preflight_room_assets(root, room, surfaces)
    profile_file = Path(profile_path or root / "System/user-profile.yaml")
    # Reads may fail safely to "off", but mutations must never replace malformed
    # or unreadable user state with an empty profile.
    profile = _read_profile(profile_file, strict=True)
    capabilities = profile.setdefault("capabilities", {})
    if not isinstance(capabilities, dict):
        raise CapabilityError("profile capabilities must be an object")
    state = capabilities.setdefault(room, {})
    if not isinstance(state, dict):
        state = {}
        capabilities[room] = state
    state["enabled"] = room_enabled

    legacy_config = surfaces.get("config")
    if isinstance(legacy_config, str):
        legacy = profile.setdefault(legacy_config, {})
        if not isinstance(legacy, dict):
            legacy = {}
            profile[legacy_config] = legacy
        legacy["enabled"] = room_enabled

    _atomic_yaml_write(profile_file, profile)
    return reconcile_room(
        room,
        room_enabled,
        vault_root=root,
        contract_path=contract_path,
    )


def _main() -> int:
    parser = argparse.ArgumentParser(description="Turn Dex capability rooms on or off")
    parser.add_argument("room", nargs="?")
    parser.add_argument("state", nargs="?", choices=("on", "off"))
    parser.add_argument(
        "--list",
        action="store_true",
        help="List room ids from the portable contract registry",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Refresh surfaced room assets from the current profile",
    )
    parser.add_argument(
        "--vault",
        default=os.environ.get("VAULT_PATH", str(REPO_ROOT)),
        help="Dex vault root (defaults to VAULT_PATH or this checkout)",
    )
    args = parser.parse_args()
    if args.list:
        print(json.dumps({"rooms": room_ids()}, indent=2))
        return 0
    if args.reconcile:
        results = reconcile_all(Path(args.vault))
        print(json.dumps({"rooms": results}, indent=2))
        return 0
    if args.room is None or args.state is None:
        parser.error("room and state are required unless --list or --reconcile is used")
    result = set_enabled(args.room, args.state == "on", vault_root=Path(args.vault))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
