"""Name every written Dex door on this machine.

A confirmed door is a host chosen in the saved harness receipt.
A walked door is a Dex install artifact on this machine.
A detectable written door with no install artifact has never been opened.
A written door this checkup cannot detect is named as unseen, not as never opened.
A left door is a walk artifact that is gone while leftover residue remains.
Confirming a door is not the same as walking it.
A confirmed door is not a leave. Leftovers are named only when a leave is proved.
Notes-panel checks read one vault's own files; the sentences claim that vault, never the machine.

This module never writes a grant, a grant receipt, or a grant flag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from core.harnesses.registry import list_profiles

CONFIRMED_IS_NOT_WALKED = "A confirmed door is not the same as a walked one."
NOTES_PANEL_INSTALLED = "The notes panel is installed in this vault."
NOTES_PANEL_MISSING = (
    "The notes panel is not installed in this vault. "
    "This checkup looked only in this vault, not across the machine."
)
NOTES_PANEL_SWITCH = "`.obsidian/community-plugins.json` listing `dex-readonly`"
NOTES_PANEL_HALF_ON = (
    "The notes panel files are there, but the panel is not switched on. "
    f"The switch is {NOTES_PANEL_SWITCH}; this checkup will not flip it."
)
NOTES_PANEL_LEFTOVER = (
    "`.obsidian/community-plugins.json` may still list `dex-readonly` until you "
    "remove that name; the workspace layout may still show an empty Dex panel slot."
)
NOTES_PANEL_MANIFEST = Path(".obsidian") / "plugins" / "dex-readonly" / "manifest.json"
NOTES_PANEL_COMMUNITY_PLUGINS = Path(".obsidian") / "community-plugins.json"


def cannot_see_opened_sentence(name: str) -> str:
    """Return the unseen-door sentence. Copy is final."""
    return (
        f"{name} is a written door and this checkup cannot see whether you have "
        "opened it."
    )


def never_opened_sentence(name: str) -> str:
    """Return the detectable never-opened sentence. Copy is final."""
    return f"{name} is a written door you have never opened."


# Every written adapter must have a walk rule. `None` means this checkup cannot
# see whether the door has been opened. Do not add a marker here to invent a walk.
WALK_RULES: dict[str, tuple[str, str] | None] = {
    "agent-plugin": None,
    "bb": None,
    "chatgpt-work": ("home-file", ".codex/plugins/dex/.codex-plugin/plugin.json"),
    "claude-code": None,
    "claude-desktop": None,
    "codex": None,
    "copilot-cli": ("home-dex-manifest", ".copilot/installed-plugins/_direct"),
    "cowork": None,
    "cursor": ("home-file", ".cursor/plugins/local/dex/.cursor-plugin/plugin.json"),
    "gemini-cli": ("home-dex-manifest", ".gemini/extensions"),
    "pi": None,
}

# Leftover copy is final. A detector that is missing cannot prove a leave.
LEFTOVER_COPY: dict[str, str] = {
    "agent-plugin": "none that Dex owns; Dex does not claim a cache here.",
    "bb": "the vault setting; local source files stay on disk.",
    "chatgpt-work": (
        "the vault-folder grant — a person must revoke it; this runner will not "
        "invent that grant. The cache at `~/.codex/plugins/cache/dex-unreleased/dex/local/` "
        "is not Work proof."
    ),
    "claude-code": "plugin cache and hook trust.",
    "claude-desktop": "the Dex vault path in that extension's configuration.",
    "codex": "hook trust in `~/.codex/config.toml`.",
    "copilot-cli": "a direct-install copy under `~/.copilot/installed-plugins/_direct/`.",
    "cowork": "the Dex folder grant.",
    "cursor": "hook approval.",
    "gemini-cli": "hook approval in Gemini CLI settings.",
    "pi": "extension registration in Pi settings until a new session.",
}

# Residue that can prove a leave. Empty means Doctor cannot prove a leave.
LEFTOVER_DETECTORS: dict[str, tuple[tuple[str, str], ...]] = {
    "agent-plugin": (),
    "bb": (),
    "chatgpt-work": (
        ("home-dir", ".codex/plugins/cache/dex-unreleased/dex/local"),
        ("home-marketplace-dex", ".agents/plugins/marketplace.json"),
    ),
    "claude-code": (),
    "claude-desktop": (),
    "codex": (),
    "copilot-cli": (("home-named-dir-without-walk", ".copilot/installed-plugins/_direct"),),
    "cowork": (),
    "cursor": (("home-dir-without-walk", ".cursor/plugins/local/dex"),),
    "gemini-cli": (("home-named-dir-without-walk", ".gemini/extensions"),),
    "pi": (),
}

_DEX_MANIFEST_NAMES = frozenset({"plugin.json", "gemini-extension.json"})
_DEX_MANIFEST_IDS = frozenset({"dex", "dex-gemini-extension"})
_DEX_LEFTOVER_DIR_NAMES = frozenset({"dex", "dex-agent-plugin", "dex-gemini-extension"})


@dataclass(frozen=True)
class DoorState:
    """One written host door and the sentences Doctor should keep verbatim."""

    id: str
    name: str
    confirmed: bool
    walked: bool
    left: bool
    leftover: str | None
    sentence: str

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "name": self.name,
            "confirmed": self.confirmed,
            "walked": self.walked,
            "left": self.left,
            "sentence": self.sentence,
        }
        if self.leftover is not None:
            payload["leftover"] = self.leftover
        return payload


@dataclass(frozen=True)
class DoorReport:
    """Machine-local door roll-up for Doctor's harness-receipt pass."""

    doors: tuple[DoorState, ...]
    notes_panel_installed: bool
    notes_panel_switched_on: bool
    notes_panel_left: bool
    notes_panel_sentence: str
    notes_panel_leftover: str | None = None
    notes_panel_switch: str | None = None
    confirmed_is_not_walked: str = CONFIRMED_IS_NOT_WALKED

    def sentences(self) -> tuple[str, ...]:
        return (
            *(door.sentence for door in self.doors),
            self.notes_panel_sentence,
            self.confirmed_is_not_walked,
        )

    def as_structured(self) -> dict[str, object]:
        notes_panel: dict[str, object] = {
            "installed": self.notes_panel_installed,
            "switched_on": self.notes_panel_switched_on,
            "left": self.notes_panel_left,
            "sentence": self.notes_panel_sentence,
        }
        if self.notes_panel_leftover is not None:
            notes_panel["leftover"] = self.notes_panel_leftover
        if self.notes_panel_switch is not None:
            notes_panel["switch"] = self.notes_panel_switch
        return {
            "doors": [door.as_dict() for door in self.doors],
            "notes_panel": notes_panel,
            "confirmed_is_not_walked": self.confirmed_is_not_walked,
        }


