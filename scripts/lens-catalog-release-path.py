#!/usr/bin/env python3
"""Decide whether a PR must dry-run the Dex Lens catalogue release path."""

from __future__ import annotations

import argparse
import posixpath
import sys
from pathlib import Path

EXACT_DEPENDENCIES = frozenset(
    {
        ".github/workflows/ci.yml",
        "CHANGELOG.md",
        "core/capabilities.py",
        "core/lens_catalog_sources.py",
        "core/portable_contract.py",
        "package.json",
        "packages/dex-contracts/dist/portable-vault.contract.json",
        "scripts/check-lens-catalog-change-stamps.py",
        "scripts/check-lens-catalog-release-asset.py",
        "scripts/generate-dex-lens-catalog.py",
        "scripts/lens-catalog-release-path.py",
    }
)
DEPENDENCY_PREFIXES = (
    ".claude/skills/",
    "core/lens-catalog/",
    "core/lifecycle/catalog/",
)


def _canonical_changed_path(value: str) -> str:
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or posixpath.normpath(value) != value
        or value.startswith("../")
    ):
        raise ValueError(f"changed path is not canonical: {value!r}")
    return value


def should_run(event_name: str, changed_paths: tuple[str, ...]) -> bool:
    if event_name == "workflow_dispatch":
        return True
    if event_name != "pull_request":
        raise ValueError(f"unsupported event: {event_name}")
    return any(
        path in EXACT_DEPENDENCIES or any(path.startswith(prefix) for prefix in DEPENDENCY_PREFIXES)
        for path in changed_paths
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--changed-files", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        changed_paths = tuple(
            _canonical_changed_path(line)
            for line in args.changed_files.read_text(encoding="utf-8").splitlines()
            if line
        )
        decision = should_run(args.event_name, changed_paths)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"Lens catalogue release-path decision failed: {error}", file=sys.stderr)
        return 1
    print(f"should_run={'true' if decision else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
