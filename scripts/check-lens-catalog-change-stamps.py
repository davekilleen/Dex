#!/usr/bin/env python3
"""Fail a change that edits a Lens catalogue entry without restamping it.

Every registry entry carries `changed_in_release`: the core release its content
last materially changed in. Dex Lens fingerprints entries locally to tell someone
"here is what changed since you last looked", but a machine seeing the catalogue
for the first time has no local history to compare against — the stamp is the only
thing that can answer the question there.

A stamp is only worth reading if it is true, and an authored field that nothing
checks goes stale exactly the way the source pins did: silently, and first noticed
by whoever depended on it. So this gate compares the registry against the base
branch and refuses a change that edits an entry's content while leaving its stamp
where it was.

Stamp fields themselves (`since_release`, `changed_in`, `changed_in_release`) are
excluded from the comparison, so restamping an entry is never itself a content
change. Adding a new entry is not a content change either: it has no history to
be wrong about, and the producer already requires its stamp to be a shipped
release no earlier than the release it was introduced in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping

REGISTRY_PATH = "core/lens-catalog/registry.json"
CHANGELOG_PATH = "CHANGELOG.md"
PACKAGE_PATH = "package.json"
STAMP_FIELDS = frozenset({"since_release", "changed_in", "changed_in_release"})
RELEASE_HEADING = re.compile(r"^## \[([0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.]+)?)\]", re.MULTILINE)


class ChangeStampError(RuntimeError):
    """The registry cannot be trusted to say when its entries last changed."""


def version_key(version: str) -> tuple[object, ...]:
    """Order two shipped release versions, prereleases before their release."""
    core, _, prerelease = version.partition("-")
    try:
        numbers = tuple(int(part) for part in core.split("."))
    except ValueError as error:
        raise ChangeStampError(f"{version!r} is not a release version") from error
    if not prerelease:
        return (*numbers, 1, ())
    identifiers = tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part) for part in prerelease.split(".")
    )
    return (*numbers, 0, identifiers)


def material_fingerprint(entry: Mapping[str, object]) -> str:
    """Everything about an entry that reaches the catalogue, minus its stamps.

    The pinned source digest is part of this, so editing the shipped skill behind
    an entry counts as a content change the moment the pin is refreshed — and the
    producer refuses to build at all while a pin is stale.
    """
    material = {key: value for key, value in entry.items() if key not in STAMP_FIELDS}
    canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _entries(text: str, *, where: str) -> dict[str, Mapping[str, object]]:
    try:
        registry = json.loads(text)
        entries = registry["entries"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ChangeStampError(f"cannot read the Lens registry at {where}: {error}") from error
    return {entry["id"]: entry for entry in entries}


def _base_registry(base_ref: str) -> dict[str, Mapping[str, object]] | None:
    """The registry as the base branch has it, or None when there is nothing to compare."""
    if _git("rev-parse", "--verify", "--quiet", base_ref).returncode != 0:
        # Plain fetch, never --depth=1: a grafted ref has no parents, so merge-base
        # below cannot find the common ancestor. CI checks out at fetch-depth: 0.
        _git("fetch", "origin", base_ref.removeprefix("origin/"))
    merge_base = _git("merge-base", "HEAD", base_ref)
    if merge_base.returncode != 0:
        raise ChangeStampError(
            f"cannot find a common ancestor between HEAD and {base_ref}. Your local history may be "
            "shallow — run: git fetch --unshallow origin — then retry."
        )
    show = _git("show", f"{merge_base.stdout.strip()}:{REGISTRY_PATH}")
    if show.returncode != 0:
        return None
    return _entries(show.stdout, where=base_ref)


def _target_release(root: Path) -> str:
    """The newest release the changelog names — the release a change made now ships in."""
    versions = RELEASE_HEADING.findall((root / CHANGELOG_PATH).read_text(encoding="utf-8"))
    if not versions:
        raise ChangeStampError(f"{CHANGELOG_PATH} names no releases")
    return max(versions, key=version_key)


def _package_version(root: Path) -> str:
    return json.loads((root / PACKAGE_PATH).read_text(encoding="utf-8"))["version"]


def stale_stamps(
    base: Mapping[str, Mapping[str, object]],
    head: Mapping[str, Mapping[str, object]],
    *,
    package_version: str,
) -> list[str]:
    problems = []
    for entry_id, head_entry in head.items():
        base_entry = base.get(entry_id)
        if base_entry is None:
            continue
        was = base_entry.get("changed_in_release")
        now = head_entry.get("changed_in_release")
        if not isinstance(was, str):
            # The base predates the field. Nothing truthful to compare against.
            continue
        if not isinstance(now, str):
            problems.append(f"{entry_id}: changed_in_release is missing; the producer will refuse to build")
            continue
        if material_fingerprint(base_entry) == material_fingerprint(head_entry):
            continue
        if now == was:
            problems.append(
                f"{entry_id}: content changed but changed_in_release still says {was}"
            )
        elif version_key(now) < version_key(was):
            problems.append(
                f"{entry_id}: changed_in_release moved backwards, from {was} to {now}"
            )
        elif version_key(now) < version_key(package_version):
            problems.append(
                f"{entry_id}: changed_in_release {now} names a release that shipped before "
                f"the current version {package_version}"
            )
    return sorted(problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        default=f"origin/{os.environ.get('GITHUB_BASE_REF') or 'main'}",
        help="the branch this change will merge into (default: origin/main)",
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    try:
        base = _base_registry(args.base_ref)
        if base is None:
            print("No Lens registry on the base branch; nothing to compare.")
            return 0
        head = _entries((args.repo_root / REGISTRY_PATH).read_text(encoding="utf-8"), where="HEAD")
        problems = stale_stamps(base, head, package_version=_package_version(args.repo_root))
        target = _target_release(args.repo_root)
    except (ChangeStampError, OSError, UnicodeError) as error:
        print(f"Lens catalogue change-stamp gate failed: {error}", file=sys.stderr)
        return 1

    if problems:
        print(
            "❌ Lens catalogue entries changed without being restamped.\n"
            f"   Set \"changed_in_release\": \"{target}\" on each entry below (the release this change "
            "ships in), and add that version to its \"changed_in\" history if you want the full trail:\n"
            "   " + "\n   ".join(problems),
            file=sys.stderr,
        )
        return 1
    print(f"Lens catalogue change stamps are current ({len(head)} entries checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
