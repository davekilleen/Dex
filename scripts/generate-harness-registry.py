#!/usr/bin/env python3
"""Generate one inspectable descriptor JSON per harness profile.

``core/harnesses/registry.json`` is intentionally a single file so CommonJS
consumers can validate it without importing Python.  The files in
``core/harnesses/profiles/`` are deterministic, human-reviewable projections
for clients that want one descriptor at a time.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "core" / "harnesses" / "registry.json"
PROFILES = ROOT / "core" / "harnesses" / "profiles"


def expected_profiles(repo_root: Path = ROOT) -> dict[Path, str]:
    registry = repo_root / "core" / "harnesses" / "registry.json"
    payload = json.loads(registry.read_text(encoding="utf-8"))
    entries = payload.get("profiles")
    if not isinstance(entries, list):
        raise ValueError("harness registry profiles must be an array")
    expected: dict[Path, str] = {}
    for profile in entries:
        if not isinstance(profile, dict) or not isinstance(profile.get("id"), str):
            raise ValueError("every harness profile needs an id")
        relative = Path("core") / "harnesses" / "profiles" / f"{profile['id']}.json"
        expected[relative] = json.dumps(profile, indent=2, sort_keys=True) + "\n"
    return expected


def write_profiles(repo_root: Path = ROOT) -> int:
    expected = expected_profiles(repo_root)
    profile_root = repo_root / "core" / "harnesses" / "profiles"
    profile_root.mkdir(parents=True, exist_ok=True)
    for relative, text in expected.items():
        target = repo_root / relative
        target.write_text(text, encoding="utf-8")
    for stale in profile_root.glob("*.json"):
        if stale.relative_to(repo_root) not in expected:
            stale.unlink()
    print(f"Generated {len(expected)} harness descriptors under {profile_root}.")
    return 0


def check_profiles(repo_root: Path = ROOT) -> int:
    expected = expected_profiles(repo_root)
    errors: list[str] = []
    for relative, text in expected.items():
        target = repo_root / relative
        if not target.is_file():
            errors.append(f"missing {relative.as_posix()}")
        elif target.read_text(encoding="utf-8") != text:
            errors.append(f"drifted {relative.as_posix()}")
    profile_root = repo_root / "core" / "harnesses" / "profiles"
    for extra in profile_root.glob("*.json") if profile_root.is_dir() else ():
        if extra.relative_to(repo_root) not in expected:
            errors.append(f"unexpected {extra.relative_to(repo_root).as_posix()}")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Harness descriptors are current ({len(expected)} files).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check generated descriptors")
    args = parser.parse_args()
    return check_profiles() if args.check else write_profiles()


if __name__ == "__main__":
    raise SystemExit(main())
