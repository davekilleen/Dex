#!/usr/bin/env python3
"""Apply one immutable Dex release without merging Git histories.

The release identity is supplied by the existing bounded release-evidence
flow. This module re-verifies that exact annotated ``dist/release/v*`` tag
against the selected stable/beta channel in the split brain Git store, builds
an ownership-authorized file plan, then delegates every release-tree mutation
to :class:`core.transaction.engine.Transaction`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core import portable_contract
from core.transaction.engine import PlanEntry, Transaction
from core.utils import release_channel
from core.utils.local_git import git_output

MANIFEST_RELATIVE = "System/.installed-files.manifest"
TOPOLOGY_RELATIVE = Path("System/.dex/topology.json")
BRAIN_RELATIVE = Path(".dex/brain.git")
VAULT_MARKER_RELATIVE = Path(".git/dex-vault-v2")
BRAIN_MARKER_NAME = "dex-brain-v2"
OFFICIAL_REMOTE = re.compile(
    r"^(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)"
    r"davekilleen/Dex(?:\.git)?/?$",
    re.IGNORECASE,
)
RELEASE_TAG = re.compile(
    r"^dist/release/v(?P<version>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*))-(?P<short>[0-9a-f]{7,64})$"
)
START_MARKER = re.compile(
    rb"^## USER_EXTENSIONS_START[^\r\n]*(?:\r?\n|$)",
    re.MULTILINE,
)
END_MARKER = re.compile(
    rb"^## USER_EXTENSIONS_END[^\r\n]*(?:\r?\n|$)",
    re.MULTILINE,
)


class UpdateError(RuntimeError):
    """The update could not safely proceed."""


class ReleaseVerificationError(UpdateError):
    """The supplied immutable release identity failed closed verification."""


class CompositionError(UpdateError):
    """A release-owned composed file could not be built without data loss."""


def _extension_block(template: bytes) -> tuple[bytes, bytes]:
    try:
        template.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CompositionError("release CLAUDE.md template is not UTF-8") from error
    starts = tuple(START_MARKER.finditer(template))
    ends = tuple(END_MARKER.finditer(template))
    if len(starts) != 1 or len(ends) != 1 or ends[0].start() < starts[0].end():
        raise CompositionError(
            "release template needs exactly one ordered USER_EXTENSIONS marker pair"
        )
    return template[: starts[0].start()], template[ends[0].end() :]


def _regenerate_claude(template: bytes, custom_content: bytes) -> bytes:
    """Mirror the dependency-free CJS migrator's ``regenerateClaude``."""
    try:
        custom_content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CompositionError("CLAUDE.md composition inputs are not UTF-8") from error
    before, after = _extension_block(template)
    separator = b"\n" if custom_content and not custom_content.endswith(b"\n") else b""
    return before + custom_content + separator + after


def _compose_claude(release_blob: bytes, vault_root: Path) -> bytes:
    _extension_block(release_blob)
    custom_path = vault_root / "CLAUDE-custom.md"
    if not custom_path.exists() and not custom_path.is_symlink():
        return release_blob
    try:
        if custom_path.is_symlink() or not custom_path.is_file():
            raise CompositionError("CLAUDE-custom.md is not a regular file")
        custom_content = custom_path.read_bytes()
    except OSError as error:
        raise CompositionError("CLAUDE-custom.md is unreadable") from error
    if not custom_content:
        return release_blob
    return _regenerate_claude(release_blob, custom_content)


COMPOSERS: dict[str, Callable[[bytes, Path], bytes]] = {
    "CLAUDE.md": _compose_claude,
}


@dataclass(frozen=True)
class TreeEntry:
    path: str
    mode: int
    object_id: str


@dataclass(frozen=True)
class VerifiedReleaseRef:
    tag: str
    tag_object: str
    commit: str
    tree: str
    version: str
    channel: str
    brain_git: Path
    entries: tuple[TreeEntry, ...]


@dataclass(frozen=True)
class UpdatePlan:
    entries: tuple[PlanEntry, ...]
    replaced: tuple[str, ...]
    seeded: tuple[str, ...]
    regenerated: tuple[str, ...]
    pruned: tuple[str, ...]
    kept: tuple[str, ...]
    kept_reasons: tuple[tuple[str, str], ...]
    untouched: tuple[str, ...]


def _read_regular_json(path: Path, description: str) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise UpdateError(f"{description} is not a regular file")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise UpdateError(f"{description} is unreadable") from error
    if not isinstance(value, dict):
        raise UpdateError(f"{description} is not an object")
    return value


