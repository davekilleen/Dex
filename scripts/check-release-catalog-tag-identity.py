#!/usr/bin/env python3
"""Fail closed unless a release catalog, source tag, and distribution tag agree."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class IdentityError(RuntimeError):
    """The release identity loop is absent, ambiguous, or inconsistent."""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic"
        raise IdentityError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise IdentityError(f"release catalog contains duplicate key {key!r}")
        result[key] = value
    return result


def _catalog(repo: Path, release_ref: str) -> tuple[str, str, str]:
    raw = _git(repo, "show", f"{release_ref}:System/.release-catalog.json")
    if not raw:
        raise IdentityError("release catalog observation was empty")
    try:
        document = json.loads(raw, object_pairs_hook=_unique_object)
        catalog_version = document["catalog_version"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise IdentityError(f"release catalog identity is unreadable: {error}") from error
    if catalog_version != 2:
        raise IdentityError(
            "release catalog identity gate requires catalog_version 2"
        )
    try:
        release = document["release"]
        version = release["version"]
        channel = release["channel"]
        tag_pattern = release["immutable_distribution_tag_pattern"]
        source_commit = release["source_commit"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise IdentityError(f"release catalog identity is unreadable: {error}") from error
    if not isinstance(version, str) or VERSION.fullmatch(version) is None:
        raise IdentityError("release catalog version is not canonical semver")
    if channel not in {"release", "release-beta"}:
        raise IdentityError(f"release catalog channel is unsupported: {channel!r}")
    if not isinstance(source_commit, str) or FULL_COMMIT.fullmatch(source_commit) is None:
        raise IdentityError("release catalog source_commit is not a full lowercase Git hash")
    expected_pattern = f"dist/{channel}/v{version}-<release-commit-prefix>"
    if tag_pattern != expected_pattern:
        raise IdentityError(
            f"catalog tag pattern {tag_pattern!r} does not match {expected_pattern!r}"
        )
    return version, channel, source_commit


def _local_peeled(repo: Path, tag: str) -> str:
    if _git(repo, "cat-file", "-t", tag) != "tag":
        raise IdentityError(f"{tag!r} is not an annotated tag")
    peeled = _git(repo, "rev-parse", f"{tag}^{{}}")
    if FULL_COMMIT.fullmatch(peeled) is None:
        raise IdentityError(f"{tag!r} did not peel to one full commit")
    if _git(repo, "cat-file", "-t", peeled) != "commit":
        raise IdentityError(f"{tag!r} did not peel to a commit")
    return peeled


def _remote_peeled(repo: Path, remote: str, tag: str) -> str:
    output = _git(
        repo,
        "ls-remote",
        "--tags",
        remote,
        f"refs/tags/{tag}",
        f"refs/tags/{tag}^{{}}",
    )
    if not output:
        raise IdentityError(f"remote returned no observation for required tag {tag!r}")
    refs: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 2 or FULL_COMMIT.fullmatch(fields[0]) is None:
            raise IdentityError(f"remote returned malformed tag observation: {line!r}")
        if fields[1] in refs:
            raise IdentityError(f"remote returned duplicate observation for {fields[1]!r}")
        refs[fields[1]] = fields[0]
    direct = f"refs/tags/{tag}"
    peeled = f"{direct}^{{}}"
    if direct not in refs or peeled not in refs:
        raise IdentityError(f"remote did not return annotated and peeled refs for {tag!r}")
    return refs[peeled]


def _expected_identity(
    repo: Path,
    release_ref: str,
    source_ref: str | None,
    peel,
) -> tuple[str, str, str, str]:
    version, channel, source_commit = _catalog(repo, release_ref)
    expected_release = _git(repo, "rev-parse", f"{release_ref}^{{commit}}")
    if FULL_COMMIT.fullmatch(expected_release) is None:
        raise IdentityError(f"release ref {release_ref!r} did not resolve to one full commit")
    if source_ref is None:
        source_label = f"peeled v{version}"
        actual_source = peel(f"v{version}")
    else:
        source_label = f"source ref {source_ref}"
        actual_source = _git(repo, "rev-parse", f"{source_ref}^{{commit}}")
        if FULL_COMMIT.fullmatch(actual_source) is None:
            raise IdentityError(f"source ref {source_ref!r} did not resolve to one full commit")
    if actual_source != source_commit:
        raise IdentityError(
            f"catalog source_commit {source_commit} does not equal {source_label} {actual_source}"
        )
    release_tag = f"dist/{channel}/v{version}-{expected_release[:7]}"
    return source_label, source_commit, expected_release, release_tag


def verify(
    repo: Path,
    release_ref: str,
    remote: str | None,
    source_ref: str | None = None,
) -> None:
    peel = (
        (lambda tag: _remote_peeled(repo, remote, tag))
        if remote is not None
        else (lambda tag: _local_peeled(repo, tag))
    )
    source_label, source_commit, expected_release, release_tag = _expected_identity(
        repo,
        release_ref,
        source_ref,
        peel,
    )
    actual_release = peel(release_tag)
    if actual_release != expected_release:
        raise IdentityError(
            f"release tag {release_tag} peels to {actual_release}, not release commit {expected_release}"
        )
    location = f"remote {remote}" if remote is not None else "local repository"
    print(
        f"Release catalog identity verified in {location}: "
        f"{source_label} -> {source_commit}; {release_tag} -> {expected_release}"
    )


def release_tag(repo: Path, release_ref: str, source_ref: str | None) -> str:
    _source_label, _source_commit, _release_commit, tag = _expected_identity(
        repo,
        release_ref,
        source_ref,
        lambda value: _local_peeled(repo, value),
    )
    return tag


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--release-ref", default="release")
    parser.add_argument("--remote")
    parser.add_argument(
        "--source-ref",
        help="verify catalog source_commit against this local source ref instead of vN",
    )
    parser.add_argument(
        "--print-release-tag",
        action="store_true",
        help="validate catalog/source fields and print the release-commit tag before minting",
    )
    args = parser.parse_args()
    try:
        repo = args.repo.resolve()
        if args.remote is not None and args.source_ref is not None:
            raise IdentityError("--source-ref cannot be combined with --remote")
        if args.print_release_tag:
            if args.remote is not None:
                raise IdentityError("--print-release-tag cannot be combined with --remote")
            print(release_tag(repo, args.release_ref, args.source_ref))
        else:
            verify(repo, args.release_ref, args.remote, args.source_ref)
    except IdentityError as error:
        parser.exit(1, f"release catalog identity gate failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