def door_is_detectable(profile_id: str) -> bool:
    """Return True when this checkup has a walk marker for the door."""
    if profile_id not in WALK_RULES:
        raise KeyError(profile_id)
    return WALK_RULES[profile_id] is not None


def door_sentence(
    *,
    name: str,
    confirmed: bool,
    walked: bool,
    leftover: str | None = None,
    detectable: bool = True,
) -> str:
    """Return one plain sentence for a written door."""
    if confirmed and walked:
        return f"You confirmed {name}, and it is walked on this machine."
    if walked:
        return f"{name} is walked on this machine and not confirmed."
    if leftover:
        return f"You left {name}. Leftover: {leftover}"
    if confirmed:
        return f"You confirmed {name}."
    if not detectable:
        return cannot_see_opened_sentence(name)
    return never_opened_sentence(name)


def notes_panel_sentence(*, installed: bool, leftover: bool, switched_on: bool) -> str:
    """Return the notes-panel sentence, naming a half-on switch or leftover residue."""
    if installed and switched_on:
        return NOTES_PANEL_INSTALLED
    if installed:
        return NOTES_PANEL_HALF_ON
    if leftover:
        return f"{NOTES_PANEL_MISSING} Leftover: {NOTES_PANEL_LEFTOVER}"
    return NOTES_PANEL_MISSING


