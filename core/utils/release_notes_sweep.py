#!/usr/bin/env python3
"""Surface local release notes once after an installed Dex update."""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path

if __package__:
    from .update_verifier import EvidenceError, SemVer, UpdateVerifier
else:
    from update_verifier import EvidenceError, SemVer, UpdateVerifier

STATE_PATH = Path("System/.dex/release-notes-state.json")
RELEASES_URL = "https://heydex.ai/releases/"
_HEADING_RE = re.compile(
    r"^## \[(?P<version>\d+\.\d+\.\d+)\]\s+—\s*(?P<headline>.*?)\s*\(\d{4}-\d{2}-\d{2}\)\s*$",
    re.MULTILINE,
)
_BOLD_LEAD_RE = re.compile(r"^\s*[*-]\s+\*\*(?P<lead>[^*]+)\*\*", re.MULTILINE)


class _MalformedState(ValueError):
    """The local announcement state cannot be trusted."""


def _state_path(vault: Path) -> Path:
    return vault / STATE_PATH


@contextmanager
def _state_lock(vault: Path):
    """Serialize session starts so one installed version can notify only once."""
    directory = _state_path(vault).parent
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(directory / "release-notes-state.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _installed_version(vault: Path) -> str:
    """Use update_verifier's exact installed-version evidence path."""
    return UpdateVerifier(vault)._current_version()


def _write_state(vault: Path, version: str) -> None:
    path = _state_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"last_announced_version": version}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_state(vault: Path) -> str:
    try:
        value = json.loads(_state_path(vault).read_text(encoding="utf-8"))
        version = value.get("last_announced_version") if isinstance(value, dict) else None
        SemVer.parse(version)
    except (OSError, UnicodeError, json.JSONDecodeError, EvidenceError) as error:
        raise _MalformedState from error
    return version


def _release_entry(changelog: str, version: str) -> "tuple[str, list[str]] | None":
    headings = list(_HEADING_RE.finditer(changelog))
    for index, heading in enumerate(headings):
        if heading.group("version") != version:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
        body = changelog[heading.end() : end]
        leads = [match.group("lead").rstrip(".") for match in _BOLD_LEAD_RE.finditer(body)]
        return heading.group("headline").strip(), leads[:3]
    return None


def _notice(vault: Path, version: str, last_announced: str) -> str:
    changelog = (vault / "CHANGELOG.md").read_text(encoding="utf-8")
    entry = _release_entry(changelog, version)
    lines = [f"◆ Dex updated to v{version}"]
    if entry is not None:
        current_semver = SemVer.parse(version)
        last_semver = SemVer.parse(last_announced)
        skipped_versions = {
            match.group("version")
            for match in _HEADING_RE.finditer(changelog)
            if last_semver < SemVer.parse(match.group("version")) < current_semver
        }
        if skipped_versions:
            lines[0] += f" (…and {len(skipped_versions)} earlier updates)"
        headline, leads = entry
        if headline:
            lines.append(headline)
        lines.extend(f"• {lead}" for lead in leads)
    lines.append(f"Full story: {RELEASES_URL}")
    return "\n".join(lines)


def sweep(vault: Path) -> "str | None":
    vault = vault.resolve()
    version = _installed_version(vault)
    with _state_lock(vault):
        if not _state_path(vault).exists():
            _write_state(vault, version)
            return None

        try:
            last_announced = _load_state(vault)
        except _MalformedState:
            _write_state(vault, version)
            return None
        if SemVer.parse(version) <= SemVer.parse(last_announced):
            return None

        notice = _notice(vault, version, last_announced)
        _write_state(vault, version)
        return notice


def main(argv: "list[str] | None" = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    vault = None
    session_start = False
    index = 0
    while index < len(args):
        if args[index] == "--vault" and index + 1 < len(args):
            vault = Path(args[index + 1]).expanduser()
            index += 2
            continue
        if args[index] == "--session-start":
            session_start = True
        index += 1

    if vault is None:
        vault = Path(os.environ.get("VAULT_PATH") or os.getcwd())

    try:
        notice = sweep(vault.resolve())
        if notice:
            if session_start:
                print(
                    json.dumps(
                        {
                            "hookSpecificOutput": {
                                "hookEventName": "SessionStart",
                                "additionalContext": f"\n{notice}\n",
                            }
                        }
                    )
                )
            else:
                print(notice)
    except Exception:
        if os.environ.get("DEX_RELEASE_NOTES_DEBUG") == "1":
            raise
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
