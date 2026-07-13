#!/usr/bin/env python3
"""Render a plain-English pull-request impact report."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple


class Area(NamedTuple):
    name: str
    journey: str
    matches: Callable[[str], bool]


def _under(prefix: str) -> Callable[[str], bool]:
    return lambda path: path == prefix or path.startswith(f"{prefix}/")


TRUST_FILES = {
    "core/utils/smoke.py",
    "core/utils/doctor.py",
    "core/utils/trust_registry.py",
}

AREA_RULES = (
    Area(
        "the task/meeting engine",
        "creating and updating tasks, processing meetings, and keeping that work connected",
        _under("core/mcp"),
    ),
    Area(
        "skills",
        "the guided workflows and commands people use with Dex",
        _under(".claude/skills"),
    ),
    Area(
        "session hooks",
        "starting sessions and carrying useful context into the next interaction",
        _under(".claude/hooks"),
    ),
    Area(
        "build & release",
        "turning a reviewed contribution into a safe Dex update",
        _under("scripts"),
    ),
    Area(
        "the trust engine",
        "safe diagnostics and health checks for installed and customized Dex setups",
        lambda path: path in TRUST_FILES,
    ),
    Area(
        "tests",
        "catching regressions before contributors and users encounter them",
        _under("core/tests"),
    ),
)


def areas_for_paths(paths: Iterable[str]) -> list[Area]:
    changed = tuple(dict.fromkeys(path.strip() for path in paths if path.strip()))
    return [area for area in AREA_RULES if any(area.matches(path) for path in changed)]


def render_report(paths: Iterable[str]) -> str:
    changed = tuple(dict.fromkeys(path.strip() for path in paths if path.strip()))
    areas = areas_for_paths(changed)
    lines = ["<!-- dex-pr-report -->", "## What this pull request touches", ""]
    if areas:
        lines.extend(f"- **{area.name}** — feeds {area.journey}." for area in areas)
    else:
        lines.append("- **other parts of Dex** — No mapped product journey was detected for these paths.")

    lines.extend(
        [
            "",
            "### Gates that will judge this change",
            "",
            "- **Personal-data gate:** added lines must not expose real identities or personal vault content.",
            "- **Change-aware gates:** source changes are checked for tests, path-contract use, documentation drift, and touched-file coverage.",
            "- **Tests and coverage:** the Python, MCP, migration, hook, and script suites must remain healthy.",
            "- **Safety and quality:** security, lint, distribution, path consistency, and large-vault checks still apply.",
            "",
            f"_Based on {len(changed)} changed file{'s' if len(changed) != 1 else ''}._",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files-from", type=Path, help="newline-delimited changed-file list; defaults to stdin")
    args = parser.parse_args(argv)
    if args.files_from:
        paths = args.files_from.read_text(encoding="utf-8").splitlines()
    else:
        paths = sys.stdin.read().splitlines()
    sys.stdout.write(render_report(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