def _brain_output(vault_root: Path, brain_git: Path, *arguments: str) -> bytes:
    return git_output(
        vault_root,
        f"--git-dir={brain_git}",
        *arguments,
        profile="read-only",
    )


def _brain_text(vault_root: Path, brain_git: Path, *arguments: str) -> str:
    try:
        return _brain_output(vault_root, brain_git, *arguments).decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise ReleaseVerificationError("Git release metadata is not UTF-8") from error


def _tree_entries(vault_root: Path, brain_git: Path, commit: str) -> tuple[TreeEntry, ...]:
    raw = _brain_output(
        vault_root,
        brain_git,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        commit,
    )
    entries: list[TreeEntry] = []
    seen: set[str] = set()
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            raw_mode, object_type, object_id = metadata.decode("ascii").split(" ")
            relative = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise ReleaseVerificationError("release tree contains a malformed entry") from error
        if relative in seen or object_type != "blob" or raw_mode not in {"100644", "100755"}:
            raise ReleaseVerificationError("release tree is ambiguous or contains a symlink/unsupported entry")
        seen.add(relative)
        entries.append(TreeEntry(relative, 0o755 if raw_mode == "100755" else 0o644, object_id))
    return tuple(sorted(entries, key=lambda entry: entry.path))


def _blob(vault_root: Path, brain_git: Path, object_id: str) -> bytes:
    return _brain_output(vault_root, brain_git, "cat-file", "blob", object_id)


def _entry_map(entries: tuple[TreeEntry, ...]) -> dict[str, TreeEntry]:
    return {entry.path: entry for entry in entries}


def _verify_manifest(
    vault_root: Path,
    brain_git: Path,
    entries: tuple[TreeEntry, ...],
) -> None:
    by_path = _entry_map(entries)
    manifest = by_path.get(MANIFEST_RELATIVE)
    if manifest is None:
        raise ReleaseVerificationError("release is missing its installed-files manifest")
    try:
        source = _blob(vault_root, brain_git, manifest.object_id).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReleaseVerificationError("release manifest is not UTF-8") from error
    paths = source.splitlines()
    if not source.endswith("\n") or "\r" in source or paths != sorted(set(paths)) or set(paths) != set(by_path):
        raise ReleaseVerificationError("release manifest contradicts the exact release tree")


