"""Registry-backed state and provisioning for optional Dex capability rooms.

The generated portable-vault contract is the only room manifest.  This module
adds user state from ``System/user-profile.yaml`` and a generic provisioning
convention; it deliberately contains no room-specific folder, skill, MCP, or
feature lists.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    from core.lens_catalog_sources import (
        SkillSourceError,
        SkillSourcePin,
        resolve_room_skill_sources,
    )
except ModuleNotFoundError as error:  # direct ``python core/capabilities.py`` entrypoint
    if error.name != "core":
        raise
    from lens_catalog_sources import (  # type: ignore[no-redef]
        SkillSourceError,
        SkillSourcePin,
        resolve_room_skill_sources,
    )

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT_PATH = REPO_ROOT / "packages/dex-contracts/dist/portable-vault.contract.json"
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
    import yaml

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
    room_state = capability_state.get(room) if isinstance(capability_state, Mapping) else None
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


def _lexical_target(root: Path, relative_path: str, *, kind: str) -> Path:
    """Resolve a vault-relative target without following any path component."""
    relative = Path(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise CapabilityError(f"Capability path is not a safe relative path: {relative_path}")
    target = root.joinpath(*relative.parts)
    cursor = root
    for index, part in enumerate(relative.parts):
        cursor = cursor / part
        final = index == len(relative.parts) - 1
        if cursor.is_symlink():
            raise CapabilityError(f"Capability target contains a symlink: {relative.as_posix()}")
        if not cursor.exists():
            continue
        expects_directory = not final or kind == "directory"
        if expects_directory and not cursor.is_dir():
            raise CapabilityError(
                f"Capability target ancestor is not a directory: {relative.as_posix()}"
            )
        if final and kind == "file" and not cursor.is_file():
            raise CapabilityError(f"Capability target is not a regular file: {relative.as_posix()}")
    return target


def _preflight_seed_overlay(source: Path, target: Path, root: Path) -> None:
    """Prove a write-if-absent overlay can complete before any mutation."""
    if source.is_symlink():
        raise CapabilityError(f"Dormant room asset is a symlink: {source}")
    if source.is_dir():
        _lexical_target(
            root,
            target.relative_to(root).as_posix(),
            kind="directory",
        )
        try:
            children = sorted(source.iterdir(), key=lambda child: child.name)
        except OSError as error:
            raise CapabilityError(f"Dormant room asset cannot be inspected: {source}") from error
        for child in children:
            _preflight_seed_overlay(child, target / child.name, root)
        return
    if source.is_file():
        _lexical_target(
            root,
            target.relative_to(root).as_posix(),
            kind="file",
        )
        return
    raise CapabilityError(f"Dormant room asset is missing or unsafe: {source}")


def _atomic_bytes_write(path: Path, payload: bytes) -> None:
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


@dataclass(frozen=True)
class _UndoMutation:
    kind: str
    path: Path
    payload: bytes | None = None
    expected: bytes | None = None


class _MutationJournal:
    """A bounded undo log for release-owned room mutations."""

    def __init__(self) -> None:
        self._actions: list[_UndoMutation] = []

    def created_directory(self, path: Path) -> None:
        self._actions.append(_UndoMutation("remove-directory", path))

    def created_file(self, path: Path, payload: bytes) -> None:
        self._actions.append(_UndoMutation("remove-file", path, payload=payload))

    def replaced_file(self, path: Path, original: bytes, replacement: bytes) -> None:
        self._actions.append(
            _UndoMutation(
                "restore-file",
                path,
                payload=original,
                expected=replacement,
            )
        )

    def removed_skill(self, target: Path, payload: bytes) -> None:
        # Rollback runs in reverse: restore the directory, then its one pinned file.
        self._actions.append(
            _UndoMutation("restore-file", target / "SKILL.md", payload=payload)
        )
        self._actions.append(_UndoMutation("restore-directory", target))

    def rollback(self) -> None:
        errors: list[str] = []
        for action in reversed(self._actions):
            try:
                self._undo(action)
            except Exception as error:  # preserve every unsafe or concurrent change
                errors.append(f"{action.path}: {error}")
        if errors:
            raise CapabilityError("room rollback could not safely restore: " + "; ".join(errors))

    @staticmethod
    def _undo(action: _UndoMutation) -> None:
        path = action.path
        if action.kind == "remove-file":
            if not path.exists():
                return
            if path.is_symlink() or not path.is_file() or path.read_bytes() != action.payload:
                raise CapabilityError("created file changed before rollback")
            path.unlink()
            return
        if action.kind == "remove-directory":
            if not path.exists():
                return
            if path.is_symlink() or not path.is_dir():
                raise CapabilityError("created directory changed before rollback")
            path.rmdir()
            return
        if action.kind == "restore-directory":
            if path.exists():
                if path.is_symlink() or not path.is_dir():
                    raise CapabilityError("removed directory target became unsafe")
                return
            path.mkdir()
            return
        if action.kind == "restore-file":
            if action.payload is None:
                raise CapabilityError("rollback payload is missing")
            if path.exists():
                if path.is_symlink() or not path.is_file():
                    raise CapabilityError("replaced file target became unsafe")
                current = path.read_bytes()
                if current == action.payload:
                    return
                if action.expected is None or current != action.expected:
                    raise CapabilityError("replaced file changed before rollback")
            _atomic_bytes_write(path, action.payload)
            return
        raise CapabilityError(f"unknown rollback action: {action.kind}")


def _mkdir_with_mutation_receipt(
    target: Path,
    mutation_paths: list[str],
    vault_root: Path,
    journal: _MutationJournal,
) -> None:
    missing: list[Path] = []
    cursor = target
    while cursor != vault_root and not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    for path in reversed(missing):
        path.mkdir()
        journal.created_directory(path)
        mutation_paths.append(path.relative_to(vault_root).as_posix())


def _copy_missing(
    source: Path,
    target: Path,
    created: list[str],
    mutation_paths: list[str],
    vault_root: Path,
    journal: _MutationJournal,
) -> None:
    if source.is_dir():
        _mkdir_with_mutation_receipt(target, mutation_paths, vault_root, journal)
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            _copy_missing(
                child,
                target / child.name,
                created,
                mutation_paths,
                vault_root,
                journal,
            )
        return
    if source.is_file() and not target.exists():
        _mkdir_with_mutation_receipt(
            target.parent,
            mutation_paths,
            vault_root,
            journal,
        )
        payload = source.read_bytes()
        _atomic_bytes_write(target, payload)
        journal.created_file(target, payload)
        relative = target.relative_to(vault_root).as_posix()
        created.append(relative)
        mutation_paths.append(relative)


def _dormant_root(room: str, vault_root: Path) -> Path:
    """The room's dormant assets ship with the BRAIN (the installed code
    tree): skills are release-owned, and sourcing them from the code install
    means a vault can never shadow a shipped dormant skill. In today's
    combined layout the two roots coincide; under the Brain/Vault split the
    brain remains the correct source. A vault-local catalog is honored ONLY
    when the brain does not ship that room at all (test fixtures, dev
    vaults) — whenever the brain has the room, the brain wins."""
    brain = REPO_ROOT / DORMANT_CATALOG / room
    if brain.is_dir():
        return brain
    return _within(vault_root, (DORMANT_CATALOG / room).as_posix())


def _room_release_root(room: str, vault_root: Path) -> Path:
    """Return the release tree that owns one room's dormant skill payloads."""
    brain = REPO_ROOT / DORMANT_CATALOG / room
    return REPO_ROOT.resolve() if brain.is_dir() else vault_root.resolve()