def notes_panel_installed(vault_root: Path) -> bool:
    """Return True only when the notes-panel plugin manifest is present."""
    return _is_regular_file(Path(vault_root) / NOTES_PANEL_MANIFEST)


def notes_panel_switched_on(vault_root: Path) -> bool:
    """Return True when the notes-panel switch lists dex-readonly."""
    return _community_plugins_list_dex_readonly(Path(vault_root) / NOTES_PANEL_COMMUNITY_PLUGINS)


def notes_panel_leftover_present(vault_root: Path) -> bool:
    """Return True when the notes-panel listing remains after the plugin is gone."""
    return notes_panel_switched_on(vault_root)


def door_is_walked(profile_id: str, *, home: Path) -> bool:
    """Return True only when this machine has Dex install evidence for the door."""
    if profile_id not in WALK_RULES:
        raise KeyError(profile_id)
    rule = WALK_RULES[profile_id]
    if rule is None:
        return False
    kind, relative = rule
    target = Path(home).joinpath(*Path(relative).parts)
    if kind == "home-file":
        return _is_regular_file(target)
    if kind == "home-dex-manifest":
        return _tree_has_dex_manifest(target)
    raise RuntimeError(f"unsupported walk rule {kind!r} for {profile_id}")


def door_leftover(profile_id: str, *, home: Path) -> str | None:
    """Return leftover copy when residue remains and the walk artifact is gone."""
    if profile_id not in LEFTOVER_COPY or profile_id not in LEFTOVER_DETECTORS:
        raise KeyError(profile_id)
    if door_is_walked(profile_id, home=home):
        return None
    if not _leftover_residue_present(profile_id, home=home):
        return None
    return LEFTOVER_COPY[profile_id]


def door_report(
    *,
    home: Path,
    vault_root: Path,
    confirmed_ids: Iterable[str] | None = None,
) -> DoorReport:
    """Describe every written adapter door plus the notes panel on this machine."""
    _assert_leave_rules_cover_the_adapter_registry()
    confirmed = {item for item in (confirmed_ids or ()) if isinstance(item, str) and item}
    doors: list[DoorState] = []
    for profile in list_profiles():
        walked = door_is_walked(profile.id, home=home)
        leftover = door_leftover(profile.id, home=home)
        is_confirmed = profile.id in confirmed
        detectable = door_is_detectable(profile.id)
        doors.append(
            DoorState(
                id=profile.id,
                name=profile.display_name,
                confirmed=is_confirmed,
                walked=walked,
                left=leftover is not None,
                leftover=leftover,
                sentence=door_sentence(
                    name=profile.display_name,
                    confirmed=is_confirmed,
                    walked=walked,
                    leftover=leftover,
                    detectable=detectable,
                ),
            )
        )
    installed = notes_panel_installed(vault_root)
    switched_on = notes_panel_switched_on(vault_root)
    leftover_notes = (not installed) and switched_on
    half_on = installed and not switched_on
    return DoorReport(
        doors=tuple(doors),
        notes_panel_installed=installed,
        notes_panel_switched_on=switched_on,
        notes_panel_left=leftover_notes,
        notes_panel_leftover=NOTES_PANEL_LEFTOVER if leftover_notes else None,
        notes_panel_switch=NOTES_PANEL_SWITCH if half_on else None,
        notes_panel_sentence=notes_panel_sentence(
            installed=installed,
            leftover=leftover_notes,
            switched_on=switched_on,
        ),
    )


def attach_door_sentences(detail: str, report: DoorReport) -> str:
    """Append one sentence per door, the notes panel, then confirmed-is-not-walked."""
    return _join_sentences(detail, report.sentences())


def _join_sentences(detail: str, extras: Sequence[str]) -> str:
    parts: list[str] = []
    head = " ".join(str(detail).split())
    if head:
        if head[-1] not in ".?!":
            head += "."
        parts.append(head)
    for extra in extras:
        sentence = " ".join(str(extra).split())
        if not sentence:
            continue
        if sentence[-1] not in ".?!":
            sentence += "."
        parts.append(sentence)
    return " ".join(parts)


