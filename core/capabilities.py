"""Registry-backed state and provisioning for optional Dex capability rooms.

The generated portable-vault contract is the only room manifest.  This module
adds user state from ``System/user-profile.yaml`` and a generic provisioning
convention; it deliberately contains no room-specific folder, skill, MCP, or
feature lists.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
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
            if (
                path.is_symlink()
                or not path.is_file()
                or path.name in {".DS_Store", ".gitkeep"}
            ):
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


def _preflight_room_assets(
    root: Path,
    room: str,
    surfaces: Mapping[str, Any],
) -> Path:
    dormant = _dormant_root(room, root)
    for skill in surfaces.get("skills", []):
        source = dormant / "skills" / str(skill)
        if not source.is_dir():
            raise CapabilityError(
                f"Dormant skill is missing for {room}: {source}"
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
        else _dormant_root(room, root)
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


def migrate_legacy_room_state(
    vault_root: Path | str,
    *,
    profile_path: Path | str | None = None,
    contract_path: Path | str | None = None,
) -> list[str]:
    """One-time bridge for vaults onboarded before capability rooms existed.

    Preserve each room's pre-migration behavior without overriding an explicit
    capability value or a legacy config value. Companies is pinned off because
    its fresh-vault default is now on; Career and Quarter Goals keep the earlier
    bridge's on default when they have no prior opinion. Fresh installs write
    explicit room answers at onboarding and are never touched here. Returns the
    rooms seeded (empty when no migration was needed).
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
        {"companies": False}
        if isinstance(capability_state, Mapping)
        else {
            "career": True,
            "companies": False,
            "quarter_goals": True,
        }
    )
    seeded: list[str] = []
    for room in room_ids(contract_path=contract_path):
        room_state = (
            capability_state.get(room)
            if isinstance(capability_state, Mapping)
            else None
        )
        if (
            isinstance(room_state, Mapping)
            and isinstance(room_state.get("enabled"), bool)
        ):
            continue
        surfaces = surfaces_for(room, contract_path=contract_path)
        legacy_config = surfaces.get("config")
        if isinstance(legacy_config, str):
            legacy = profile.get(legacy_config)
            if (
                isinstance(legacy, Mapping)
                and isinstance(legacy.get("enabled"), bool)
            ):
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
    migrate_legacy_room_state(
        root, profile_path=profile, contract_path=contract_path
    )
    return [
        reconcile_room(
            room,
            enabled(room, profile_path=profile, contract_path=contract_path),
            vault_root=root,
            contract_path=contract_path,
        )
        for room in room_ids(contract_path=contract_path)
    ]


def _atomic_text_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
            addition = (
                f"{suffix}{block_key}:{newline}  {room}:{newline}"
                f"    enabled: {rendered}{newline}"
            )
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
    """Render the one-time Companies-off pin without rewriting profile prose.

    ``None`` means the profile already has an explicit or legacy opinion.
    Invalid state fails closed so an update cannot fall through to the new
    contract default or replace user-owned data. Profiles with no capability
    map also retain the earlier Career/Quarter bridge defaults in the same
    transaction; partial maps gain only the Companies pin.
    """
    try:
        profile = yaml.safe_load(original) or {}
    except yaml.YAMLError as exc:
        raise CapabilityError("Profile must contain valid YAML") from exc
    if not isinstance(profile, dict):
        raise CapabilityError("Profile must contain an object")

    capability_state = profile.get("capabilities")
    if capability_state is not None and not isinstance(capability_state, Mapping):
        raise CapabilityError("Profile capabilities must contain an object")
    company_state = (
        capability_state.get("companies")
        if isinstance(capability_state, Mapping)
        else None
    )
    if company_state is not None and not isinstance(company_state, Mapping):
        raise CapabilityError("Profile capabilities.companies must contain an object")
    if isinstance(company_state, Mapping) and "enabled" in company_state:
        if not isinstance(company_state["enabled"], bool):
            raise CapabilityError(
                "Profile capabilities.companies.enabled must be true or false"
            )
        return None
    company_surfaces = surfaces_for("companies", contract_path=contract_path)
    company_legacy_config = company_surfaces.get("config")
    if isinstance(company_legacy_config, str):
        company_legacy_state = profile.get(company_legacy_config)
        if (
            isinstance(company_legacy_state, Mapping)
            and "enabled" in company_legacy_state
        ):
            if not isinstance(company_legacy_state["enabled"], bool):
                raise CapabilityError(
                    f"Profile {company_legacy_config}.enabled must be true or false"
                )
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
        room_state = (
            capability_state.get(room)
            if isinstance(capability_state, Mapping)
            else None
        )
        if isinstance(room_state, Mapping) and "enabled" in room_state:
            if not isinstance(room_state["enabled"], bool):
                raise CapabilityError(
                    f"Profile capabilities.{room}.enabled must be true or false"
                )
            continue
        surfaces = surfaces_for(room, contract_path=contract_path)
        legacy_config = surfaces.get("config")
        if isinstance(legacy_config, str):
            legacy_state = profile.get(legacy_config)
            if isinstance(legacy_state, Mapping) and "enabled" in legacy_state:
                if not isinstance(legacy_state["enabled"], bool):
                    raise CapabilityError(
                        f"Profile {legacy_config}.enabled must be true or false"
                    )
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
    # or unreadable user state with an empty profile. strict=True raises on
    # unreadable YAML before any edit is attempted.
    _read_profile(profile_file, strict=True)
    original = (
        profile_file.read_text(encoding="utf-8") if profile_file.exists() else ""
    )

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
        raise CapabilityError(
            "profile edit produced invalid YAML; refusing to write"
        ) from exc
    room_state = (
        reparsed.get("capabilities", {}).get(room, {})
        if isinstance(reparsed.get("capabilities"), Mapping)
        else {}
    )
    if not isinstance(room_state, Mapping) or room_state.get("enabled") is not room_enabled:
        raise CapabilityError(
            "profile edit did not produce the intended room state; refusing to write"
        )

    _atomic_text_write(profile_file, updated)
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