def _tracked_file_differs_from_head(root: Path, relative: Path) -> bool | None:
    """Compare one tracked file by Git object id without loading its contents."""
    git = next(
        (
            candidate
            for candidate in (Path("/usr/bin/git"), Path("/bin/git"))
            if candidate.is_file() and not candidate.is_symlink()
        ),
        None,
    )
    if git is None:
        return None
    command_prefix = [
        str(git),
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "core.excludesFile=/dev/null",
        "-C",
        str(root),
    ]
    env = {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/var/empty" if Path("/var/empty").is_dir() else "/",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
    }
    relative_text = relative.as_posix()
    try:
        tracked = subprocess.run(
            [*command_prefix, "ls-tree", "HEAD", "--", relative_text],
            capture_output=True,
            env=env,
            text=True,
            timeout=3,
            check=False,
        )
        metadata, separator, _path = tracked.stdout.partition("\t")
        fields = metadata.split()
        if tracked.returncode != 0 or not separator or len(fields) != 3:
            return None
        expected = fields[2]
        current = subprocess.run(
            [
                *command_prefix,
                "hash-object",
                "--no-filters",
                "--",
                relative_text,
            ],
            capture_output=True,
            env=env,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if current.returncode != 0:
        return None
    return current.stdout.strip() != expected


def _room_has_user_content(
    root: Path,
    room: str,
    surfaces: Mapping[str, Any],
) -> bool:
    """Detect room use without mistaking untouched shipped seeds for user work."""
    dormant = _dormant_root(room, root)
    for relative_folder in surfaces.get("folders", []):
        folder = _within(root, str(relative_folder))
        if folder.is_symlink() or not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_symlink() or not path.is_file() or path.name in {".DS_Store", ".gitkeep"}:
                continue
            relative = path.relative_to(root)
            shipped = dormant / "folders" / relative
            if not shipped.exists():
                return True
            if shipped.is_symlink() or not shipped.is_file():
                continue
            tracked_difference = _tracked_file_differs_from_head(
                root,
                relative,
            )
            if tracked_difference is not None:
                if tracked_difference:
                    return True
                continue
    return False


def has_onboarding_evidence(
    vault_root: Path | str,
    *,
    profile_path: Path | str | None = None,
    contract_path: Path | str | None = None,
) -> bool:
    """Recognize completed old vaults without guessing about fresh installs."""
    root = Path(vault_root).resolve()
    marker = root / "System/.onboarding-complete"
    if marker.is_file() and not marker.is_symlink():
        return True
    profile_file = Path(profile_path or root / "System/user-profile.yaml")
    profile = _read_profile(profile_file)
    name = profile.get("name")
    if isinstance(name, str) and name.strip():
        return True
    return any(
        _room_has_user_content(
            root,
            room,
            surfaces_for(room, contract_path=contract_path),
        )
        for room in room_ids(contract_path=contract_path)
    )


@dataclass(frozen=True)
class _ActiveRoomSkill:
    target: Path
    identity: str
    payload: bytes | None


def _preflight_room_assets(
    root: Path,
    room: str,
    surfaces: Mapping[str, Any],
    *,
    contract_path: Path | str | None = None,
) -> tuple[
    Path,
    dict[str, SkillSourcePin],
    dict[str, _ActiveRoomSkill],
]:
    dormant = _dormant_root(room, root)
    try:
        pins = resolve_room_skill_sources(
            room,
            _room_release_root(room, root),
            portable_contract_path=contract_path,
        )
    except SkillSourceError as error:
        raise CapabilityError(f"Dormant skill source identity failed for {room}: {error}") from error
    by_skill = {Path(pin.target_path).parent.name: pin for pin in pins}
    expected = tuple(str(skill) for skill in surfaces.get("skills", []))
    if set(by_skill) != set(expected):
        raise CapabilityError(f"Dormant skill authority does not match room {room}")
    for relative_folder in surfaces.get("folders", []):
        relative = str(relative_folder)
        target = _lexical_target(root, relative, kind="directory")
        _preflight_seed_overlay(dormant / "folders" / relative, target, root)
    active: dict[str, _ActiveRoomSkill] = {}
    for pin in pins:
        skill = Path(pin.target_path).parent.name
        active[skill] = _active_room_skill_target(root, pin)
    return dormant, by_skill, active


def _active_room_skill_target(root: Path, pin: SkillSourcePin) -> _ActiveRoomSkill:
    """Validate one lexical active target without following any vault symlink.

    An existing target is safe only when it is the exact release-owned payload.
    Unknown bytes are user-owned for safety purposes and must never be replaced
    or removed by a room toggle.
    """
    relative = Path(pin.target_path).parent
    target = _lexical_target(root, relative.as_posix(), kind="directory")
    if not target.exists():
        return _ActiveRoomSkill(target, "missing", None)
    try:
        entries = tuple(target.iterdir())
    except OSError as error:
        raise CapabilityError(f"Active room skill target cannot be inspected: {relative.as_posix()}") from error
    if len(entries) != 1 or any(
        entry.name != "SKILL.md" or entry.is_symlink() or not entry.is_file()
        for entry in entries
    ):
        raise CapabilityError(
            f"Active room skill target contains unpinned or unsafe entries: {relative.as_posix()}"
        )
    try:
        payload = entries[0].read_bytes()
    except OSError as error:
        raise CapabilityError(
            f"Active room skill target cannot be read: {relative.as_posix()}"
        ) from error
    identity = pin.identify_payload(payload)
    if identity is None:
        raise CapabilityError(
            f"Active room skill target does not match its authoritative pin: {relative.as_posix()}"
        )
    return _ActiveRoomSkill(target, identity, payload)


def _copy_verified_room_skill(
    pin: SkillSourcePin,
    active: _ActiveRoomSkill,
    root: Path,
    mutation_paths: list[str],
    journal: _MutationJournal,
) -> bool:
    """Surface or safely upgrade one pinned skill."""
    target = active.target
    observed = _active_room_skill_target(root, pin)
    if observed.identity != active.identity or observed.payload != active.payload:
        raise CapabilityError(f"Active room skill changed after preflight: {pin.target_path}")
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise CapabilityError(f"Active room skill target is unsafe: {target}")
    if active.identity == "current":
        return False
    payload = pin.path.read_bytes()
    if active.identity != "missing":
        if active.payload is None:
            raise CapabilityError(f"Previous room skill payload is unavailable: {pin.target_path}")
        journal.replaced_file(target / "SKILL.md", active.payload, payload)
        _atomic_bytes_write(target / "SKILL.md", payload)
        if _active_room_skill_target(root, pin).identity != "current":
            raise CapabilityError(f"Upgraded room skill failed identity read-back: {pin.target_path}")
        mutation_paths.append((target / "SKILL.md").relative_to(root).as_posix())
        return True

    _mkdir_with_mutation_receipt(target.parent, mutation_paths, root, journal)
    staged = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        shutil.copy2(pin.path, staged / "SKILL.md", follow_symlinks=False)
        payload = (staged / "SKILL.md").read_bytes()
        if hashlib.sha256(payload).hexdigest() != pin.sha256 or len(payload) != pin.byte_size:
            raise CapabilityError(f"Staged room skill bytes do not match source identity: {pin.source_path}")
        staged.replace(target)
        journal.created_directory(target)
        journal.created_file(target / "SKILL.md", payload)
        surfaced = (target / "SKILL.md").read_bytes()
        if hashlib.sha256(surfaced).hexdigest() != pin.sha256 or len(surfaced) != pin.byte_size:
            raise CapabilityError(f"Surfaced room skill failed identity read-back: {pin.target_path}")
        mutation_paths.extend(
            (
                target.relative_to(root).as_posix(),
                (target / "SKILL.md").relative_to(root).as_posix(),
            )
        )
        return True
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def reconcile_room(
    room: str,
    room_enabled: bool,
    *,
    vault_root: Path | str,
    contract_path: Path | str | None = None,
    _journal: _MutationJournal | None = None,
) -> dict[str, Any]:
    """Surface or hide a room without ever deleting its user-owned folders."""
    if not isinstance(room_enabled, bool):
        raise CapabilityError("enabled state must be true or false")
    root = Path(vault_root).resolve()
    surfaces = surfaces_for(room, contract_path=contract_path)
    dormant, skill_pins, active_skills = _preflight_room_assets(
        root,
        room,
        surfaces,
        contract_path=contract_path,
    )
    created: list[str] = []
    surfaced: list[str] = []
    hidden: list[str] = []
    mutation_paths: list[str] = []
    owns_journal = _journal is None
    journal = _journal or _MutationJournal()

    try:
        if room_enabled:
            for relative_folder in surfaces.get("folders", []):
                relative = str(relative_folder)
                target = _lexical_target(root, relative, kind="directory")
                source = dormant / "folders" / relative
                existed = target.exists()
                _mkdir_with_mutation_receipt(target, mutation_paths, root, journal)
                if not existed:
                    created.append(target.relative_to(root).as_posix())
                _copy_missing(
                    source,
                    target,
                    created,
                    mutation_paths,
                    root,
                    journal,
                )

            for skill in surfaces.get("skills", []):
                skill_id = str(skill)
                pin = skill_pins[skill_id]
                active = active_skills[skill_id]
                if _copy_verified_room_skill(
                    pin,
                    active,
                    root,
                    mutation_paths,
                    journal,
                ):
                    surfaced.append(active.target.relative_to(root).as_posix())
        else:
            # Capability folders are vault-owned user content. Only release-owned
            # active skill copies are unsurfaced, one lexical file and directory.
            for skill in surfaces.get("skills", []):
                skill_id = str(skill)
                pin = skill_pins[skill_id]
                active = active_skills[skill_id]
                observed = _active_room_skill_target(root, pin)
                if observed.identity != active.identity or observed.payload != active.payload:
                    raise CapabilityError(
                        f"Active room skill changed after preflight: {pin.target_path}"
                    )
                if active.identity != "missing":
                    if active.payload is None:
                        raise CapabilityError(
                            f"Active room skill payload is unavailable: {pin.target_path}"
                        )
                    journal.removed_skill(active.target, active.payload)
                    skill_file = active.target / "SKILL.md"
                    skill_file.unlink()
                    active.target.rmdir()
                    mutation_paths.extend(
                        (
                            active.target.relative_to(root).as_posix(),
                            skill_file.relative_to(root).as_posix(),
                        )
                    )
                    hidden.append(active.target.relative_to(root).as_posix())
    except Exception as error:
        if owns_journal:
            try:
                journal.rollback()
            except Exception as rollback_error:
                raise CapabilityError(
                    f"Room {room} reconciliation failed and rollback was incomplete: {rollback_error}"
                ) from error
            raise CapabilityError(
                f"Room {room} reconciliation failed and was rolled back: {error}"
            ) from error
        raise CapabilityError(f"Room {room} reconciliation failed: {error}") from error

    return {
        "room": room,
        "enabled": room_enabled,
        "created": created,
        "skills_surfaced": surfaced,
        "skills_hidden": hidden,
        "mutation_paths": sorted(set(mutation_paths)),
        "user_content_deleted": False,
    }


def migrate_legacy_room_state(
    vault_root: Path | str,
    *,
    profile_path: Path | str | None = None,
    contract_path: Path | str | None = None,
) -> list[str]:
    """One-time bridge for vaults onboarded before capability rooms existed.

    Preserve each room's pre-migration behavior without overriding an explicit
    capability value or a legacy config value. A room with no recorded opinion
    is restored to its current default, so the legacy and lifecycle-only paths
    agree. Fresh installs write explicit room answers at onboarding and are
    never touched here. Returns the rooms seeded (empty when no migration was
    needed).
    """
    root = Path(vault_root).resolve()
    profile_file = Path(profile_path or root / "System/user-profile.yaml")
    if not has_onboarding_evidence(
        root,
        profile_path=profile_file,
        contract_path=contract_path,
    ):
        return []
    profile = _read_profile(profile_file, strict=True)
    capability_state = profile.get("capabilities")
    room_defaults = (
        {"companies": True}
        if isinstance(capability_state, Mapping)
        else {
            "career": True,
            "companies": True,
            "quarter_goals": True,
        }
    )
    seeded: list[str] = []
    for room in room_ids(contract_path=contract_path):
        room_state = capability_state.get(room) if isinstance(capability_state, Mapping) else None
        if isinstance(room_state, Mapping) and isinstance(room_state.get("enabled"), bool):
            continue
        surfaces = surfaces_for(room, contract_path=contract_path)
        legacy_config = surfaces.get("config")
        if isinstance(legacy_config, str):
            legacy = profile.get(legacy_config)
            if isinstance(legacy, Mapping) and isinstance(legacy.get("enabled"), bool):
                continue
        if room not in room_defaults:
            continue
        set_enabled(
            room,
            room_defaults[room],
            vault_root=root,
            profile_path=profile_file,
            contract_path=contract_path,
        )
        seeded.append(room)
    return seeded


def preflight_all(
    vault_root: Path | str,
    *,
    contract_path: Path | str | None = None,
) -> tuple[str, ...]:
    """Validate every room source and active target before any room mutates."""
    root = Path(vault_root).resolve()
    rooms = room_ids(contract_path=contract_path)
    for room in rooms:
        _preflight_room_assets(
            root,
            room,
            surfaces_for(room, contract_path=contract_path),
            contract_path=contract_path,
        )
    return rooms


def preflight_mutation_targets(
    vault_root: Path | str,
    targets: list[Mapping[str, Any]],
) -> tuple[dict[str, str], ...]:
    """Validate a closed list of provisioner write targets without mutation.

    The Node provisioner calls this boundary before it changes profile, seed,
    generated, or session files. Keeping lexical ancestor inspection here means
    room toggles and onboarding share the same no-symlink/no-escape discipline.
    """
    root = Path(vault_root).resolve()
    validated: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(targets):
        if not isinstance(raw, Mapping) or set(raw) != {"path", "kind"}:
            raise CapabilityError(
                f"Provision mutation target {index} must contain only path and kind"
            )
        relative_path = raw["path"]
        kind = raw["kind"]
        if not isinstance(relative_path, str) or kind not in {"file", "directory"}:
            raise CapabilityError(
                f"Provision mutation target {index} has an invalid path or kind"
            )
        identity = (relative_path, kind)
        if identity in seen:
            continue
        _lexical_target(root, relative_path, kind=kind)
        seen.add(identity)
        validated.append({"path": relative_path, "kind": kind})
    return tuple(validated)


def preflight_skill_targets(
    vault_root: Path | str,
    *,
    contract_path: Path | str | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Return the already-validated active payload state for dry-run consumers."""
    root = Path(vault_root).resolve()
    report: dict[str, list[dict[str, str]]] = {}
    for room in room_ids(contract_path=contract_path):
        surfaces = surfaces_for(room, contract_path=contract_path)
        _, pins, active = _preflight_room_assets(
            root,
            room,
            surfaces,
            contract_path=contract_path,
        )
        report[room] = [
            {
                "skill": skill,
                "target_path": pins[skill].target_path,
                "state": active[skill].identity,
            }
            for skill in surfaces.get("skills", [])
        ]
    return report


def reconcile_all(
    vault_root: Path | str,
    *,
    profile_path: Path | str | None = None,
    contract_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Reconcile every contract-declared room against the current profile.

    Runs the legacy migration first so an already-onboarded vault keeps each
    room's pre-migration behavior rather than inheriting fresh-install defaults.
    """
    root = Path(vault_root).resolve()
    profile = Path(profile_path or root / "System/user-profile.yaml")
    rooms = preflight_all(root, contract_path=contract_path)
    _lexical_target(
        root,
        profile.absolute().relative_to(root).as_posix(),
        kind="file",
    )
    journal = _MutationJournal()
    profile_mutation_paths: list[str] = []

    try:
        if has_onboarding_evidence(
            root,
            profile_path=profile,
            contract_path=contract_path,
        ):
            original_bytes = profile.read_bytes() if profile.exists() else b""
            try:
                original = original_bytes.decode("utf-8")
            except UnicodeDecodeError as error:
                raise CapabilityError("Profile must contain UTF-8 text") from error
            rendered = render_missing_companies_compatibility_pin(
                original,
                contract_path=contract_path,
            )
            if rendered is not None and rendered != original:
                rendered_bytes = rendered.encode("utf-8")
                profile_existed = profile.exists()
                _mkdir_with_mutation_receipt(
                    profile.parent,
                    profile_mutation_paths,
                    root,
                    journal,
                )
                _atomic_text_write(profile, rendered)
                if profile_existed:
                    journal.replaced_file(
                        profile,
                        original_bytes,
                        rendered_bytes,
                    )
                else:
                    journal.created_file(profile, rendered_bytes)
                profile_mutation_paths.append(profile.relative_to(root).as_posix())
                if profile.read_bytes() != rendered_bytes:
                    raise CapabilityError("migrated profile read-back did not match its preview")

        results = [
            reconcile_room(
                room,
                enabled(room, profile_path=profile, contract_path=contract_path),
                vault_root=root,
                contract_path=contract_path,
                _journal=journal,
            )
            for room in rooms
        ]
        if profile_mutation_paths and results:
            results[0]["mutation_paths"] = sorted(
                set(results[0]["mutation_paths"]) | set(profile_mutation_paths)
            )
        return results
    except Exception as error:
        try:
            journal.rollback()
        except Exception as rollback_error:
            raise CapabilityError(
                "All-room reconciliation failed and aggregate rollback was incomplete: "
                f"{rollback_error}"
            ) from error
        raise CapabilityError(
            f"All-room reconciliation failed and aggregate rollback completed: {error}"
        ) from error


def _atomic_text_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
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


def _set_block_enabled(text: str, block_key: str, room: str | None, value: bool) -> str:
    """Surgically set ``<block_key>.enabled`` (or ``<block_key>.<room>.enabled``)
    in YAML text, preserving every other byte — comments included.

    Assumes the two-space indentation our shipped profiles use. The caller
    validates the result by re-parsing before anything touches disk.
    """
    rendered = "true" if value else "false"
    lines = text.splitlines(keepends=True)
    newline = "\n"

    def block_bounds(key: str, indent: str, start: int, end: int) -> tuple[int, int] | None:
        opened = None
        for index in range(start, end):
            stripped = lines[index].rstrip("\n")
            if stripped.startswith(f"{indent}{key}:"):
                opened = index
                continue
            if opened is not None:
                # Block ends at the first line at same-or-lower indentation
                # that is not blank/comment continuation.
                if stripped and not stripped.startswith(indent + " ") and not stripped.lstrip().startswith("#"):
                    return opened, index
        return (opened, end) if opened is not None else None

    top = block_bounds(block_key, "", 0, len(lines))
    if top is None:
        # Append a fresh block at EOF.
        suffix = "" if (not lines or lines[-1].endswith("\n")) else newline
        if room is None:
            addition = f"{suffix}{block_key}:{newline}  enabled: {rendered}{newline}"
        else:
            addition = f"{suffix}{block_key}:{newline}  {room}:{newline}    enabled: {rendered}{newline}"
        return text + addition

    start, end = top
    if room is not None:
        inner = block_bounds(room, "  ", start + 1, end)
        if inner is None:
            addition = f"  {room}:{newline}    enabled: {rendered}{newline}"
            lines.insert(start + 1, addition)
            return "".join(lines)
        start, end = inner
        target_indent = "    "
    else:
        target_indent = "  "

    for index in range(start + 1, end):
        stripped = lines[index].rstrip("\n")
        if stripped.lstrip().startswith("enabled:") and stripped.startswith(target_indent):
            comment = ""
            if "#" in stripped:
                comment = "  #" + stripped.split("#", 1)[1]
            lines[index] = f"{target_indent}enabled: {rendered}{comment}{newline}"
            return "".join(lines)
    lines.insert(start + 1, f"{target_indent}enabled: {rendered}{newline}")
    return "".join(lines)


def render_missing_companies_compatibility_pin(
    original: str,
    *,
    contract_path: Path | str | None = None,
) -> str | None:
    """Render the one-time Companies compatibility pin without rewriting profile prose.

    ``None`` means the profile already has an explicit or legacy opinion.
    Invalid state fails closed so an update cannot fall through to the new
    contract default or replace user-owned data. Profiles with no capability
    map also retain the earlier Career/Quarter bridge defaults in the same
    transaction; partial maps gain only the Companies pin.
    """
    import yaml

    try:
        profile = yaml.safe_load(original) or {}
    except yaml.YAMLError as exc:
        raise CapabilityError("Profile must contain valid YAML") from exc
    if not isinstance(profile, dict):
        raise CapabilityError("Profile must contain an object")

    capability_state = profile.get("capabilities")
    if capability_state is not None and not isinstance(capability_state, Mapping):
        raise CapabilityError("Profile capabilities must contain an object")
    company_state = capability_state.get("companies") if isinstance(capability_state, Mapping) else None
    if company_state is not None and not isinstance(company_state, Mapping):
        raise CapabilityError("Profile capabilities.companies must contain an object")
    if isinstance(company_state, Mapping) and "enabled" in company_state:
        if not isinstance(company_state["enabled"], bool):
            raise CapabilityError("Profile capabilities.companies.enabled must be true or false")
        return None
    company_surfaces = surfaces_for("companies", contract_path=contract_path)
    company_legacy_config = company_surfaces.get("config")
    if isinstance(company_legacy_config, str):
        company_legacy_state = profile.get(company_legacy_config)
        if isinstance(company_legacy_state, Mapping) and "enabled" in company_legacy_state:
            if not isinstance(company_legacy_state["enabled"], bool):
                raise CapabilityError(f"Profile {company_legacy_config}.enabled must be true or false")
            return None

    # A vault that never expressed a choice gets these rooms rather than being
    # held at an older, emptier shape: restoring a data surface nobody declined
    # is the point. Companies now matches Career and Quarter Goals; it was the
    # odd one out, pinned off, which no user could have explained. An explicit
    # choice, on or off, is read above this and always wins.
    room_defaults = (
        {"companies": True}
        if isinstance(capability_state, Mapping)
        else {
            "career": True,
            "companies": True,
            "quarter_goals": True,
        }
    )
    expected = copy.deepcopy(profile)
    rendered = original
    for room, default in room_defaults.items():
        room_state = capability_state.get(room) if isinstance(capability_state, Mapping) else None
        if isinstance(room_state, Mapping) and "enabled" in room_state:
            if not isinstance(room_state["enabled"], bool):
                raise CapabilityError(f"Profile capabilities.{room}.enabled must be true or false")
            continue
        surfaces = surfaces_for(room, contract_path=contract_path)
        legacy_config = surfaces.get("config")
        if isinstance(legacy_config, str):
            legacy_state = profile.get(legacy_config)
            if isinstance(legacy_state, Mapping) and "enabled" in legacy_state:
                if not isinstance(legacy_state["enabled"], bool):
                    raise CapabilityError(f"Profile {legacy_config}.enabled must be true or false")
                continue
        expected.setdefault("capabilities", {})
        expected["capabilities"].setdefault(room, {})
        expected["capabilities"][room]["enabled"] = default
        rendered = _set_block_enabled(
            rendered,
            "capabilities",
            room,
            default,
        )
    try:
        reparsed = yaml.safe_load(rendered) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - guarded by byte-level tests
        raise CapabilityError("Companies compatibility pin produced invalid YAML") from exc
    if reparsed != expected:
        raise CapabilityError("Companies compatibility pin changed unrelated profile state")
    return rendered


def set_enabled(
    room: str,
    room_enabled: bool,
    *,
    vault_root: Path | str,
    profile_path: Path | str | None = None,
    contract_path: Path | str | None = None,
) -> dict[str, Any]:
    """Persist one room state and immediately reconcile its surfaced assets."""
    import yaml

    if not isinstance(room_enabled, bool):
        raise CapabilityError("enabled state must be true or false")
    surfaces = surfaces_for(room, contract_path=contract_path)
    root = Path(vault_root).resolve()
    # Enabling and disabling both change active code. Prove the release source
    # and every existing target before changing profile state or room assets.
    _preflight_room_assets(root, room, surfaces, contract_path=contract_path)
    profile_file = Path(profile_path or root / "System/user-profile.yaml")
    try:
        profile_relative = profile_file.absolute().relative_to(root)
    except ValueError as error:
        raise CapabilityError("Profile mutation target must stay inside the vault") from error
    _lexical_target(root, profile_relative.as_posix(), kind="file")
    # Reads may fail safely to "off", but mutations must never replace malformed
    # or unreadable user state with an empty profile. strict=True raises on
    # unreadable YAML before any edit is attempted.
    _read_profile(profile_file, strict=True)
    original_bytes = profile_file.read_bytes() if profile_file.exists() else b""
    original = original_bytes.decode("utf-8")

    # Surgical line edits: only the enabled flags change; every other byte of
    # the user's profile — comments and formatting included — is preserved.
    updated = _set_block_enabled(original, "capabilities", room, room_enabled)
    legacy_config = surfaces.get("config")
    if isinstance(legacy_config, str):
        updated = _set_block_enabled(updated, legacy_config, None, room_enabled)

    # Validate the surgical result BEFORE it touches disk: it must parse, and
    # it must read back exactly the state we intended. Anything else refuses.
    try:
        reparsed = yaml.safe_load(updated) or {}
    except yaml.YAMLError as exc:
        raise CapabilityError("profile edit produced invalid YAML; refusing to write") from exc
    room_state = (
        reparsed.get("capabilities", {}).get(room, {}) if isinstance(reparsed.get("capabilities"), Mapping) else {}
    )
    if not isinstance(room_state, Mapping) or room_state.get("enabled") is not room_enabled:
        raise CapabilityError("profile edit did not produce the intended room state; refusing to write")

    profile_existed = profile_file.exists()
    profile_written = not profile_existed or updated != original
    profile_mutation_paths: list[str] = []
    profile_journal = _MutationJournal()

    if profile_written:
        if profile_existed:
            if (
                profile_file.is_symlink()
                or not profile_file.is_file()
                or profile_file.read_text(encoding="utf-8") != original
            ):
                raise CapabilityError("profile changed after preview; refusing to write")
        elif profile_file.exists() or profile_file.is_symlink():
            raise CapabilityError("profile target appeared after preview; refusing to write")
        updated_bytes = updated.encode("utf-8")
        try:
            _mkdir_with_mutation_receipt(
                profile_file.parent,
                profile_mutation_paths,
                root,
                profile_journal,
            )
            _atomic_text_write(profile_file, updated)
            if profile_existed:
                profile_journal.replaced_file(
                    profile_file,
                    original_bytes,
                    updated_bytes,
                )
            else:
                profile_journal.created_file(profile_file, updated_bytes)
            profile_mutation_paths.append(profile_relative.as_posix())
            if profile_file.read_bytes() != updated_bytes:
                raise CapabilityError("profile read-back did not match the preview")
        except Exception as error:
            try:
                profile_journal.rollback()
            except Exception as rollback_error:
                raise CapabilityError(
                    "profile write failed and rollback was incomplete: "
                    f"{rollback_error}"
                ) from error
            raise CapabilityError(
                f"profile write failed before room reconciliation: {error}"
            ) from error
    try:
        result = reconcile_room(
            room,
            room_enabled,
            vault_root=root,
            contract_path=contract_path,
        )
        result["mutation_paths"] = sorted(
            set(result["mutation_paths"]) | set(profile_mutation_paths)
        )
        return result
    except Exception as error:
        try:
            profile_journal.rollback()
        except Exception as rollback_error:
            raise CapabilityError(
                f"Room {room} reconciliation failed and profile rollback was incomplete: "
                f"{rollback_error}"
            ) from error
        if isinstance(error, CapabilityError):
            raise
        raise CapabilityError(
            f"Room {room} reconciliation failed and was rolled back: {error}"
        ) from error


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
        "--preflight",
        action="store_true",
        help="Validate every room source and active target without mutation",
    )
    parser.add_argument(
        "--preflight-mutation-targets",
        action="store_true",
        help="Validate caller-declared provision mutation targets without room checks",
    )
    parser.add_argument(
        "--mutation-targets-json",
        default="[]",
        help="Closed JSON array of {path, kind} provision mutation targets",
    )
    parser.add_argument(
        "--vault",
        default=os.environ.get("VAULT_PATH", str(REPO_ROOT)),
        help="Dex vault root (defaults to VAULT_PATH or this checkout)",
    )
    parser.add_argument(
        "--contract",
        default=None,
        help="Portable contract authority (defaults to the shipped contract)",
    )
    args = parser.parse_args()
    try:
        mutation_targets = json.loads(args.mutation_targets_json)
    except json.JSONDecodeError as error:
        parser.error(f"--mutation-targets-json must be valid JSON: {error}")
    if not isinstance(mutation_targets, list):
        parser.error("--mutation-targets-json must contain an array")
    if args.list:
        print(json.dumps({"rooms": room_ids(contract_path=args.contract)}, indent=2))
        return 0
    if args.preflight:
        rooms = preflight_all(Path(args.vault), contract_path=args.contract)
        validated_targets = preflight_mutation_targets(Path(args.vault), mutation_targets)
        print(
            json.dumps(
                {
                    "preflight": "passed",
                    "rooms": rooms,
                    "skill_targets": preflight_skill_targets(
                        Path(args.vault),
                        contract_path=args.contract,
                    ),
                    "mutation_targets": validated_targets,
                },
                indent=2,
            )
        )
        return 0
    if args.preflight_mutation_targets:
        validated_targets = preflight_mutation_targets(Path(args.vault), mutation_targets)
        print(
            json.dumps(
                {
                    "preflight": "passed",
                    "mutation_targets": validated_targets,
                },
                indent=2,
            )
        )
        return 0
    if args.reconcile:
        results = reconcile_all(Path(args.vault), contract_path=args.contract)
        print(json.dumps({"rooms": results}, indent=2))
        return 0
    if args.room is None or args.state is None:
        parser.error(
            "room and state are required unless --list, --preflight, "
            "--preflight-mutation-targets, or --reconcile is used"
        )
    result = set_enabled(
        args.room,
        args.state == "on",
        vault_root=Path(args.vault),
        contract_path=args.contract,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
