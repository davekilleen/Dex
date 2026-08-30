"""Name every written Dex door on this machine.

A confirmed door is a host chosen in the saved harness receipt.
A walked door is a Dex install artifact on this machine.
A written door with no install artifact has never been opened.
Confirming a door is not the same as walking it.

This module never writes a grant, a grant receipt, or a grant flag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from core.harnesses.registry import list_profiles

CONFIRMED_IS_NOT_WALKED = "A confirmed door is not the same as a walked one."
NOTES_PANEL_INSTALLED = "The notes panel is installed on this machine."
NOTES_PANEL_MISSING = "The notes panel is not installed on this machine."
NOTES_PANEL_MANIFEST = Path(".obsidian") / "plugins" / "dex-readonly" / "manifest.json"

# Every written adapter must have a walk rule. `None` means Doctor cannot prove
# a walk, so the door stays unopened until a later lot names a real marker.
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

_DEX_MANIFEST_NAMES = frozenset({"plugin.json", "gemini-extension.json"})
_DEX_MANIFEST_IDS = frozenset({"dex", "dex-gemini-extension"})


@dataclass(frozen=True)
class DoorState:
    """One written host door and the sentences Doctor should keep verbatim."""

    id: str
    name: str
    confirmed: bool
    walked: bool
    sentence: str

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "confirmed": self.confirmed,
            "walked": self.walked,
            "sentence": self.sentence,
        }


@dataclass(frozen=True)
class DoorReport:
    """Machine-local door roll-up for Doctor's harness-receipt pass."""

    doors: tuple[DoorState, ...]
    notes_panel_installed: bool
    notes_panel_sentence: str
    confirmed_is_not_walked: str = CONFIRMED_IS_NOT_WALKED

    def sentences(self) -> tuple[str, ...]:
        return (
            *(door.sentence for door in self.doors),
            self.notes_panel_sentence,
            self.confirmed_is_not_walked,
        )

    def as_structured(self) -> dict[str, object]:
        return {
            "doors": [door.as_dict() for door in self.doors],
            "notes_panel": {
                "installed": self.notes_panel_installed,
                "sentence": self.notes_panel_sentence,
            },
            "confirmed_is_not_walked": self.confirmed_is_not_walked,
        }


def door_sentence(*, name: str, confirmed: bool, walked: bool) -> str:
    """Return one plain sentence for a written door."""
    if confirmed and walked:
        return f"You confirmed {name}, and it is walked on this machine."
    if confirmed:
        return f"You confirmed {name}."
    if walked:
        return f"{name} is walked on this machine and not confirmed."
    return f"{name} is a written door you have never opened."


def notes_panel_installed(vault_root: Path) -> bool:
    """Return True only when the notes-panel plugin manifest is present."""
    return _is_regular_file(Path(vault_root) / NOTES_PANEL_MANIFEST)


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


def door_report(
    *,
    home: Path,
    vault_root: Path,
    confirmed_ids: Iterable[str] | None = None,
) -> DoorReport:
    """Describe every written adapter door plus the notes panel on this machine."""
    _assert_walk_rules_cover_the_adapter_registry()
    confirmed = {item for item in (confirmed_ids or ()) if isinstance(item, str) and item}
    doors: list[DoorState] = []
    for profile in list_profiles():
        walked = door_is_walked(profile.id, home=home)
        is_confirmed = profile.id in confirmed
        doors.append(
            DoorState(
                id=profile.id,
                name=profile.display_name,
                confirmed=is_confirmed,
                walked=walked,
                sentence=door_sentence(
                    name=profile.display_name,
                    confirmed=is_confirmed,
                    walked=walked,
                ),
            )
        )
    installed = notes_panel_installed(vault_root)
    return DoorReport(
        doors=tuple(doors),
        notes_panel_installed=installed,
        notes_panel_sentence=NOTES_PANEL_INSTALLED if installed else NOTES_PANEL_MISSING,
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


def _assert_walk_rules_cover_the_adapter_registry() -> None:
    adapter_ids = {profile.id for profile in list_profiles()}
    rule_ids = set(WALK_RULES)
    if rule_ids != adapter_ids:
        raise RuntimeError(
            "door walk rules must cover every written adapter: "
            f"missing={sorted(adapter_ids - rule_ids)} extra={sorted(rule_ids - adapter_ids)}"
        )


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