def _assert_leave_rules_cover_the_adapter_registry() -> None:
    adapter_ids = {profile.id for profile in list_profiles()}
    rule_ids = set(WALK_RULES)
    leftover_ids = set(LEFTOVER_COPY)
    detector_ids = set(LEFTOVER_DETECTORS)
    if rule_ids != adapter_ids:
        raise RuntimeError(
            "door walk rules must cover every written adapter: "
            f"missing={sorted(adapter_ids - rule_ids)} extra={sorted(rule_ids - adapter_ids)}"
        )
    if leftover_ids != adapter_ids:
        raise RuntimeError(
            "leftover copy must cover every written adapter: "
            f"missing={sorted(adapter_ids - leftover_ids)} extra={sorted(leftover_ids - adapter_ids)}"
        )
    if detector_ids != adapter_ids:
        raise RuntimeError(
            "leftover detectors must cover every written adapter: "
            f"missing={sorted(adapter_ids - detector_ids)} extra={sorted(detector_ids - adapter_ids)}"
        )


def _leftover_residue_present(profile_id: str, *, home: Path) -> bool:
    for kind, relative in LEFTOVER_DETECTORS[profile_id]:
        target = Path(home).joinpath(*Path(relative).parts)
        if kind == "home-dir":
            if _is_real_dir(target):
                return True
        elif kind == "home-dir-without-walk":
            if _is_real_dir(target) or _is_regular_file(target):
                return True
        elif kind == "home-named-dir-without-walk":
            if _named_leftover_dir(target):
                return True
        elif kind == "home-marketplace-dex":
            if _marketplace_lists_dex(target):
                return True
        else:
            raise RuntimeError(f"unsupported leftover detector {kind!r} for {profile_id}")
    return False


def _is_real_dir(path: Path) -> bool:
    try:
        return path.is_dir() and not path.is_symlink()
    except OSError:
        return False


def _named_leftover_dir(root: Path) -> bool:
    try:
        if not root.is_dir() or root.is_symlink():
            return False
        for entry in root.iterdir():
            try:
                if entry.is_symlink():
                    continue
                if entry.name in _DEX_LEFTOVER_DIR_NAMES:
                    return True
            except OSError:
                continue
    except OSError:
        return False
    return False


def _marketplace_lists_dex(path: Path) -> bool:
    try:
        if not path.is_file() or path.is_symlink():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, Mapping):
        return False
    plugins = payload.get("plugins")
    if not isinstance(plugins, list):
        return False
    for plugin in plugins:
        if isinstance(plugin, Mapping) and plugin.get("name") == "dex":
            return True
    return False


def _community_plugins_list_dex_readonly(path: Path) -> bool:
    try:
        if not path.is_file() or path.is_symlink():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if isinstance(payload, list):
        return "dex-readonly" in payload
    if isinstance(payload, Mapping):
        plugins = payload.get("plugins")
        if isinstance(plugins, list) and "dex-readonly" in plugins:
            return True
        enabled = payload.get("enabledPlugins")
        if isinstance(enabled, list) and "dex-readonly" in enabled:
            return True
    return False


def _is_regular_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _manifest_is_dex(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, Mapping):
        return False
    name = payload.get("name")
    return isinstance(name, str) and name in _DEX_MANIFEST_IDS


def _tree_has_dex_manifest(root: Path, *, max_depth: int = 4, max_files: int = 80) -> bool:
    try:
        if root.is_file() and root.name in _DEX_MANIFEST_NAMES:
            return _manifest_is_dex(root)
        if not root.is_dir():
            return False
    except OSError:
        return False
    stack: list[tuple[Path, int]] = [(root, 0)]
    seen = 0
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if seen > max_files:
                return False
            try:
                if entry.is_symlink():
                    continue
                if entry.is_file() and entry.name in _DEX_MANIFEST_NAMES:
                    if _manifest_is_dex(entry):
                        return True
                elif entry.is_dir() and depth < max_depth:
                    stack.append((entry, depth + 1))
            except OSError:
                continue
    return False
