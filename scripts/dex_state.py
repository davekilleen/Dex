#!/usr/bin/env python3
"""Report Dex Core's released, local, and planned state without network access."""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = REPO_ROOT / "docs/architecture/STATE.md"
GENERATED_START = "<!-- GENERATED:START -->"
GENERATED_END = "<!-- GENERATED:END -->"
PLANNED_START = "<!-- PLANNED:START -->"
PLANNED_END = "<!-- PLANNED:END -->"
GIT_TIMEOUT_SECONDS = 3
PR_SUFFIX = re.compile(r"\s*\(#(\d+)\)$")


@dataclass(frozen=True)
class Release:
    tag: str
    commit_date: str


@dataclass(frozen=True)
class UnreleasedCommit:
    subject: str
    pr_number: int | None


@dataclass(frozen=True)
class CoreState:
    released: Release | None
    unreleased: tuple[UnreleasedCommit, ...] | None
    planned: str


def _git(repo_root: Path, *args: str) -> str | None:
    """Run one bounded git query, returning None for every unavailable state."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def find_latest_release(repo_root: Path = REPO_ROOT) -> Release | None:
    """Return the newest version-sorted v* tag and its commit date."""
    tags = _git(repo_root, "tag", "--sort=-v:refname", "--list", "v[0-9]*")
    if not tags:
        return None
    tag = tags.splitlines()[0]
    commit_timestamp = _git(repo_root, "log", "-1", "--format=%ci", tag)
    commit_date = commit_timestamp.split(maxsplit=1)[0] if commit_timestamp else "unknown"
    return Release(tag=tag, commit_date=commit_date)


def parse_unreleased_subject(subject: str) -> UnreleasedCommit:
    """Parse a squash-merge PR number while preserving the exact subject."""
    match = PR_SUFFIX.search(subject)
    return UnreleasedCommit(subject=subject, pr_number=int(match.group(1)) if match else None)


def find_unreleased(repo_root: Path, release_tag: str) -> tuple[UnreleasedCommit, ...] | None:
    """Return newest-first commit subjects after the release tag."""
    subjects = _git(repo_root, "log", "--format=%s", f"{release_tag}..HEAD")
    if subjects is None:
        return None
    return tuple(parse_unreleased_subject(subject) for subject in subjects.splitlines() if subject)


def read_planned(state_path: Path = STATE_PATH) -> str:
    """Read the hand-maintained PLANNED contents verbatim, or return empty."""
    try:
        document = state_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    before, start, rest = document.partition(PLANNED_START)
    del before
    if not start:
        return ""
    planned, end, _after = rest.partition(PLANNED_END)
    return planned if end else ""


def collect_state(repo_root: Path = REPO_ROOT, state_path: Path = STATE_PATH) -> CoreState:
    """Collect live git state and hand-maintained planned work."""
    planned = read_planned(state_path)
    released = find_latest_release(repo_root)
    if released is None:
        return CoreState(released=None, unreleased=None, planned=planned)
    attached_branch = _git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    unreleased = find_unreleased(repo_root, released.tag) if attached_branch else None
    return CoreState(released=released, unreleased=unreleased, planned=planned)


def _released_line(released: Release | None) -> str:
    if released is None:
        return "Released: unknown (no version tag found)"
    return f"Released: {released.tag} ({released.commit_date})"


def _display_commit(commit: UnreleasedCommit) -> str:
    subject_without_pr = PR_SUFFIX.sub("", commit.subject)
    if commit.pr_number is None:
        return subject_without_pr
    return f"#{commit.pr_number} {subject_without_pr}"


def render_digest(state: CoreState) -> str:
    """Render the compact SessionStart grounding digest."""
    lines = ["=== Dex Core — grounding ===", _released_line(state.released)]
    if state.unreleased is not None:
        summary = " · ".join(_display_commit(commit) for commit in state.unreleased) or "none"
        lines.append(f"On main, not yet released ({len(state.unreleased)}): {summary}")
    lines.append(
        "Before Core work read: docs/architecture/DEX-CORE-MAP.md (map) + "
        "INVENTORY.md (generated)"
    )
    return "\n".join(lines)


def render_human(state: CoreState) -> str:
    """Render the fuller on-demand /dex-orient report."""
    lines = ["=== Dex Core — orientation ===", _released_line(state.released)]
    if state.unreleased is not None:
        lines.append(f"On main, not yet released ({len(state.unreleased)}):")
        if state.unreleased:
            lines.extend(f"- {_display_commit(commit)}" for commit in state.unreleased)
        else:
            lines.append("- none")
    lines.append("Planned:")
    lines.append(state.planned.strip("\n") or "- none recorded")
    lines.append(
        "Before Core work read: docs/architecture/DEX-CORE-MAP.md (narrative) + "
        "docs/architecture/INVENTORY.md (generated)"
    )
    return "\n".join(lines)


def render_generated(state: CoreState) -> str:
    """Render only STATE.md's deterministic generated snapshot."""
    lines = [
        "## Generated snapshot",
        "",
        "SHIPPED/LOCAL are computed live — run `/dex-orient` or "
        "`python3 scripts/dex_state.py` for current truth.",
        "",
        _released_line(state.released),
        "",
    ]
    if state.released is None:
        lines.append("LOCAL delta unavailable without a version tag.")
    elif state.unreleased is None:
        lines.append("LOCAL delta unavailable in the current git state.")
    else:
        lines.append(f"### LOCAL — on main, not yet released ({len(state.unreleased)})")
        lines.append("")
        if state.unreleased:
            lines.extend(f"- {_display_commit(commit)}" for commit in state.unreleased)
        else:
            lines.append("- none")
    return "\n".join(lines)


def _new_state_document() -> str:
    return (
        "# Dex Core State\n\n"
        "A compact snapshot of released, local, and planned Dex Core work.\n\n"
        f"{GENERATED_START}\n{GENERATED_END}\n\n"
        f"{PLANNED_START}\n{PLANNED_END}\n"
    )


def write_generated_state(state: CoreState, state_path: Path = STATE_PATH) -> None:
    """Replace only the GENERATED block, leaving every other byte untouched."""
    try:
        document = state_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        document = _new_state_document()
    before, start, rest = document.partition(GENERATED_START)
    _old_generated, end, after = rest.partition(GENERATED_END)
    if not start or not end:
        return
    replacement = f"{before}{GENERATED_START}\n{render_generated(state)}\n{GENERATED_END}{after}"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(replacement, encoding="utf-8")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--digest", action="store_true", help="print a compact SessionStart digest")
    mode.add_argument("--write", action="store_true", help="refresh STATE.md's generated block")
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    repo_root: Path = REPO_ROOT,
    state_path: Path = STATE_PATH,
) -> int:
    """Run a mode without allowing local environment failures to break a session."""
    args = _parse_args(argv)
    try:
        state = collect_state(repo_root, state_path)
        if args.write:
            write_generated_state(state, state_path)
        else:
            print(render_digest(state) if args.digest else render_human(state))
    except (OSError, ValueError):
        print("Released: unknown (grounding state unavailable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