def _topology(vault_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root = Path(vault_root).resolve()
    for relative in (Path(".git"), Path(".dex"), BRAIN_RELATIVE, Path("System"), Path("System/.dex")):
        candidate = root / relative
        if candidate.is_symlink():
            raise UpdateError(f"split update refuses a symlinked {relative.as_posix()}")
    topology = _read_regular_json(root / TOPOLOGY_RELATIVE, "split topology marker")
    vault_marker = _read_regular_json(root / VAULT_MARKER_RELATIVE, "vault Git marker")
    brain_git = root / BRAIN_RELATIVE
    brain_marker = _read_regular_json(brain_git / BRAIN_MARKER_NAME, "brain Git marker")
    environment = topology.get("environment")
    wired_vault = environment.get("DEX_VAULT") if isinstance(environment, dict) else None
    try:
        vault_wiring_matches = isinstance(wired_vault, str) and Path(wired_vault).resolve() == root
    except (OSError, RuntimeError):
        vault_wiring_matches = False
    if (
        topology.get("topology") != "brain-vault-split"
        or topology.get("vaultGitDir") != ".git"
        or topology.get("brainGitDir") != ".dex/brain.git"
        or not vault_wiring_matches
        or vault_marker.get("role") != "vault"
        or brain_marker.get("role") != "brain"
        or not brain_git.is_dir()
    ):
        raise UpdateError("the brain/vault split topology is incomplete or inconsistent")
    return brain_git, topology, brain_marker


def _verify_official_origin(vault_root: Path, brain_git: Path) -> None:
    configured = _brain_text(vault_root, brain_git, "config", "--get", "remote.origin.url")
    effective = _brain_text(vault_root, brain_git, "remote", "get-url", "origin")
    if not OFFICIAL_REMOTE.fullmatch(configured) or not OFFICIAL_REMOTE.fullmatch(effective):
        raise ReleaseVerificationError("brain origin is not the effective official Dex repository")


def verify_release_ref(
    vault_root: Path,
    *,
    tag: str,
    tag_object: str,
    commit: str,
    tree: str,
) -> VerifiedReleaseRef:
    """Re-verify one evidence-pinned tag against the selected release channel."""
    root = Path(vault_root).resolve()
    brain_git, _topology_value, _brain_marker = _topology(root)
    _verify_official_origin(root, brain_git)
    match = RELEASE_TAG.fullmatch(tag)
    if match is None:
        raise ReleaseVerificationError("release ref is not an immutable dist/release/v* tag")
    if not re.fullmatch(r"[0-9a-f]{40,64}", tag_object):
        raise ReleaseVerificationError("release tag object identity is malformed")
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit) or not re.fullmatch(r"[0-9a-f]{40,64}", tree):
        raise ReleaseVerificationError("release commit/tree identity is malformed")

    actual_tag_object = _brain_text(root, brain_git, "rev-parse", "--verify", f"refs/tags/{tag}")
    if actual_tag_object != tag_object:
        raise ReleaseVerificationError("immutable release tag object does not match the evidence pin")
    if _brain_text(root, brain_git, "cat-file", "-t", tag_object) != "tag":
        raise ReleaseVerificationError("immutable release tag is not annotated")
    tag_payload = _brain_text(root, brain_git, "cat-file", "tag", tag_object)
    headers: dict[str, str] = {}
    for line in tag_payload.split("\n\n", 1)[0].splitlines():
        if " " not in line:
            continue
        key, value = line.split(" ", 1)
        if key in headers:
            raise ReleaseVerificationError("annotated release tag headers are ambiguous")
        headers[key] = value
    if headers.get("type") != "commit" or headers.get("tag") != tag or headers.get("object") != commit:
        raise ReleaseVerificationError("annotated release tag identity contradicts the evidence pin")
    if not commit.startswith(match.group("short")):
        raise ReleaseVerificationError("immutable tag suffix does not pin the full release commit")
    if _brain_text(root, brain_git, "rev-parse", "--verify", f"{commit}^{{tree}}") != tree:
        raise ReleaseVerificationError("release tree does not match the evidence pin")

    channel = release_channel.read_channel(root)
    if channel not in release_channel.VALID_CHANNELS:
        raise ReleaseVerificationError("the configured update channel is invalid")
    channel_commits = []
    for candidate in release_channel.release_ref_candidates(channel):
        try:
            channel_commits.append(
                _brain_text(
                    root,
                    brain_git,
                    "rev-parse",
                    "--verify",
                    f"refs/remotes/{candidate}^{{commit}}",
                )
            )
        except RuntimeError:
            continue
    if not channel_commits or commit not in channel_commits:
        raise ReleaseVerificationError(f"immutable release is not the pinned target of the {channel} channel")

    entries = _tree_entries(root, brain_git, commit)
    _verify_manifest(root, brain_git, entries)
    package_entry = _entry_map(entries).get("package.json")
    if package_entry is None:
        raise ReleaseVerificationError("release is missing package.json")
    try:
        package = json.loads(_blob(root, brain_git, package_entry.object_id).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseVerificationError("release package metadata is unreadable") from error
    if not isinstance(package, dict) or package.get("version") != match.group("version"):
        raise ReleaseVerificationError("release package version contradicts the immutable tag")
    return VerifiedReleaseRef(
        tag,
        tag_object,
        commit,
        tree,
        match.group("version"),
        channel,
        brain_git,
        entries,
    )


def _matches_entry(vault_root: Path, entry: TreeEntry, expected: bytes) -> bool:
    target = vault_root / entry.path
    try:
        return (
            not target.is_symlink()
            and target.is_file()
            and target.read_bytes() == expected
            and (target.stat().st_mode & 0o777) == entry.mode
        )
    except OSError:
        return False


def build_update_plan(vault_root: Path, release: VerifiedReleaseRef) -> UpdatePlan:
    """Build a fail-closed release mutation plan from contract verdicts."""
    root = Path(vault_root).resolve()
    installed = _brain_text(root, release.brain_git, "rev-parse", "--verify", "refs/dex/installed^{commit}")
    previous_entries = _tree_entries(root, release.brain_git, installed)
    _verify_manifest(root, release.brain_git, previous_entries)
    target_brain: set[str] = set()
    planned: list[PlanEntry] = []
    replaced: list[str] = []
    seeded: list[str] = []
    regenerated: list[str] = []
    kept: list[str] = []
    kept_reasons: list[tuple[str, str]] = []
    untouched: list[str] = []

    for entry in release.entries:
        target = root / entry.path
        verdict = portable_contract.update_write_verdict(entry.path, exists=target.exists())
        if verdict.action in {"deny", "unclassified-never-write"}:
            raise UpdateError(
                f"release contains a path the ownership contract refuses: {entry.path} [{verdict.action}]"
            )
        if verdict.ownership == "brain":
            target_brain.add(entry.path)
        if not verdict.allowed:
            untouched.append(entry.path)
            continue
        content = _blob(root, release.brain_git, entry.object_id)
        composer = COMPOSERS.get(entry.path)
        if composer is not None:
            try:
                content = composer(content, root)
            except CompositionError as error:
                kept.append(entry.path)
                kept_reasons.append((entry.path, str(error)))
                continue
        if _matches_entry(root, entry, content):
            untouched.append(entry.path)
            continue
        planned.append(PlanEntry(entry.path, content, entry.mode))
        if verdict.ownership == "brain":
            replaced.append(entry.path)
        elif verdict.ownership == "seed":
            seeded.append(entry.path)
        elif verdict.ownership == "generated":
            regenerated.append(entry.path)

    pruned: list[str] = []
    for previous in previous_entries:
        resolution = portable_contract.resolve(previous.path)
        if resolution.ownership != "brain" or previous.path in target_brain:
            continue
        target = root / previous.path
        if not target.exists():
            continue
        previous_content = _blob(root, release.brain_git, previous.object_id)
        if _matches_entry(root, previous, previous_content):
            verdict = portable_contract.update_write_verdict(previous.path, exists=True)
            if not verdict.allowed or verdict.ownership != "brain":
                raise UpdateError(f"ownership contract refuses pruning {previous.path}")
            planned.append(
                PlanEntry(
                    previous.path,
                    None,
                    previous.mode,
                    expected_current_sha256=hashlib.sha256(
                        previous_content
                    ).hexdigest(),
                )
            )
            pruned.append(previous.path)
        else:
            kept.append(previous.path)

    return UpdatePlan(
        tuple(planned),
        tuple(replaced),
        tuple(seeded),
        tuple(regenerated),
        tuple(pruned),
        tuple(kept),
        tuple(kept_reasons),
        tuple(untouched),
    )


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temporary = path.parent / f".{path.name}.update-{os.getpid()}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _finalize_release_metadata(
    vault_root: Path,
    release: VerifiedReleaseRef,
    previous_commit: str,
) -> None:
    topology_path = vault_root / TOPOLOGY_RELATIVE
    marker_path = release.brain_git / BRAIN_MARKER_NAME
    topology = _read_regular_json(topology_path, "split topology marker")
    marker = _read_regular_json(marker_path, "brain Git marker")
    previous_topology = dict(topology)
    previous_marker = dict(marker)
    topology["installedRelease"] = release.commit
    marker["installed"] = release.commit
    try:
        _atomic_json(topology_path, topology)
        _atomic_json(marker_path, marker)
        git_output(
            vault_root,
            f"--git-dir={release.brain_git}",
            "update-ref",
            "refs/dex/installed",
            release.commit,
            previous_commit,
            profile="mutation",
        )
    except BaseException:
        _atomic_json(topology_path, previous_topology)
        _atomic_json(marker_path, previous_marker)
        raise


