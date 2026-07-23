#!/usr/bin/env python3
"""Generate Dex's deterministic installed-files manifest from a Git tree."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

DEFAULT_MANIFEST = Path("System/.installed-files.manifest")
REQUIRED_LIFECYCLE_RELEASE_PATHS = (
    "core/lifecycle/bridge.py",
    "core/lifecycle/catalog/bridge-release.json",
    "core/lifecycle/contracts/api.schema.json",
    "core/lifecycle/service.py",
    "core/portable_contract.py",
    "packages/dex-contracts/dist/portable-vault.contract.json",
)


class ManifestError(RuntimeError):
    """Raised when an installed-files manifest cannot be generated."""


def _run_git(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ManifestError(detail or f"git {' '.join(args)} failed")
    return result.stdout


def installed_paths(repo_root: Path, treeish: str = "HEAD") -> tuple[str, ...]:
    """Return sorted tracked paths from *treeish* without reading the worktree."""
    repo_root = repo_root.resolve()
    tree = _run_git(repo_root, "rev-parse", "--verify", f"{treeish}^{{tree}}").strip()
    raw_paths = _run_git(repo_root, "ls-tree", "-r", "-z", "--name-only", tree.decode("ascii"))

    paths = []
    for raw_path in raw_paths.split(b"\0"):
        if not raw_path:
            continue
        path = raw_path.decode("utf-8")
        if "\n" in path or "\r" in path:
            raise ManifestError(f"path cannot be represented in a newline manifest: {path!r}")
        paths.append(path)
    return tuple(sorted(paths))


def generate_manifest(repo_root: Path, treeish: str = "HEAD") -> str:
    """Render the manifest for *treeish* as a deterministic newline path list."""
    paths = installed_paths(repo_root, treeish)
    return "".join(f"{path}\n" for path in paths)


def require_lifecycle_release_paths(paths: tuple[str, ...]) -> None:
    """Fail closed when a release omits any frozen lifecycle contract artifact."""
    missing = sorted(set(REQUIRED_LIFECYCLE_RELEASE_PATHS) - set(paths))
    if missing:
        raise ManifestError(
            "release manifest omits frozen lifecycle contract paths: "
            + ", ".join(missing)
        )


def read_manifest(path: Path) -> tuple[str, ...]:
    """Read one canonical sorted/unique newline manifest."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ManifestError("manifest is not UTF-8") from error
    if not text.endswith("\n") or "\r" in text or "\x00" in text:
        raise ManifestError("manifest is not canonical newline text")
    paths = tuple(text.splitlines())
    if paths != tuple(sorted(set(paths))):
        raise ManifestError("manifest paths are not sorted and unique")
    return paths


def write_manifest(
    repo_root: Path,
    treeish: str = "HEAD",
    output: Path | None = None,
) -> Path:
    """Write a manifest for *treeish* and return its destination."""
    repo_root = repo_root.resolve()
    destination = output or repo_root / DEFAULT_MANIFEST
    if not destination.is_absolute():
        destination = repo_root / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(generate_manifest(repo_root, treeish), encoding="utf-8")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("treeish", nargs="?", default="HEAD", help="Git tree-ish to list (default: HEAD).")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Git repository root.")
    parser.add_argument("--output", type=Path, help=f"Output path (default: {DEFAULT_MANIFEST}).")
    parser.add_argument("--validate-file", type=Path, help="Validate an existing manifest instead of generating one.")
    parser.add_argument(
        "--require-lifecycle-contracts",
        action="store_true",
        help="Fail unless every frozen lifecycle contract artifact is present.",
    )
    args = parser.parse_args(argv)

    try:
        if args.validate_file is not None:
            if args.output is not None or args.treeish != "HEAD":
                raise ManifestError("--validate-file cannot be combined with treeish or --output")
            paths = read_manifest(args.validate_file)
            if args.require_lifecycle_contracts:
                require_lifecycle_release_paths(paths)
            print(f"Validated {args.validate_file} ({len(paths)} paths)")
            return 0
        destination = write_manifest(args.repo_root, args.treeish, args.output)
        paths = installed_paths(args.repo_root, args.treeish)
        if args.require_lifecycle_contracts:
            require_lifecycle_release_paths(paths)
        count = len(paths)
    except (ManifestError, OSError, UnicodeError) as error:
        parser.exit(1, f"manifest generation failed: {error}\n")

    print(f"Wrote {destination} ({count} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
