"""Release-owned source authority for active and adoptable Lens skill entries.

The Lens registry names a source kind, but it does not duplicate lifecycle or
capability-room payload identity. This module resolves every reference through the
publisher-owned authority and returns one verified source/target pin. Catalogue
generation and room surfacing share this boundary so they cannot disagree about
which bytes are trusted.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

try:
    from core.utils.local_git import git_result
except ModuleNotFoundError:  # Script entrypoints execute with core/ on sys.path.
    from utils.local_git import git_result  # type: ignore[no-redef]

DEFAULT_LIFECYCLE_CATALOG = Path("core/lifecycle/catalog/official-capabilities.json")
DEFAULT_PORTABLE_CONTRACT = Path("packages/dex-contracts/dist/portable-vault.contract.json")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX_COMMIT = re.compile(r"^[0-9a-f]{40}$")
RELEASE_VERSION = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")


class SkillSourceError(ValueError):
    """A skill reference cannot be resolved to release-owned bytes."""


@dataclass(frozen=True)
class SkillPayloadPin:
    """One historical release payload that Dex may safely replace."""

    release: str
    sha256: str
    byte_size: int


@dataclass(frozen=True)
class SkillSourcePin:
    """One verified dormant-or-active source and its canonical active target."""

    kind: str
    source_path: str
    target_path: str
    sha256: str
    byte_size: int
    path: Path
    previous_payloads: tuple[SkillPayloadPin, ...] = ()

    def identify_payload(self, payload: bytes) -> str | None:
        """Return ``current`` or the owning prior release for trusted bytes."""
        sha256 = hashlib.sha256(payload).hexdigest()
        byte_size = len(payload)
        if sha256 == self.sha256 and byte_size == self.byte_size:
            return "current"
        for previous in self.previous_payloads:
            if sha256 == previous.sha256 and byte_size == previous.byte_size:
                return previous.release
        return None


def _mapping(value: object, *, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SkillSourceError(f"{context} must be a JSON object")
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
        raise SkillSourceError(f"{context} fields are not closed ({'; '.join(details)})")


def _strict_json(path: Path, *, context: str) -> object:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise SkillSourceError(f"{context} repeats JSON field {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                SkillSourceError(f"{context} contains non-finite JSON number {value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SkillSourceError(f"cannot read {context}: {error}") from error


def _authority_path(release_root: Path, explicit: Path | str | None, default: Path) -> Path:
    candidate = Path(explicit) if explicit is not None else default
    return candidate if candidate.is_absolute() else release_root / candidate


def _relative_path(value: object, *, context: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise SkillSourceError(f"{context} is not a canonical release-relative path")
    normalized = posixpath.normpath(value)
    if (
        normalized != value
        or normalized in ("", ".", "..")
        or normalized.startswith("/")
        or normalized.startswith("../")
    ):
        raise SkillSourceError(f"{context} is not a canonical release-relative path")
    return value


def _digest(value: object, *, context: str) -> str:
    if not isinstance(value, str) or HEX_SHA256.fullmatch(value) is None:
        raise SkillSourceError(f"{context} must be a lowercase sha256 digest")
    return value


def _byte_size(value: object, *, context: str) -> int:
    if type(value) is not int or value < 0:
        raise SkillSourceError(f"{context} must be a non-negative integer")
    return value


def _previous_payloads(value: object, *, context: str) -> tuple[SkillPayloadPin, ...]:
    if not isinstance(value, list):
        raise SkillSourceError(f"{context} must be an array")
    result: list[SkillPayloadPin] = []
    releases: set[str] = set()
    identities: set[tuple[str, int]] = set()
    for index, raw in enumerate(value):
        item_context = f"{context} {index}"
        item = _mapping(raw, context=item_context)
        _exact_fields(
            item,
            {"release", "sha256", "byte_size"},
            context=item_context,
        )
        release = item.get("release")
        if not isinstance(release, str) or RELEASE_VERSION.fullmatch(release) is None:
            raise SkillSourceError(f"{item_context} release must be a stable vMAJOR.MINOR.PATCH tag")
        sha256 = _digest(item.get("sha256"), context=f"{item_context} sha256")
        byte_size = _byte_size(item.get("byte_size"), context=f"{item_context} byte_size")
        identity = (sha256, byte_size)
        if release in releases or identity in identities:
            raise SkillSourceError(f"{context} contains duplicate release or payload identity")
        releases.add(release)
        identities.add(identity)
        result.append(SkillPayloadPin(release, sha256, byte_size))
    return tuple(result)


def _release_file(release_root: Path, relative: str, *, context: str) -> Path:
    root = release_root.resolve()
    candidate = root / relative
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise SkillSourceError(f"{context} escapes the release root: {relative}")

    cursor = root
    for part in Path(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SkillSourceError(f"{context} contains a symlink: {relative}")
    if not candidate.is_file():
        raise SkillSourceError(f"{context} is missing or not a regular file: {relative}")
    return candidate


def _regular_json_mapping(path: Path, *, context: str) -> Mapping[str, object]:
    if path.is_symlink() or not path.is_file():
        raise SkillSourceError(f"{context} is missing or not a regular file")
    return _mapping(_strict_json(path, context=context), context=context)


def _split_release_identity(
    release_root: Path,
    *,
    context: str,
) -> tuple[Path, str] | None:
    """Return the exact installed brain tree for a sound post-split vault.

    A split leaves release-owned bytes in the vault directory but moves their
    Git authority to ``.dex/brain.git``. The new ``.git`` belongs only to the
    user's vault, so it must never be used to prove shipped source identity.
    """
    root = release_root.resolve()
    topology_path = root / "System/.dex/topology.json"
    brain_git = root / ".dex/brain.git"
    split_signal = any(
        candidate.is_symlink() or candidate.exists()
        for candidate in (topology_path, brain_git)
    )
    if not split_signal:
        return None

    for relative in (".git", ".dex", ".dex/brain.git", "System", "System/.dex"):
        candidate = root / relative
        if candidate.is_symlink():
            raise SkillSourceError(f"cannot prove {context}: split path {relative} is a symlink")
    if not (root / ".git").is_dir() or not brain_git.is_dir():
        raise SkillSourceError(f"cannot prove {context}: split Git directories are incomplete")

    topology = _regular_json_mapping(topology_path, context="split topology marker")
    vault_marker = _regular_json_mapping(root / ".git/dex-vault-v2", context="vault Git marker")
    brain_marker = _regular_json_mapping(brain_git / "dex-brain-v2", context="brain Git marker")
    environment = topology.get("environment")
    if (
        topology.get("schemaVersion") != 1
        or topology.get("topology") != "brain-vault-split"
        or topology.get("vaultGitDir") != ".git"
        or topology.get("brainGitDir") != ".dex/brain.git"
        or not isinstance(environment, Mapping)
        or not isinstance(environment.get("DEX_VAULT"), str)
        or not environment.get("DEX_VAULT")
        or vault_marker.get("schemaVersion") != 1
        or vault_marker.get("role") != "vault"
        or brain_marker.get("schemaVersion") != 1
        or brain_marker.get("role") != "brain"
    ):
        raise SkillSourceError(f"cannot prove {context}: brain/vault split identity is inconsistent")

    installed = topology.get("installedRelease")
    brain_installed = brain_marker.get("installed")
    if (
        not isinstance(installed, str)
        or HEX_COMMIT.fullmatch(installed) is None
        or brain_installed != installed
    ):
        raise SkillSourceError(
            f"cannot prove {context}: brain installed identity does not match split topology"
        )
    try:
        installed_ref = git_result(
            root,
            f"--git-dir={brain_git}",
            "rev-parse",
            "--verify",
            "refs/dex/installed^{commit}",
            profile="read-only",
            timeout=3,
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        raise SkillSourceError(f"cannot prove {context} from the installed brain ref") from error
    if installed_ref.returncode != 0 or installed_ref.stdout.decode("ascii", errors="ignore").strip() != installed:
        raise SkillSourceError(
            f"cannot prove {context}: installed brain ref does not match split topology"
        )
    return brain_git, installed


def _require_tracked(release_root: Path, relative: str, *, context: str) -> None:
    root = release_root.resolve()
    split_identity = _split_release_identity(root, context=context)
    if split_identity is not None:
        brain_git, installed = split_identity
        try:
            result = git_result(
                root,
                f"--git-dir={brain_git}",
                "ls-tree",
                "-z",
                "--full-tree",
                installed,
                "--",
                relative,
                profile="read-only",
                timeout=3,
            )
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            raise SkillSourceError(f"cannot prove {context} from the installed brain tree") from error
        records = tuple(record for record in result.stdout.split(b"\0") if record)
        if result.returncode != 0 or not records:
            raise SkillSourceError(
                f"{context} is not tracked by the installed release tree: {relative}"
            )
        try:
            metadata, raw_path = records[0].split(b"\t", 1)
            mode, object_type, object_id = metadata.decode("ascii").split(" ")
            tracked_path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise SkillSourceError(f"cannot prove {context}: installed release entry is malformed") from error
        if (
            len(records) != 1
            or mode not in {"100644", "100755"}
            or object_type != "blob"
            or tracked_path != relative
        ):
            raise SkillSourceError(f"cannot prove {context}: installed release entry is unsafe")
        try:
            blob = git_result(
                root,
                f"--git-dir={brain_git}",
                "cat-file",
                "blob",
                object_id,
                profile="read-only",
                timeout=3,
            )
            physical = (root / relative).read_bytes()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            raise SkillSourceError(f"cannot prove {context}: installed release bytes are unreadable") from error
        if blob.returncode != 0 or blob.stdout != physical:
            raise SkillSourceError(f"{context} differs from the installed release tree: {relative}")
        return

    if not (root / ".git").exists():
        return
    try:
        result = git_result(
            root,
            "ls-files",
            "--error-unmatch",
            relative,
            profile="read-only",
            timeout=3,
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        raise SkillSourceError(f"cannot prove {context} is tracked: {error}") from error
    if result.returncode != 0:
        raise SkillSourceError(f"{context} is not tracked by the release tree: {relative}")


def _verify_pin(
    *,
    kind: str,
    release_root: Path,
    source_path: str,
    target_path: str,
    sha256: str,
    byte_size: int,
    context: str,
    exact_room_directory: bool = False,
    previous_payloads: tuple[SkillPayloadPin, ...] = (),
) -> SkillSourcePin:
    source = _release_file(release_root, source_path, context=context)
    _require_tracked(release_root, source_path, context=context)
    if exact_room_directory:
        entries = tuple(source.parent.iterdir())
        if len(entries) != 1 or entries[0].name != "SKILL.md" or entries[0] != source:
            raise SkillSourceError(f"{context} directory contains unpinned entries; only SKILL.md is allowed")
    payload = source.read_bytes()
    actual_sha = hashlib.sha256(payload).hexdigest()
    if actual_sha != sha256 or len(payload) != byte_size:
        raise SkillSourceError(
            f"{context} bytes do not match the authoritative sha256 or byte_size "
            f"(declared sha256={sha256} byte_size={byte_size}; "
            f"actual sha256={actual_sha} byte_size={len(payload)})"
        )
    if any(
        previous.sha256 == actual_sha and previous.byte_size == len(payload)
        for previous in previous_payloads
    ):
        raise SkillSourceError(f"{context} repeats the current payload as a previous payload")
    return SkillSourcePin(
        kind=kind,
        source_path=source_path,
        target_path=target_path,
        sha256=actual_sha,
        byte_size=len(payload),
        path=source,
        previous_payloads=previous_payloads,
    )


def _active_skill(reference: Mapping[str, object], release_root: Path) -> SkillSourcePin:
    _exact_fields(
        reference,
        {"kind", "path", "sha256", "byte_size"},
        context="active-skill source",
    )
    path = _relative_path(reference.get("path"), context="active-skill path")
    if not path.startswith(".claude/skills/") or not path.endswith("/SKILL.md"):
        raise SkillSourceError("active-skill path must be a shipped skill SKILL.md")
    if "/_available/" in path:
        raise SkillSourceError("active-skill path must not be dormant")
    if path.startswith(".claude/skills/anthropic-"):
        raise SkillSourceError("active-skill path must not be a vendored skill")
    return _verify_pin(
        kind="active-skill",
        release_root=release_root,
        source_path=path,
        target_path=path,
        sha256=_digest(reference.get("sha256"), context="active-skill sha256"),
        byte_size=_byte_size(reference.get("byte_size"), context="active-skill byte_size"),
        context="active-skill source",
    )


def _lifecycle_items(path: Path) -> dict[str, Mapping[str, object]]:
    document = _mapping(
        _strict_json(path, context="official lifecycle catalogue"),
        context="official lifecycle catalogue",
    )
    _exact_fields(
        document,
        {"catalog_source_version", "items"},
        context="official lifecycle catalogue",
    )
    if document.get("catalog_source_version") != 1:
        raise SkillSourceError("official lifecycle catalogue version is unsupported")
    raw_items = document.get("items")
    if not isinstance(raw_items, list):
        raise SkillSourceError("official lifecycle catalogue items must be an array")

    items: dict[str, Mapping[str, object]] = {}
    for index, raw_item in enumerate(raw_items):
        context = f"official lifecycle item {index}"
        item = _mapping(raw_item, context=context)
        _exact_fields(
            item,
            {"id", "kind", "version", "files", "dependencies", "capabilities"},
            context=context,
        )
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise SkillSourceError(f"{context} id must be non-empty text")
        if item_id in items:
            raise SkillSourceError(f"official lifecycle catalogue has duplicate item id {item_id!r}")
        items[item_id] = item
    return items


def _lifecycle_skill(
    reference: Mapping[str, object],
    release_root: Path,
    lifecycle_catalog_path: Path,
) -> SkillSourcePin:
    _exact_fields(
        reference,
        {"kind", "item_id"},
        context="lifecycle-skill source",
    )
    item_id = reference.get("item_id")
    if not isinstance(item_id, str) or not item_id:
        raise SkillSourceError("lifecycle-skill item_id must be non-empty text")
    item = _lifecycle_items(lifecycle_catalog_path).get(item_id)
    if item is None:
        raise SkillSourceError(f"lifecycle item {item_id!r} was not found")
    if item.get("kind") != "skill":
        raise SkillSourceError(f"lifecycle item {item_id!r} kind must be skill")
    files = item.get("files")
    if not isinstance(files, list) or len(files) != 1:
        raise SkillSourceError(f"lifecycle item {item_id!r} must contain exactly one file")
    declared = _mapping(files[0], context=f"lifecycle item {item_id!r} file")
    _exact_fields(
        declared,
        {"path", "source_path", "sha256", "byte_size"},
        context=f"lifecycle item {item_id!r} file",
    )
    target = _relative_path(declared.get("path"), context=f"lifecycle item {item_id!r} target")
    expected_target = f".claude/skills/{item_id}/SKILL.md"
    if target != expected_target:
        raise SkillSourceError(f"lifecycle item {item_id!r} target must be {expected_target}")
    source = _relative_path(
        declared.get("source_path"),
        context=f"lifecycle item {item_id!r} source",
    )
    if not source.startswith(".claude/skills/_available/") or not source.endswith("/SKILL.md"):
        raise SkillSourceError(f"lifecycle item {item_id!r} source must be a dormant skill SKILL.md")
    if Path(source).parent.name != item_id:
        raise SkillSourceError(
            f"lifecycle item {item_id!r} source identity must come from its {item_id} directory"
        )
    return _verify_pin(
        kind="lifecycle-skill",
        release_root=release_root,
        source_path=source,
        target_path=target,
        sha256=_digest(
            declared.get("sha256"),
            context=f"lifecycle item {item_id!r} sha256",
        ),
        byte_size=_byte_size(
            declared.get("byte_size"),
            context=f"lifecycle item {item_id!r} byte_size",
        ),
        context=f"lifecycle item {item_id!r} source",
    )


def _room_authorities(release_root: Path, portable_contract_path: Path) -> dict[tuple[str, str], Mapping[str, object]]:
    document = _mapping(
        _strict_json(portable_contract_path, context="portable vault contract"),
        context="portable vault contract",
    )
    declared_rooms = document.get("capabilities")
    if not isinstance(declared_rooms, Mapping):
        raise SkillSourceError("portable vault contract has no capability rooms")

    contract_version = document.get("contract_version")
    rooms = declared_rooms
    if contract_version == 1:
        # Portable v1 intentionally has no payload pins. Current runtimes still
        # read its room/folder/config shape, while resolving release-owned skill
        # bytes through the current release's committed v2 authority. This keeps
        # one pin owner and prevents an old caller document from becoming a
        # second, mutable source of executable payload identity.
        for room, raw_spec in declared_rooms.items():
            spec = _mapping(raw_spec, context=f"portable v1 room {room!r}")
            if "skill_sources" in spec:
                raise SkillSourceError("portable v1 rooms must not declare skill_sources")

        authority_path = release_root / DEFAULT_PORTABLE_CONTRACT
        try:
            same_authority = authority_path.resolve() == portable_contract_path.resolve()
        except OSError:
            same_authority = authority_path == portable_contract_path
        if same_authority:
            raise SkillSourceError(
                "portable v1 needs the current release's separate v2 room authority"
            )
        authority_document = _mapping(
            _strict_json(authority_path, context="current portable v2 room authority"),
            context="current portable v2 room authority",
        )
        if authority_document.get("contract_version") != 2:
            raise SkillSourceError("current release room authority must be portable contract v2")
        authority_rooms = authority_document.get("capabilities")
        if not isinstance(authority_rooms, Mapping):
            raise SkillSourceError("current portable v2 room authority has no capability rooms")

        selected_rooms: dict[str, object] = {}
        for room, raw_spec in declared_rooms.items():
            if not isinstance(room, str) or not room:
                raise SkillSourceError("capability room id must be non-empty text")
            declared_spec = _mapping(raw_spec, context=f"portable v1 room {room!r}")
            authority_spec = _mapping(
                authority_rooms.get(room),
                context=f"current portable v2 room {room!r}",
            )
            declared_skills = declared_spec.get("skills", [])
            authority_skills = authority_spec.get("skills", [])
            if declared_skills != authority_skills:
                raise SkillSourceError(
                    f"portable v1 room {room!r} skills do not match the current release authority"
                )
            selected_rooms[room] = authority_spec
        rooms = selected_rooms
    elif contract_version not in (None, 2):
        raise SkillSourceError("portable vault contract version is unsupported")

    authorities: dict[tuple[str, str], Mapping[str, object]] = {}
    target_owners: dict[str, tuple[str, str]] = {}
    for room, raw_spec in rooms.items():
        if not isinstance(room, str) or not room:
            raise SkillSourceError("capability room id must be non-empty text")
        spec = _mapping(raw_spec, context=f"room {room!r}")
        raw_skills = spec.get("skills", [])
        if not isinstance(raw_skills, list) or not all(isinstance(skill, str) and skill for skill in raw_skills):
            raise SkillSourceError(f"room {room!r} skills must be an array of text")
        if len(raw_skills) != len(set(raw_skills)):
            raise SkillSourceError(f"room {room!r} skills contains duplicates")
        raw_pins = spec.get("skill_sources")
        if not isinstance(raw_pins, list):
            raise SkillSourceError(f"room {room!r} skill_sources must be an array")

        room_skills: set[str] = set()
        for index, raw_pin in enumerate(raw_pins):
            context = f"room {room!r} authority {index}"
            pin = _mapping(raw_pin, context=context)
            _exact_fields(
                pin,
                {
                    "room",
                    "skill",
                    "source_path",
                    "target_path",
                    "sha256",
                    "byte_size",
                    "previous_payloads",
                },
                context=context,
            )
            skill = pin.get("skill")
            if pin.get("room") != room or not isinstance(skill, str) or not skill:
                raise SkillSourceError(f"room {room!r} authority must declare the same room and a skill")
            key = (room, skill)
            if key in authorities:
                raise SkillSourceError(f"room {room!r} authority duplicates skill {skill!r}")
            source = _relative_path(pin.get("source_path"), context=f"{context} source_path")
            target = _relative_path(pin.get("target_path"), context=f"{context} target_path")
            expected_source = f".claude/skills/_available/capabilities/{room}/skills/{skill}/SKILL.md"
            expected_target = f".claude/skills/{skill}/SKILL.md"
            if source != expected_source or target != expected_target:
                raise SkillSourceError(f"room {room!r} authority paths do not match skill {skill!r}")
            previous = target_owners.setdefault(target, key)
            if previous != key:
                raise SkillSourceError(f"room authorities duplicate active target {target!r}")
            _digest(pin.get("sha256"), context=f"{context} sha256")
            _byte_size(pin.get("byte_size"), context=f"{context} byte_size")
            _previous_payloads(
                pin.get("previous_payloads"),
                context=f"{context} previous_payloads",
            )
            authorities[key] = pin
            room_skills.add(skill)

        if room_skills != set(raw_skills):
            raise SkillSourceError(f"room {room!r} authority skill_sources must exactly match declared skills")
    return authorities


def resolve_room_skill_sources(
    room: str,
    release_root: Path | str,
    *,
    portable_contract_path: Path | str | None = None,
) -> tuple[SkillSourcePin, ...]:
    """Resolve and verify every skill pin belonging to one capability room."""
    root = Path(release_root).resolve()
    contract = _authority_path(root, portable_contract_path, DEFAULT_PORTABLE_CONTRACT)
    authorities = _room_authorities(root, contract)
    selected = [(skill, raw) for (authority_room, skill), raw in authorities.items() if authority_room == room]
    if not selected:
        document = _mapping(
            _strict_json(contract, context="portable vault contract"),
            context="portable vault contract",
        )
        capabilities = document.get("capabilities")
        if not isinstance(capabilities, Mapping) or room not in capabilities:
            raise SkillSourceError(f"room {room!r} was not found")
    result = []
    for skill, raw in sorted(selected):
        result.append(
            _verify_pin(
                kind="room-skill",
                release_root=root,
                source_path=str(raw["source_path"]),
                target_path=str(raw["target_path"]),
                sha256=str(raw["sha256"]),
                byte_size=int(raw["byte_size"]),
                context=f"room {room!r} skill {skill!r} source identity",
                exact_room_directory=True,
                previous_payloads=_previous_payloads(
                    raw.get("previous_payloads"),
                    context=f"room {room!r} skill {skill!r} previous_payloads",
                ),
            )
        )
    return tuple(result)


def _room_skill(
    reference: Mapping[str, object],
    release_root: Path,
    portable_contract_path: Path,
) -> SkillSourcePin:
    _exact_fields(
        reference,
        {"kind", "room", "skill"},
        context="room-skill source",
    )
    room = reference.get("room")
    skill = reference.get("skill")
    if not isinstance(room, str) or not room or not isinstance(skill, str) or not skill:
        raise SkillSourceError("room-skill room and skill must be non-empty text")
    pins = resolve_room_skill_sources(
        room,
        release_root,
        portable_contract_path=portable_contract_path,
    )
    matches = [pin for pin in pins if pin.target_path == f".claude/skills/{skill}/SKILL.md"]
    if len(matches) != 1:
        raise SkillSourceError(f"room {room!r} skill authority for {skill!r} was not found exactly once")
    return matches[0]


def resolve_skill_source(
    reference: object,
    release_root: Path | str,
    *,
    lifecycle_catalog_path: Path | str | None = None,
    portable_contract_path: Path | str | None = None,
) -> SkillSourcePin:
    """Resolve a closed Lens source reference to release-owned, verified bytes."""
    root = Path(release_root).resolve()
    raw = _mapping(reference, context="skill source")
    kind = raw.get("kind")
    if kind == "active-skill":
        return _active_skill(raw, root)
    if kind == "lifecycle-skill":
        lifecycle = _authority_path(root, lifecycle_catalog_path, DEFAULT_LIFECYCLE_CATALOG)
        return _lifecycle_skill(raw, root, lifecycle)
    if kind == "room-skill":
        contract = _authority_path(root, portable_contract_path, DEFAULT_PORTABLE_CONTRACT)
        return _room_skill(raw, root, contract)
    raise SkillSourceError("skill source kind must be active-skill, lifecycle-skill, or room-skill")