def apply_verified_release(vault_root: Path, release: VerifiedReleaseRef) -> dict[str, Any]:
    """Apply a verified immutable release through the shared transaction core."""
    root = Path(vault_root).resolve()
    Transaction.resume(root)
    brain_git, topology, marker = _topology(root)
    if brain_git != release.brain_git:
        raise UpdateError("verified release belongs to a different split brain store")
    previous_commit = _brain_text(root, brain_git, "rev-parse", "--verify", "refs/dex/installed^{commit}")
    if topology.get("installedRelease") != previous_commit or marker.get("installed") != previous_commit:
        raise UpdateError("installed release identity disagrees across the split topology markers")
    if previous_commit == release.commit:
        raise UpdateError("that immutable release is already installed")
    plan = build_update_plan(root, release)
    transaction = Transaction.begin(root, list(plan.entries), allow_empty=True)
    transaction_result = transaction.run(
        before_commit=lambda: _finalize_release_metadata(
            root,
            release,
            previous_commit,
        )
    )
    return {
        **transaction_result,
        "tag": release.tag,
        "commit": release.commit,
        "version": release.version,
        "channel": release.channel,
        "replaced": list(plan.replaced),
        "seeded": list(plan.seeded),
        "regenerated": list(plan.regenerated),
        "pruned": list(plan.pruned),
        "kept": list(plan.kept),
        "kept_reasons": dict(plan.kept_reasons),
        "untouched": list(plan.untouched),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=Path.cwd())
    parser.add_argument("--tag", required=True)
    parser.add_argument("--tag-object", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tree", required=True)
    args = parser.parse_args(argv)
    try:
        release = verify_release_ref(
            args.vault,
            tag=args.tag,
            tag_object=args.tag_object,
            commit=args.commit,
            tree=args.tree,
        )
        result = apply_verified_release(args.vault, release)
    except (OSError, RuntimeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
