"""Transition capsules: pre-change snapshots of the reset-owned config files.

A reset (re-onboarding over a vault that completed onboarding) rewrites
``System/user-profile.yaml``, ``System/pillars.yaml``, and the room-enable
map. Before the provisioner mutates anything, this module captures that
pre-change state so the outcome can be verified against a transition
manifest — the dotted keys the replayed steps were allowed to change — and
restored exactly if the user rejects the result.

The customization-capsule primitives are reused directly (canonical JSON,
SHA-256 content addressing, the crash-safe transaction engine). Capsules
live under their own root rather than ``System/.dex/customization-migrations``
because the update lane's status projection and doctor probe treat every
entry there as an update-migration capsule and would report a transition
capsule as pending or unverifiable forever.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from core import capabilities as capability_rooms
from core.customization_migration.capsule import _canonical_json, _sha256
from core.customization_migration.inventory import USER_CONFIG_PATHS
from core.lifecycle.filesystem import FilesystemInspectionError, bounded_read
from core.transaction.engine import PlanEntry, Transaction

TRANSITION_CAPSULE_ROOT = "System/.dex/transition-capsules"
# The embedded UTC timestamp makes lexical order creation order.
TRANSITION_CAPSULE_ID = re.compile(r"^tcap-\d{8}T\d{6}Z-[0-9a-f]{8}$")
TRANSITION_CONFIG_PATHS = ("System/pillars.yaml", "System/user-profile.yaml")
_FILE_NAMESPACES = {
    "System/user-profile.yaml": "profile",
    "System/pillars.yaml": "pillars",
}
_ROOM_NAMESPACE = "rooms"
_MAX_CONFIG_BYTES = 1024 * 1024
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "capsule_id",
        "created_epoch_seconds",
        "reason",
        "files",
        "sections",
    }
)
_FILE_ENTRY_KEYS = frozenset({"path", "present", "sha256", "byte_size"})
_SECTION_ENTRY_KEYS = frozenset({"name", "sha256", "byte_size"})
_SECTION_NAMES = frozenset({"allowed", "rooms"})
# The display order of the onboarding answers, for the human-readable summary.
_DISPLAY_ORDER = (
    "name",
    "role",
    "role_group",
    "company",
    "company_size",
    "email_domain",
    "pillars",
    "communication",
    "working_week",
    "rooms",
)

if not set(TRANSITION_CONFIG_PATHS) <= USER_CONFIG_PATHS:
    raise AssertionError(
        "transition capsule paths drifted from the protected customization inventory"
    )


class TransitionCapsuleError(RuntimeError):
    """A transition-capsule operation refused to proceed safely."""


@dataclass(frozen=True)
class TransitionCapsule:
    capsule_id: str
    created_epoch_seconds: int
    reason: str
    files: Mapping[str, bytes | None]
    rooms: Mapping[str, bool]
    allowed_prefixes: tuple[str, ...]


_ABSENT = object()


def _flatten(value: object, prefix: str = "") -> dict[str, object]:
    """Flatten nested mappings to dotted keys; lists and scalars are leaves."""
    if isinstance(value, dict) and value:
        flat: dict[str, object] = {}
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            flat.update(_flatten(child, child_prefix))
        return flat
    return {prefix: value} if prefix else {}


def effective_room_map(vault_root: Path) -> dict[str, bool]:
    """The room-enable states a user actually experiences right now."""
    profile_path = Path(vault_root) / "System/user-profile.yaml"
    return {
        room: capability_rooms.enabled(room, profile_path=profile_path)
        for room in capability_rooms.room_ids()
    }


def _read_config_bytes(root: Path, relative: str) -> bytes | None:
    target = root / relative
    if not target.exists() and not target.is_symlink():
        return None
    try:
        return bounded_read(root, relative, max_bytes=_MAX_CONFIG_BYTES)
    except FilesystemInspectionError as error:
        raise TransitionCapsuleError(f"{relative} cannot be read safely: {error}") from error


def create_transition_capsule(
    vault_root: Path,
    *,
    allowed_prefixes: Iterable[str],
    rooms: Mapping[str, bool],
    reason: str = "reset-finalize",
    clock: Callable[[], float] = time.time,
) -> dict[str, object]:
    """Snapshot the config files and room map through one sealed transaction."""
    root = Path(vault_root).resolve()
    if not isinstance(reason, str) or not reason:
        raise TransitionCapsuleError("capsule reason must be a non-empty string")
    prefixes = tuple(sorted(set(allowed_prefixes)))
    if any(not isinstance(prefix, str) or not prefix for prefix in prefixes):
        raise TransitionCapsuleError("allowed prefixes must be non-empty strings")
    room_map = dict(rooms)
    if any(
        not isinstance(room, str) or not room or not isinstance(state, bool)
        for room, state in room_map.items()
    ):
        raise TransitionCapsuleError("rooms must map room ids to booleans")

    created = int(clock())
    capsule_id = (
        time.strftime("tcap-%Y%m%dT%H%M%SZ-", time.gmtime(created))
        + secrets.token_hex(4)
    )
    files_meta: list[dict[str, object]] = []
    blobs: dict[str, bytes] = {}
    for relative in TRANSITION_CONFIG_PATHS:
        raw = _read_config_bytes(root, relative)
        if raw is None:
            files_meta.append(
                {"path": relative, "present": False, "sha256": None, "byte_size": None}
            )
            continue
        digest = _sha256(raw)
        files_meta.append(
            {"path": relative, "present": True, "sha256": digest, "byte_size": len(raw)}
        )
        blobs[digest] = raw

    sections = {
        "allowed": _canonical_json(
            {"schema_version": 0, "allowed_prefixes": list(prefixes)}
        ),
        "rooms": _canonical_json({"schema_version": 0, "rooms": room_map}),
    }
    manifest = {
        "schema_version": 0,
        "capsule_id": capsule_id,
        "created_epoch_seconds": created,
        "reason": reason,
        "files": files_meta,
        "sections": [
            {"name": name, "sha256": _sha256(raw), "byte_size": len(raw)}
            for name, raw in sorted(sections.items())
        ],
    }
    capsule_prefix = f"{TRANSITION_CAPSULE_ROOT}/{capsule_id}"
    if (root / capsule_prefix).exists():
        raise TransitionCapsuleError(f"transition capsule already exists: {capsule_id}")
    materials: dict[str, bytes] = {
        f"{capsule_prefix}/manifest.json": _canonical_json(manifest)
    }
    for name, raw in sections.items():
        materials[f"{capsule_prefix}/{name}.json"] = raw
    for digest, raw in blobs.items():
        materials[f"{capsule_prefix}/blobs/{digest}"] = raw
    plan = [
        PlanEntry(path, raw, mode=0o600) for path, raw in sorted(materials.items())
    ]
    Transaction.begin(root, plan, operation="transition-capsule").run()
    return {"capsule_id": capsule_id, "path": capsule_prefix, "files": files_meta}


def list_transition_capsule_ids(vault_root: Path) -> tuple[str, ...]:
    root = Path(vault_root).resolve()
    capsule_root = root / TRANSITION_CAPSULE_ROOT
    if capsule_root.is_symlink() or not capsule_root.is_dir():
        return ()
    return tuple(
        sorted(
            child.name
            for child in capsule_root.iterdir()
            if TRANSITION_CAPSULE_ID.fullmatch(child.name) is not None
            and child.is_dir()
            and not child.is_symlink()
        )
    )


def _capsule_bytes(root: Path, relative: str) -> bytes:
    try:
        return bounded_read(root, relative, max_bytes=_MAX_CONFIG_BYTES)
    except FilesystemInspectionError as error:
        raise TransitionCapsuleError(
            f"transition capsule content is missing or unsafe: {relative}"
        ) from error


def _manifest_from_bytes(raw: bytes, capsule_id: str) -> dict[str, object]:
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TransitionCapsuleError("transition manifest is unreadable") from error
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise TransitionCapsuleError("transition manifest shape is not the v0 schema")
    if manifest["schema_version"] != 0 or manifest["capsule_id"] != capsule_id:
        raise TransitionCapsuleError("transition manifest identity does not match")
    if _canonical_json(manifest) != raw:
        raise TransitionCapsuleError("transition manifest is not canonical")
    files = manifest["files"]
    if not isinstance(files, list) or {
        entry["path"] for entry in files if isinstance(entry, dict)
    } != set(TRANSITION_CONFIG_PATHS):
        raise TransitionCapsuleError("transition manifest files are not the config set")
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != _FILE_ENTRY_KEYS:
            raise TransitionCapsuleError("transition manifest file entry is malformed")
    sections = manifest["sections"]
    if not isinstance(sections, list) or {
        entry.get("name") for entry in sections if isinstance(entry, dict)
    } != _SECTION_NAMES:
        raise TransitionCapsuleError("transition manifest sections are incomplete")
    for entry in sections:
        if not isinstance(entry, dict) or set(entry) != _SECTION_ENTRY_KEYS:
            raise TransitionCapsuleError(
                "transition manifest section entry is malformed"
            )
    return manifest


def read_transition_capsule(vault_root: Path, capsule_id: str) -> TransitionCapsule:
    """Load one capsule, refusing any content that no longer matches its manifest."""
    if (
        not isinstance(capsule_id, str)
        or TRANSITION_CAPSULE_ID.fullmatch(capsule_id) is None
    ):
        raise TransitionCapsuleError("transition capsule id is not canonical")
    root = Path(vault_root).resolve()
    capsule_prefix = f"{TRANSITION_CAPSULE_ROOT}/{capsule_id}"
    manifest = _manifest_from_bytes(
        _capsule_bytes(root, f"{capsule_prefix}/manifest.json"), capsule_id
    )
    files: dict[str, bytes | None] = {}
    for entry in manifest["files"]:
        if entry["present"] is not True:
            files[entry["path"]] = None
            continue
        raw = _capsule_bytes(root, f"{capsule_prefix}/blobs/{entry['sha256']}")
        if len(raw) != entry["byte_size"] or _sha256(raw) != entry["sha256"]:
            raise TransitionCapsuleError(
                f"transition capsule {capsule_id} is tampered: stored content for "
                f"{entry['path']} does not match its manifest"
            )
        files[entry["path"]] = raw
    sections: dict[str, dict[str, object]] = {}
    for entry in manifest["sections"]:
        raw = _capsule_bytes(root, f"{capsule_prefix}/{entry['name']}.json")
        if len(raw) != entry["byte_size"] or _sha256(raw) != entry["sha256"]:
            raise TransitionCapsuleError(
                f"transition capsule {capsule_id} is tampered: stored section "
                f"{entry['name']} does not match its manifest"
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TransitionCapsuleError(
                f"transition capsule section {entry['name']} is unreadable"
            ) from error
        if not isinstance(payload, dict) or payload.get("schema_version") != 0:
            raise TransitionCapsuleError(
                f"transition capsule section {entry['name']} is malformed"
            )
        sections[entry["name"]] = payload
    allowed = sections["allowed"].get("allowed_prefixes")
    rooms = sections["rooms"].get("rooms")
    if not isinstance(allowed, list) or any(
        not isinstance(prefix, str) or not prefix for prefix in allowed
    ):
        raise TransitionCapsuleError("transition capsule allowed keys are malformed")
    if not isinstance(rooms, dict) or any(
        not isinstance(room, str) or not isinstance(state, bool)
        for room, state in rooms.items()
    ):
        raise TransitionCapsuleError("transition capsule room states are malformed")
    return TransitionCapsule(
        capsule_id,
        int(manifest["created_epoch_seconds"]),
        str(manifest["reason"]),
        files,
        rooms,
        tuple(allowed),
    )


def _latest_capsule_id(root: Path) -> str:
    ids = list_transition_capsule_ids(root)
    if not ids:
        raise TransitionCapsuleError(
            "no transition capsule exists; one is created when finalize runs "
            "on a vault that already completed onboarding"
        )
    return ids[-1]


def _flatten_state(
    files: Mapping[str, bytes | None],
    rooms: Mapping[str, bool],
) -> dict[str, object]:
    import yaml

    flat: dict[str, object] = {}
    for relative, raw in files.items():
        namespace = _FILE_NAMESPACES[relative]
        if raw is None:
            continue
        try:
            loaded = yaml.safe_load(raw.decode("utf-8")) or {}
        except (UnicodeDecodeError, yaml.YAMLError) as error:
            raise TransitionCapsuleError(
                f"{relative} is not readable as settings"
            ) from error
        if not isinstance(loaded, dict):
            raise TransitionCapsuleError(f"{relative} must contain an object")
        for key, value in _flatten(loaded).items():
            flat[f"{namespace}.{key}"] = value
    for room, state in rooms.items():
        flat[f"{_ROOM_NAMESPACE}.{room}"] = bool(state)
    return flat


def _is_allowed(key: str, prefixes: tuple[str, ...]) -> bool:
    return any(key == prefix or key.startswith(prefix + ".") for prefix in prefixes)


def _display_name(key: str) -> str:
    if key.startswith(f"{_ROOM_NAMESPACE}.") or key.startswith("profile.capabilities."):
        return "rooms"
    for namespace in ("profile.", "pillars."):
        if key.startswith(namespace):
            key = key[len(namespace):]
            break
    return key.split(".", 1)[0]


def _strip_profile_namespace(key: str) -> str:
    return key[len("profile."):] if key.startswith("profile.") else key


def _ordered_display(names: set[str]) -> list[str]:
    ordered = [name for name in _DISPLAY_ORDER if name in names]
    ordered.extend(sorted(name for name in names if name not in _DISPLAY_ORDER))
    return ordered


def verify_transition(
    vault_root: Path,
    capsule_id: str | None = None,
) -> dict[str, object]:
    """Diff the capsule against the vault, allowing only the manifested keys."""
    root = Path(vault_root).resolve()
    if capsule_id is None:
        capsule_id = _latest_capsule_id(root)
    capsule = read_transition_capsule(root, capsule_id)
    before = _flatten_state(capsule.files, capsule.rooms)
    current_files = {
        relative: _read_config_bytes(root, relative)
        for relative in TRANSITION_CONFIG_PATHS
    }
    after = _flatten_state(current_files, effective_room_map(root))

    changed_allowed: list[str] = []
    lost: list[dict[str, object]] = []
    unexpected: list[dict[str, object]] = []
    filled_defaults: list[str] = []
    carried = 0
    for key in sorted(set(before) | set(after)):
        old = before.get(key, _ABSENT)
        new = after.get(key, _ABSENT)
        if old is not _ABSENT and new is not _ABSENT and old == new:
            # Room states mirror profile keys; count each setting once.
            if not key.startswith(f"{_ROOM_NAMESPACE}."):
                carried += 1
            continue
        if _is_allowed(key, capsule.allowed_prefixes):
            changed_allowed.append(key)
        elif old is _ABSENT:
            # A key neither state had before is a filled gap, not a loss.
            filled_defaults.append(key)
        elif new is _ABSENT:
            lost.append({"key": key, "old": old})
        else:
            unexpected.append({"key": key, "old": old, "new": new})

    verified = not lost and not unexpected
    changed_names = _ordered_display({_display_name(key) for key in changed_allowed})
    changed_text = ", ".join(changed_names) if changed_names else "nothing"
    lost_text = (
        ", ".join(_strip_profile_namespace(item["key"]) for item in lost)
        if lost
        else "none"
    )
    summary = (
        f"Changed (you chose): {changed_text}. "
        f"Carried forward: {carried} settings. Lost: {lost_text}."
    )
    if unexpected:
        summary += " Changed outside your answers: " + ", ".join(
            _strip_profile_namespace(item["key"]) for item in unexpected
        ) + "."
    return {
        "verified": verified,
        "capsule_id": capsule_id,
        "changed_allowed": changed_allowed,
        "carried_forward_count": carried,
        "lost": lost,
        "unexpected": unexpected,
        "filled_defaults": filled_defaults,
        "summary": summary,
    }


def _restore_changes(
    current: bytes | None,
    captured: bytes,
) -> list[dict[str, object]] | None:
    import yaml

    try:
        current_loaded = (
            yaml.safe_load(current.decode("utf-8")) if current is not None else {}
        ) or {}
        captured_loaded = yaml.safe_load(captured.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError):
        return None
    if not isinstance(current_loaded, dict) or not isinstance(captured_loaded, dict):
        return None
    current_flat = _flatten(current_loaded)
    captured_flat = _flatten(captured_loaded)
    changes: list[dict[str, object]] = []
    for key in sorted(set(current_flat) | set(captured_flat)):
        old = current_flat.get(key, _ABSENT)
        new = captured_flat.get(key, _ABSENT)
        if old is not _ABSENT and new is not _ABSENT and old == new:
            continue
        changes.append(
            {
                "key": key,
                "old": None if old is _ABSENT else old,
                "new": None if new is _ABSENT else new,
            }
        )
    return changes


def restore_transition_capsule(
    vault_root: Path,
    capsule_id: str | None = None,
    *,
    dry_run: bool = True,
) -> dict[str, object]:
    """Put the two config files back exactly as captured; touch nothing else."""
    root = Path(vault_root).resolve()
    if capsule_id is None:
        capsule_id = _latest_capsule_id(root)
    capsule = read_transition_capsule(root, capsule_id)

    actions: list[dict[str, object]] = []
    plan: list[PlanEntry] = []
    for relative in TRANSITION_CONFIG_PATHS:
        captured = capsule.files[relative]
        current = _read_config_bytes(root, relative)
        if captured is None:
            if current is None:
                actions.append({"path": relative, "action": "unchanged"})
            else:
                # Restore never deletes: a file the capture never saw stays.
                actions.append(
                    {
                        "path": relative,
                        "action": "left-in-place",
                        "note": (
                            "did not exist when the snapshot was taken; "
                            "restore never deletes"
                        ),
                    }
                )
            continue
        if current == captured:
            actions.append({"path": relative, "action": "unchanged"})
            continue
        action: dict[str, object] = {"path": relative, "action": "restore"}
        changes = _restore_changes(current, captured)
        if changes is not None:
            action["changes"] = changes
        actions.append(action)
        plan.append(PlanEntry(relative, captured))

    restored = False
    if plan and not dry_run:
        Transaction.begin(root, plan, operation="transition-restore").run()
        restored = True
    return {
        "capsule_id": capsule_id,
        "dry_run": dry_run,
        "restored": restored,
        "files": actions,
    }


__all__ = [
    "TRANSITION_CAPSULE_ROOT",
    "TRANSITION_CONFIG_PATHS",
    "TransitionCapsule",
    "TransitionCapsuleError",
    "create_transition_capsule",
    "effective_room_map",
    "list_transition_capsule_ids",
    "read_transition_capsule",
    "restore_transition_capsule",
    "verify_transition",
]
