#!/usr/bin/env python3
"""Reject removed Tau Mirror code, references, dependencies, and release members."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tarfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

TAU_NAME = "tau" + "-mirror"
TAU_PATH_PATTERN = re.compile(r"(?:^|/)(?:tau[-_ ]mirror)(?:/|$)", re.IGNORECASE)
TEXT_RULES = (
    ("Tau Mirror reference", re.compile(r"tau[-_ ]mirror", re.IGNORECASE)),
    (
        "Tau Mirror npx loader",
        re.compile(r"\bnpx\b.{0,120}\btau[-_ ]mirror\b", re.IGNORECASE | re.DOTALL),
    ),
    ("removed QR dependency", re.compile(r"qrcode" + r"-terminal", re.IGNORECASE)),
    (
        "removed Pi coding-agent dependency",
        re.compile(r"@mariozechner/" + r"pi-coding-agent", re.IGNORECASE),
    ),
    (
        "wildcard network bind",
        re.compile(r"(?:listen|bind)\s*\([^)]*[\"']0\.0\.0\.0[\"']", re.IGNORECASE),
    ),
    ("wildcard host argument", re.compile(r"--host(?:=|\s+)[\"']?0\.0\.0\.0", re.IGNORECASE)),
    ("LAN address discovery", re.compile(r"\bnetworkInterfaces\s*\(", re.IGNORECASE)),
    (
        "unsupported no-authentication claim",
        re.compile(r"\b(?:no authentication|required authentication:\s*none|authentication disabled)\b", re.IGNORECASE),
    ),
)
FORBIDDEN_DEPENDENCIES = {
    TAU_NAME,
    "qrcode" + "-terminal",
    "@mariozechner/" + "pi-coding-agent",
}
SOURCE_CONTENT_EXCLUSIONS = {
    ".distignore",
    ".gitattributes",
    "scripts/check-tau-removal.py",
}
SOURCE_PREFIX_EXCLUSIONS = ("core/tests/",)
DISTIGNORE_ENTRY = "extensions/" + TAU_NAME + "/"


def _git(repo_root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=repo_root, check=True, capture_output=True
    ).stdout


def _tracked_files(repo_root: Path) -> list[tuple[str, bytes]]:
    paths = _git(repo_root, "ls-files", "-z").decode("utf-8").split("\0")
    return [
        (path, (repo_root / path).read_bytes())
        for path in paths
        if path and (repo_root / path).is_file()
    ]


def _filesystem_tree(tree_root: Path) -> list[tuple[str, bytes]]:
    return [
        (path.relative_to(tree_root).as_posix(), path.read_bytes())
        for path in tree_root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(tree_root).parts
    ]


def _git_tree(repo_root: Path, treeish: str) -> list[tuple[str, bytes]]:
    paths = _git(repo_root, "ls-tree", "-r", "-z", "--name-only", treeish).decode("utf-8").split("\0")
    return [(path, _git(repo_root, "show", f"{treeish}:{path}")) for path in paths if path]


def _archive_tree(archive_path: Path) -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    with tarfile.open(archive_path, mode="r:*") as archive:
        for member in archive.getmembers():
            normalized = PurePosixPath(member.name.removeprefix("./")).as_posix()
            if member.isfile():
                extracted = archive.extractfile(member)
                if extracted is not None:
                    files.append((normalized, extracted.read()))
            elif member.issym() or member.islnk():
                files.append((normalized, member.linkname.encode("utf-8")))
    return files


def _is_source_content_excluded(path: str) -> bool:
    return path in SOURCE_CONTENT_EXCLUSIONS or path.startswith(SOURCE_PREFIX_EXCLUSIONS)


def _dependency_names(path: str, content: bytes) -> set[str]:
    if path not in {"package.json", "package-lock.json"}:
        return set()
    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return set()

    names: set[str] = set()
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        values = document.get(section, {})
        if isinstance(values, dict):
            names.update(str(name).lower() for name in values)
    packages = document.get("packages", {})
    if isinstance(packages, dict):
        for package_path in packages:
            marker = "node_modules/"
            if marker in package_path:
                names.add(package_path.rsplit(marker, 1)[1].lower())
    return names


def _check_files(files: Iterable[tuple[str, bytes]], *, source: bool) -> list[str]:
    violations: list[str] = []
    for raw_path, content in files:
        path = PurePosixPath(raw_path.removeprefix("./")).as_posix()
        lower_path = path.lower()
        if TAU_PATH_PATTERN.search(lower_path):
            violations.append(f"{path}: removed Tau path")

        dependencies = _dependency_names(path, content)
        for dependency in sorted(dependencies & FORBIDDEN_DEPENDENCIES):
            violations.append(f"{path}: forbidden dependency {dependency}")

        if (source and _is_source_content_excluded(path)) or lower_path.startswith("node_modules/"):
            continue
        if b"\0" in content:
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for description, pattern in TEXT_RULES:
            if pattern.search(text):
                violations.append(f"{path}: {description}")
    return sorted(set(violations))


def _check_distignore(repo_root: Path) -> list[str]:
    path = repo_root / ".distignore"
    if not path.is_file():
        return [".distignore: missing release quarantine"]
    entries = {
        line.split("#", 1)[0].strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.split("#", 1)[0].strip()
    }
    if DISTIGNORE_ENTRY not in entries:
        return [f".distignore: missing exact quarantine entry {DISTIGNORE_ENTRY}"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--source-root", type=Path)
    group.add_argument("--tree", type=Path)
    group.add_argument("--git-tree")
    group.add_argument("--archive", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    source = args.source_root is not None or not any(
        (args.tree, args.git_tree, args.archive)
    )
    if source:
        repo_root = (args.source_root or repo_root).resolve()
        files = _tracked_files(repo_root)
        violations = _check_distignore(repo_root)
    elif args.tree:
        files = _filesystem_tree(args.tree.resolve())
        violations = []
    elif args.git_tree:
        files = _git_tree(repo_root, args.git_tree)
        violations = []
    else:
        files = _archive_tree(args.archive.resolve())
        violations = []

    violations.extend(_check_files(files, source=source))
    if violations:
        print("Tau removal check failed:")
        for violation in sorted(set(violations)):
            print(f"  - {violation}")
        return 1
    print("Tau removal check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
