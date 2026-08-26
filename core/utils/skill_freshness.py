"""Make a skill that just landed on disk usable in this session.

The host slash list is loaded at session start. Dex has no event that
refreshes it: `.claude/settings.json` wires SessionStart, UserPromptSubmit,
PreToolUse, Stop, Notification, and SessionEnd only. CLAUDE.md recomposition
(`.claude/hooks/claude-composition-refresh.sh`) keeps personal instructions
live; it does not republish the slash-skill list. After an update writes a
new `.claude/skills/<name>/SKILL.md`, the slash menu can still omit it until
the next session.

This module is the Dex-owned path. SessionStart records which skills were
already on disk. UserPromptSubmit then injects any skill that arrived later
(and any on-disk skill the user already named with a slash) as additional
context so the current turn can Read the SKILL.md and follow it.

HOST_SLASH_LIST_REFRESHABLE is False on purpose. A test fails if someone
claims Dex can reload the host menu.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

HOST_SLASH_LIST_REFRESHABLE = False

SKILLS_RELATIVE = Path(".claude") / "skills"
SKILL_FILENAME = "SKILL.md"
FRONTMATTER_DESCRIPTION = re.compile(
    r"^description:\s*(?P<value>.+?)\s*$",
    re.MULTILINE,
)
SLASH_MENTION = re.compile(
    r"(?:^|[\s`\"'(])/(?P<name>[a-z0-9]+(?:-[a-z0-9]+)*)\b"
)


def vault_root_from_env() -> Path:
    configured = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("VAULT_PATH")
    if configured:
        return Path(configured)
    return Path.cwd()


def state_dir(vault: Path) -> Path:
    override = os.environ.get("DEX_SKILL_FRESHNESS_STATE_DIR")
    if override:
        return Path(override)
    digest = hashlib.sha256(str(vault.resolve()).encode("utf-8")).hexdigest()[:16]
    return Path("/tmp") / f"dex-skill-freshness-{digest}"


def snapshot_path(vault: Path, session_id: str = "default") -> Path:
    safe_session = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id) or "default"
    return state_dir(vault) / f"{safe_session}.json"


def list_installed_skills(vault: Path) -> dict[str, Path]:
    """Map skill directory name → SKILL.md for installed, non-hidden skills."""
    root = vault / SKILLS_RELATIVE
    skills: dict[str, Path] = {}
    if not root.is_dir():
        return skills
    try:
        children = list(root.iterdir())
    except OSError:
        return skills
    for child in children:
        name = child.name
        if name.startswith("_") or name.startswith("."):
            continue
        skill_md = child / SKILL_FILENAME
        try:
            if child.is_dir() and skill_md.is_file():
                skills[name] = skill_md
        except OSError:
            continue
    return skills


def _read_description(skill_md: Path) -> str:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return ""
    match = FRONTMATTER_DESCRIPTION.search(text)
    if not match:
        return ""
    value = match.group("value").strip()
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        value = value[1:-1]
    # One line, short enough for hook context.
    value = " ".join(value.split())
    if len(value) > 160:
        value = value[:157] + "..."
    return value


def skills_named_in_prompt(prompt: str, installed: dict[str, Path]) -> set[str]:
    if not prompt or not installed:
        return set()
    names = {match.group("name") for match in SLASH_MENTION.finditer(prompt)}
    return names & set(installed)


def load_snapshot(vault: Path, session_id: str = "default") -> set[str] | None:
    path = snapshot_path(vault, session_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    names = payload.get("skills") if isinstance(payload, dict) else None
    if not isinstance(names, list):
        return None
    return {name for name in names if isinstance(name, str)}


def save_snapshot(vault: Path, skills: dict[str, Path], session_id: str = "default") -> None:
    path = snapshot_path(vault, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "skills": sorted(skills),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def skills_to_inject(
    installed: dict[str, Path],
    snapshot: set[str] | None,
    prompt: str = "",
) -> dict[str, Path]:
    """Skills the current turn must be able to run without a host restart.

    - Skills that arrived after the session snapshot (typical: an update just
      wrote a new SKILL.md).
    - Skills the user already named with a slash that are on disk but were
      not in the snapshot (the slash menu omitted them).
    """
    if snapshot is None:
        named = skills_named_in_prompt(prompt, installed)
        return {name: installed[name] for name in named}
    arrived = set(installed) - snapshot
    named = skills_named_in_prompt(prompt, installed) - snapshot
    inject = arrived | named
    return {name: installed[name] for name in sorted(inject)}


def additional_context_for(skills: dict[str, Path], vault: Path) -> str:
    if not skills:
        return ""
    lines = [
        "<skill_freshness>",
        "These skills are on disk and live in this session. The host slash "
        "menu may omit them until the next session; that does not make them "
        "unavailable. If the user asks for one, Read the SKILL.md path now "
        "and follow it. Do not ask them to restart first.",
        "",
    ]
    for name in sorted(skills):
        relative = skills[name]
        try:
            shown = relative.relative_to(vault).as_posix()
        except ValueError:
            shown = relative.as_posix()
        description = _read_description(relative)
        suffix = f" — {description}" if description else ""
        lines.append(f"- /{name} — {shown}{suffix}")
    lines.append("</skill_freshness>")
    return "\n".join(lines)


def record_session_snapshot(vault: Path, session_id: str = "default") -> dict[str, Path]:
    installed = list_installed_skills(vault)
    save_snapshot(vault, installed, session_id)
    return installed


def context_for_prompt(
    vault: Path,
    prompt: str,
    session_id: str = "default",
) -> str:
    installed = list_installed_skills(vault)
    snapshot = load_snapshot(vault, session_id)
    if snapshot is None:
        # First sighting this session: remember what was already here so a
        # later update can be detected, and still inject a skill the user
        # already named.
        to_inject = skills_to_inject(installed, None, prompt)
        save_snapshot(vault, installed, session_id)
        return additional_context_for(to_inject, vault)
    to_inject = skills_to_inject(installed, snapshot, prompt)
    return additional_context_for(to_inject, vault)


def hook_payload(event_name: str, context: str) -> dict:
    return {
        "continue": True,
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": context,
        },
    }


def handle_hook_event(payload: object, vault: Path | None = None) -> dict | None:
    """Return a UserPromptSubmit hook payload, or None for silence.

    SessionStart records the snapshot and stays silent. Any failure is
    silence: a vault that cannot advertise a new skill is no worse off
    than before this hook existed.
    """
    if not isinstance(payload, dict):
        return None
    root = vault if vault is not None else vault_root_from_env()
    event = payload.get("hook_event_name") or payload.get("hookEventName") or ""
    session_id = payload.get("session_id") or payload.get("sessionId") or "default"
    if not isinstance(session_id, str) or not session_id:
        session_id = "default"

    if event == "SessionStart":
        record_session_snapshot(root, session_id)
        return None

    if event != "UserPromptSubmit":
        return None

    prompt = payload.get("prompt") if isinstance(payload.get("prompt"), str) else ""
    context = context_for_prompt(root, prompt, session_id)
    if not context:
        return None
    return hook_payload("UserPromptSubmit", context)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        raw = sys.stdin.read()
        payload: object
        if raw.strip():
            payload = json.loads(raw)
        else:
            payload = {}
        if args and args[0] == "--session-start":
            if isinstance(payload, dict):
                payload = {**payload, "hook_event_name": payload.get("hook_event_name") or "SessionStart"}
            else:
                payload = {"hook_event_name": "SessionStart"}
        result = handle_hook_event(payload)
        if result:
            print(json.dumps(result))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
