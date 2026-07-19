#!/usr/bin/env python3
"""Reject removed Tau Mirror code, references, dependencies, and release members."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tarfile
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath

TAU_NAME = "tau" + "-mirror"
TEXT_RULES = (
    (
        "Tau Mirror npx loader",
        re.compile(
            r"\bnpx\b.{0,120}(?:\btau[-_ ]+mirror\b|\b(?:tau|Tau)Mirror\b)",
            re.IGNORECASE | re.DOTALL,
        ),
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


def _normalize_member_path(raw_path: str, *, allow_root: bool = False) -> str:
    if not raw_path or "\\" in raw_path or "\0" in raw_path:
        raise ValueError("empty, backslash, or NUL path")
    if raw_path.startswith("/") or PurePosixPath(raw_path).is_absolute():
        raise ValueError("absolute path")

    trimmed = raw_path
    while trimmed.startswith("./"):
        trimmed = trimmed[2:]
    if trimmed in {"", "."}:
        if allow_root:
            return "."
        raise ValueError("root or empty path")

    raw_parts = trimmed.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError("empty, dot, or traversal component")
    if any(any(ord(character) < 32 or ord(character) == 127 for character in part) for part in raw_parts):
        raise ValueError("control character")

    normalized = PurePosixPath(*raw_parts).as_posix()
    if normalized.startswith("../") or normalized == "..":
        raise ValueError("path escapes root")
    return normalized


def _tracked_files(repo_root: Path) -> tuple[list[tuple[str, bytes]], list[str]]:
    paths = _git(repo_root, "ls-files", "-z").decode("utf-8").split("\0")
    return _filesystem_files(repo_root, (path for path in paths if path))


def _filesystem_files(
    tree_root: Path,
    relative_paths: Iterable[str] | None = None,
    *,
    reject_symlinks: bool = True,
    enforce_canonical: bool = True,
) -> tuple[list[tuple[str, bytes]], list[str]]:
    lexical_root = tree_root.absolute()
    canonical_root = lexical_root.resolve(strict=True)
    files: list[tuple[str, bytes]] = []
    violations: list[str] = []

    if relative_paths is None:
        discovered: list[str] = []
        for current_root, directories, filenames in os.walk(lexical_root, followlinks=False):
            current = Path(current_root)
            for name in [*directories, *filenames]:
                discovered.append((current / name).relative_to(lexical_root).as_posix())
        relative_paths = discovered

    seen: set[str] = set()
    for raw_path in relative_paths:
        try:
            normalized = _normalize_member_path(raw_path)
        except ValueError as error:
            violations.append(f"{raw_path}: unsafe tree path ({error})")
            continue
        if normalized in seen:
            violations.append(f"{raw_path}: duplicate normalized tree path {normalized}")
            continue
        seen.add(normalized)

        lexical_candidate = lexical_root.joinpath(*PurePosixPath(normalized).parts)
        try:
            lexical_candidate.relative_to(lexical_root)
        except ValueError:
            violations.append(f"{raw_path}: tree path escapes lexical root")
            continue

        try:
            metadata = lexical_candidate.lstat()
        except FileNotFoundError:
            violations.append(f"{raw_path}: tracked tree member is missing")
            continue
        if stat.S_ISLNK(metadata.st_mode):
            target = os.readlink(lexical_candidate)
            try:
                canonical_target = lexical_candidate.resolve(strict=True)
                canonical_target.relative_to(canonical_root)
                containment = "inside tree"
            except (FileNotFoundError, RuntimeError, ValueError):
                containment = "escaping or unresolved"
            if enforce_canonical and containment != "inside tree":
                violations.append(
                    f"{raw_path}: distribution symlink is forbidden ({containment}: {target})"
                )
                continue
            if reject_symlinks:
                violations.append(
                    f"{raw_path}: distribution symlink is forbidden ({containment}: {target})"
                )
                continue
            metadata = lexical_candidate.stat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            violations.append(f"{raw_path}: unsafe tree special-file type")
            continue

        canonical_candidate = lexical_candidate.resolve(strict=True)
        if enforce_canonical:
            try:
                canonical_candidate.relative_to(canonical_root)
            except ValueError:
                violations.append(f"{raw_path}: canonical tree path escapes root")
                continue
        files.append((normalized, lexical_candidate.read_bytes()))
    return files, violations


def _filesystem_tree(tree_root: Path) -> tuple[list[tuple[str, bytes]], list[str]]:
    return _filesystem_files(tree_root)


def _git_tree(repo_root: Path, treeish: str) -> tuple[list[tuple[str, bytes]], list[str]]:
    entries = _git(repo_root, "ls-tree", "-r", "-z", treeish).decode("utf-8").split("\0")
    files: list[tuple[str, bytes]] = []
    violations: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        if not entry:
            continue
        metadata, raw_path = entry.split("\t", 1)
        mode, object_type, object_id = metadata.split(" ", 2)
        try:
            normalized = _normalize_member_path(raw_path)
        except ValueError as error:
            violations.append(f"{raw_path}: unsafe Git-tree path ({error})")
            continue
        if normalized in seen:
            violations.append(f"{raw_path}: duplicate normalized Git-tree path {normalized}")
            continue
        seen.add(normalized)
        if mode == "120000":
            violations.append(f"{raw_path}: distribution symlink is forbidden")
            continue
        if object_type != "blob" or mode not in {"100644", "100755"}:
            violations.append(f"{raw_path}: unsafe Git-tree member type {mode} {object_type}")
            continue
        files.append((normalized, _git(repo_root, "cat-file", "blob", object_id)))
    return files, violations


def _archive_tree(
    archive_path: Path,
    *,
    normalize_path: Callable[..., str] = _normalize_member_path,
    reject_duplicates: bool = True,
    reject_links: bool = True,
    reject_special: bool = True,
) -> tuple[list[tuple[str, bytes]], list[str]]:
    files: list[tuple[str, bytes]] = []
    violations: list[str] = []
    seen: set[str] = set()
    with tarfile.open(archive_path, mode="r:*") as archive:
        for member in archive.getmembers():
            try:
                normalized = normalize_path(member.name, allow_root=member.isdir())
            except ValueError as error:
                violations.append(f"{member.name}: unsafe archive path ({error})")
                continue
            if normalized == ".":
                continue
            if reject_duplicates and normalized in seen:
                violations.append(f"{member.name}: duplicate normalized archive path {normalized}")
                continue
            seen.add(normalized)

            if member.issym() or member.islnk():
                try:
                    normalize_path(member.linkname)
                except ValueError as error:
                    violations.append(
                        f"{member.name}: unsafe archive link target {member.linkname} ({error})"
                    )
                if reject_links:
                    violations.append(f"{member.name}: distribution archive link is forbidden")
                continue
            if member.isfile():
                extracted = archive.extractfile(member)
                if extracted is not None:
                    files.append((normalized, extracted.read()))
            elif not member.isdir() and reject_special:
                violations.append(f"{member.name}: unsafe archive special-file type")
    return files, violations


def _is_source_content_excluded(path: str) -> bool:
    return path in SOURCE_CONTENT_EXCLUSIONS or path.startswith(SOURCE_PREFIX_EXCLUSIONS)


def _contains_tau_identity(value: str) -> bool:
    """Match the removed identity across path/identifier formats without substrings."""
    camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    tokens = [token.lower() for token in re.findall(r"[A-Za-z0-9]+", camel_split)]
    return any(left == "tau" and right == "mirror" for left, right in zip(tokens, tokens[1:]))


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


def _check_files(
    files: Iterable[tuple[str, bytes]],
    *,
    source: bool,
    identity_checker: Callable[[str], bool] | None = _contains_tau_identity,
    text_rules: tuple[tuple[str, re.Pattern[str]], ...] = TEXT_RULES,
    forbidden_dependencies: set[str] = FORBIDDEN_DEPENDENCIES,
) -> list[str]:
    violations: list[str] = []
    for raw_path, content in files:
        path = PurePosixPath(raw_path.removeprefix("./")).as_posix()
        lower_path = path.lower()
        if identity_checker is not None and identity_checker(path):
            violations.append(f"{path}: removed Tau path")

        dependencies = _dependency_names(path, content)
        for dependency in sorted(dependencies & forbidden_dependencies):
            violations.append(f"{path}: forbidden dependency {dependency}")

        if (source and _is_source_content_excluded(path)) or lower_path.startswith("node_modules/"):
            continue
        if b"\0" in content:
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if identity_checker is not None and identity_checker(text):
            violations.append(f"{path}: Tau Mirror reference")
        for description, pattern in text_rules:
            if pattern.search(text):
                violations.append(f"{path}: {description}")
    return sorted(set(violations))


def _check_distignore_content(content: bytes | None) -> list[str]:
    if content is None:
        return [".distignore: missing release quarantine"]
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return [".distignore: not UTF-8"]
    entries = {
        line.split("#", 1)[0].strip()
        for line in text.splitlines()
        if line.split("#", 1)[0].strip()
    }
    if DISTIGNORE_ENTRY not in entries:
        return [f".distignore: missing exact quarantine entry {DISTIGNORE_ENTRY}"]
    return []


def _check_distignore(repo_root: Path) -> list[str]:
    path = repo_root / ".distignore"
    return _check_distignore_content(path.read_bytes() if path.is_file() else None)


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--source-root", type=Path)
    group.add_argument("--tree", type=Path)
    group.add_argument("--git-source")
    group.add_argument("--git-tree")
    group.add_argument("--archive", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    source = args.source_root is not None or not any(
        (args.tree, args.git_source, args.git_tree, args.archive)
    )
    if source:
        repo_root = (args.source_root or repo_root).resolve()
        files, violations = _tracked_files(repo_root)
        violations.extend(_check_distignore(repo_root))
    elif args.tree:
        files, violations = _filesystem_tree(args.tree)
    elif args.git_source:
        files, violations = _git_tree(repo_root, args.git_source)
        distignore = next((content for path, content in files if path == ".distignore"), None)
        violations.extend(_check_distignore_content(distignore))
        source = True
    elif args.git_tree:
        files, violations = _git_tree(repo_root, args.git_tree)
    else:
        files, violations = _archive_tree(args.archive.resolve())

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
