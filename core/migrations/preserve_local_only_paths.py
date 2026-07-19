#!/usr/bin/env python3
"""Preserve and untrack only Dex's three approved local-only paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from core.utils.tracked_ignored import (
    LOCAL_ONLY_PATHS,
    TrackedIgnoredError,
    git_executable,
    load_exact_policy,
    load_transition,
    query_tracked_ignored,
    sanitized_git_env,
)

POLICY_RELATIVE = Path("core/migrations/tracked-ignored-policy.yaml")
MANIFEST_NAME = "journal.json"
INDEX_FLAGS = {
    "0",
    "8000",
    "20004000",
    "2000c000",
    "40004000",
    "4000c000",
    "60004000",
    "6000c000",
}


class MigrationError(RuntimeError):
    """The exact preservation migration cannot proceed safely."""


def _git(repo: Path, *arguments: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            [
                git_executable(),
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-C",
                os.fspath(repo),
                *arguments,
            ],
            input=input_bytes,
            capture_output=True,
            env=sanitized_git_env(),
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise MigrationError(f"git command failed before mutation completed: {error}") from error


def _run_git(repo: Path, *arguments: str) -> bytes:
    result = _git(repo, *arguments)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise MigrationError(detail or f"git {' '.join(arguments)} exited {result.returncode}")
    return result.stdout


def _load_policy(repo: Path, policy_path: Path | None = None) -> tuple[set[str], set[str], str]:
    try:
        policy = load_exact_policy(policy_path or repo / POLICY_RELATIVE)
    except TrackedIgnoredError as error:
        raise MigrationError(str(error)) from error
    return policy.paths, policy.local_only_paths, policy.sha256


def _query_tracked_ignored(repo: Path) -> set[str]:
    try:
        return set(query_tracked_ignored(repo))
    except TrackedIgnoredError as error:
        raise MigrationError(str(error)) from error


def _index_entry(repo: Path, relative: str, *, required: bool = True) -> dict[str, Any] | None:
    output = _run_git(repo, "ls-files", "--stage", "--debug", "--", relative)
    if not output:
        if required:
            raise MigrationError(f"bootstrap capture requires a tracked index entry: {relative}")
        return None
    lines = output.decode("utf-8", "surrogateescape").splitlines()
    if len(lines) != 6:
        raise MigrationError(f"conflicted index entry requires manual resolution: {relative}")
    try:
        metadata, output_path = lines[0].split("\t", 1)
        mode, oid, stage = metadata.split(" ")
        flags = lines[5].rsplit("flags: ", 1)[1]
    except (IndexError, ValueError) as error:
        raise MigrationError(f"unexpected index metadata for local-only path: {relative}") from error
    if output_path != relative or stage != "0" or flags not in INDEX_FLAGS:
        raise MigrationError(f"unexpected index identity for local-only path: {relative}")
    return {"tracked": True, "mode": mode, "oid": oid, "stage": 0, "flags": flags}


def _payload_path(journal_dir: Path, ordinal: int) -> Path:
    return journal_dir / "payloads" / f"apply-{ordinal}.bin"


def _rewind_payload_path(journal_dir: Path, ordinal: int) -> Path:
    return journal_dir / "payloads" / f"rewind-{ordinal}.bin"


def _snapshot_worktree(repo: Path, relative: str, payload: Path) -> dict[str, Any]:
    target = repo / relative
    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        return {"state": "absent"}
    if not stat.S_ISREG(target_stat.st_mode):
        raise MigrationError(f"local-only path must be a regular file or absent: {relative}")
    data = target.read_bytes()
    payload.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload.write_bytes(data)
    payload.chmod(0o600)
    return {
        "state": "present",
        "mode": stat.S_IMODE(target_stat.st_mode),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _write_journal(journal_dir: Path, payload: dict[str, Any]) -> None:
    journal_path = journal_dir / MANIFEST_NAME
    descriptor, temporary_name = tempfile.mkstemp(prefix=".journal.", dir=journal_dir)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, journal_path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise MigrationError(f"duplicate preservation journal key: {key}")
        payload[key] = value
    return payload


def _valid_index_snapshot(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"tracked", "mode", "oid", "stage", "flags"}
        and value.get("tracked") is True
        and value.get("mode") in {"100644", "100755"}
        and isinstance(value.get("oid"), str)
        and len(value["oid"]) in {40, 64}
        and all(character in "0123456789abcdef" for character in value["oid"])
        and value.get("stage") == 0
        and value.get("flags") in INDEX_FLAGS
    )


def _valid_worktree_snapshot(value: object) -> bool:
    if not isinstance(value, dict) or value.get("state") not in {"present", "deleted", "absent"}:
        return False
    if value["state"] != "present":
        return set(value) == {"state"}
    return (
        set(value) == {"state", "mode", "size", "sha256"}
        and isinstance(value.get("mode"), int)
        and 0 <= value["mode"] <= 0o777
        and isinstance(value.get("size"), int)
        and value["size"] >= 0
        and isinstance(value.get("sha256"), str)
        and len(value["sha256"]) == 64
        and all(character in "0123456789abcdef" for character in value["sha256"])
    )


def _validate_journal(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "policy_sha256",
        "source_transition",
        "phase",
        "entries",
        "rewind_worktree",
    }:
        raise MigrationError("preservation journal has unexpected or missing fields")
    if payload.get("schema_version") != 1 or payload.get("phase") not in {
        "captured",
        "applying",
        "applied",
        "rewind-captured",
        "rewinding-original",
        "rewinding",
        "rewound",
    }:
        raise MigrationError("preservation journal schema or phase is unsupported")
    source_transition = payload.get("source_transition")
    if (
        not isinstance(source_transition, dict)
        or set(source_transition) != {"phase", "release_version"}
        or source_transition.get("phase") != "bootstrap-v1"
        or not isinstance(source_transition.get("release_version"), str)
        or not source_transition["release_version"]
    ):
        raise MigrationError("preservation journal source transition is invalid")
    policy_hash = payload.get("policy_sha256")
    if (
        not isinstance(policy_hash, str)
        or len(policy_hash) != 64
        or any(character not in "0123456789abcdef" for character in policy_hash)
    ):
        raise MigrationError("preservation journal policy identity is invalid")
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) != len(LOCAL_ONLY_PATHS):
        raise MigrationError("preservation journal must contain exactly three ordered entries")
    for ordinal, relative in enumerate(LOCAL_ONLY_PATHS):
        entry = entries[ordinal]
        if not isinstance(entry, dict) or set(entry) != {"path", "index", "worktree"}:
            raise MigrationError("preservation journal entry fields are invalid")
        if entry.get("path") != relative:
            raise MigrationError("preservation journal entry identities are not the closed ordered paths")
        if not _valid_index_snapshot(entry.get("index")):
            raise MigrationError(f"preservation journal index metadata is invalid at ordinal {ordinal}")
        if not _valid_worktree_snapshot(entry.get("worktree")):
            raise MigrationError(f"preservation journal worktree metadata is invalid at ordinal {ordinal}")
    rewind_worktree = payload.get("rewind_worktree")
    if rewind_worktree is not None:
        if not isinstance(rewind_worktree, list) or len(rewind_worktree) != len(LOCAL_ONLY_PATHS):
            raise MigrationError("preservation journal rewind metadata is invalid")
        if not all(_valid_worktree_snapshot(value) for value in rewind_worktree):
            raise MigrationError("preservation journal rewind snapshot metadata is invalid")
    return payload


def _read_journal(journal_dir: Path) -> dict[str, Any]:
    identities = _prevalidate_journal_container(journal_dir)
    journal_path = journal_dir / MANIFEST_NAME
    try:
        payload = json.loads(
            journal_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (OSError, json.JSONDecodeError) as error:
        raise MigrationError(f"could not read preservation journal: {error}") from error
    journal = _validate_journal(payload)
    _prevalidate_journal_storage(journal_dir, journal, identities)
    return journal


def _read_fixed_payload(source: Path, expected_hash: object, relative: str) -> bytes:
    source_stat = source.lstat()
    if not stat.S_ISREG(source_stat.st_mode) or stat.S_ISLNK(source_stat.st_mode):
        raise MigrationError(f"preservation payload is not a regular file: {relative}")
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise MigrationError(f"preservation payload hash mismatch: {relative}")
    return data


def _require_private_path(path: Path, *, directory: bool) -> os.stat_result:
    try:
        path_stat = path.lstat()
    except OSError as error:
        raise MigrationError(f"preservation storage path is unavailable: {path}") from error
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if stat.S_ISLNK(path_stat.st_mode) or not expected(path_stat.st_mode):
        raise MigrationError(f"preservation storage has invalid type: {path}")
    required_mode = 0o700 if directory else 0o600
    if stat.S_IMODE(path_stat.st_mode) != required_mode or path_stat.st_uid != os.getuid():
        raise MigrationError(f"preservation storage owner or mode is invalid: {path}")
    return path_stat


def _identity(path_stat: os.stat_result) -> tuple[int, int]:
    return path_stat.st_dev, path_stat.st_ino


def _prevalidate_journal_container(journal_dir: Path) -> dict[Path, tuple[int, int]]:
    parent = journal_dir.parent
    paths = {
        parent: _require_private_path(parent, directory=True),
        journal_dir: _require_private_path(journal_dir, directory=True),
        journal_dir / MANIFEST_NAME: _require_private_path(journal_dir / MANIFEST_NAME, directory=False),
        journal_dir / "payloads": _require_private_path(journal_dir / "payloads", directory=True),
    }
    identities = {path: _identity(path_stat) for path, path_stat in paths.items()}
    for path, expected in identities.items():
        if _identity(path.lstat()) != expected:
            raise MigrationError("preservation storage identity changed during container validation")
    return identities


def _prevalidate_journal_storage(
    journal_dir: Path,
    journal: dict[str, Any],
    identities: dict[Path, tuple[int, int]],
) -> None:
    root_before = _require_private_path(journal_dir, directory=True)
    payload_dir = journal_dir / "payloads"
    payload_before = _require_private_path(payload_dir, directory=True)
    expected: dict[Path, tuple[object, object, str]] = {}
    for ordinal, relative in enumerate(LOCAL_ONLY_PATHS):
        snapshot = journal["entries"][ordinal]["worktree"]
        if snapshot["state"] == "present":
            expected[_payload_path(journal_dir, ordinal)] = (snapshot["sha256"], snapshot["size"], relative)
        rewind_snapshot = journal["rewind_worktree"]
        if rewind_snapshot is not None and rewind_snapshot[ordinal]["state"] == "present":
            value = rewind_snapshot[ordinal]
            expected[_rewind_payload_path(journal_dir, ordinal)] = (value["sha256"], value["size"], relative)
    actual = set(payload_dir.iterdir())
    if actual != set(expected):
        raise MigrationError("preservation payload set is missing or contains unexpected files")
    for payload_path, (expected_hash, expected_size, relative) in expected.items():
        payload_stat = _require_private_path(payload_path, directory=False)
        data = payload_path.read_bytes()
        if payload_stat.st_size != expected_size or len(data) != expected_size:
            raise MigrationError(f"preservation payload size mismatch: {relative}")
        if hashlib.sha256(data).hexdigest() != expected_hash:
            raise MigrationError(f"preservation payload hash mismatch: {relative}")
    expected_identities = dict(identities)
    expected_identities[journal_dir] = _identity(root_before)
    expected_identities[payload_dir] = _identity(payload_before)
    for path, expected_identity in expected_identities.items():
        if _identity(path.lstat()) != expected_identity:
            raise MigrationError("preservation storage identity changed during validation")


def _create_journal(
    repo: Path,
    journal_dir: Path,
    policy_hash: str,
    source_version: str,
) -> dict[str, Any]:
    try:
        journal_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError as error:
        raise MigrationError("journal already exists but has no resumable manifest") from error
    (journal_dir / "payloads").mkdir(mode=0o700)
    entries = []
    for index, relative in enumerate(LOCAL_ONLY_PATHS):
        index_entry = _index_entry(repo, relative)
        assert index_entry is not None
        worktree = _snapshot_worktree(repo, relative, _payload_path(journal_dir, index))
        if worktree["state"] == "absent":
            worktree["state"] = "deleted" if index_entry["tracked"] else "absent"
        entries.append({"path": relative, "index": index_entry, "worktree": worktree})
    payload: dict[str, Any] = {
        "schema_version": 1,
        "policy_sha256": policy_hash,
        "source_transition": {"phase": "bootstrap-v1", "release_version": source_version},
        "phase": "captured",
        "entries": entries,
        "rewind_worktree": None,
    }
    _write_journal(journal_dir, payload)
    return payload


def _has_symlink_parent(repo: Path, relative: str) -> bool:
    current = repo
    for part in Path(relative).parts[:-1]:
        current = current / part
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(current_stat.st_mode):
            return True
    return False


def _restore_captured_if_missing(
    repo: Path,
    journal_dir: Path,
    ordinal: int,
    relative: str,
    snapshot: dict[str, Any],
) -> None:
    """Restore captured bytes only when the release transition removed the file."""
    if snapshot.get("state") != "present":
        return
    target = repo / relative
    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        target_stat = None
    if target_stat is not None:
        if not stat.S_ISREG(target_stat.st_mode):
            raise MigrationError(f"local-only path changed to a non-regular file: {relative}")
        return
    if _has_symlink_parent(repo, relative):
        raise MigrationError(f"refusing to restore local-only path through a symlink: {relative}")
    source = _payload_path(journal_dir, ordinal)
    data = _read_fixed_payload(source, snapshot.get("sha256"), relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, int(snapshot["mode"]))
        os.replace(temporary_name, target)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _restore_exact_worktree(
    repo: Path,
    relative: str,
    snapshot: dict[str, Any],
    source: Path,
) -> None:
    target = repo / relative
    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        target_stat = None
    if target_stat is not None and not stat.S_ISREG(target_stat.st_mode):
        raise MigrationError(f"local-only path changed to a non-regular file: {relative}")
    if snapshot["state"] != "present":
        if target_stat is not None:
            target.unlink()
        return
    if _has_symlink_parent(repo, relative):
        raise MigrationError(f"refusing to restore local-only path through a symlink: {relative}")
    data = _read_fixed_payload(source, snapshot.get("sha256"), relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, int(snapshot["mode"]))
        os.replace(temporary_name, target)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def capture(repo: Path, journal_dir: Path, policy_path: Path | None = None) -> dict[str, Any]:
    existing: dict[str, Any] | None = None
    if journal_dir.exists() or journal_dir.is_symlink():
        existing = _read_journal(journal_dir)
        if existing.get("phase") != "rewound":
            raise MigrationError(f"journal cannot recapture from phase: {existing.get('phase')}")
    policy_paths, _, policy_hash = _load_policy(repo, policy_path)
    try:
        transition = load_transition(repo)
    except TrackedIgnoredError as error:
        raise MigrationError(str(error)) from error
    if transition.phase != "bootstrap-v1":
        raise MigrationError("capture requires bootstrap-v1 transition metadata")
    if _query_tracked_ignored(repo) != policy_paths:
        raise MigrationError(
            "live tracked-ignore query differs from the exact 27-row baseline; no preservation journal was created"
        )
    if existing is not None:
        parent_before = _require_private_path(journal_dir.parent, directory=True)
        archive = journal_dir.with_name(f"archive-{uuid.uuid4().hex}")
        os.replace(journal_dir, archive)
        if _identity(journal_dir.parent.lstat()) != _identity(parent_before):
            raise MigrationError("preservation storage parent identity changed during recapture")
    return _create_journal(repo, journal_dir, policy_hash, transition.release_version)


def capture_rewind(repo: Path, journal_dir: Path, policy_path: Path | None = None) -> dict[str, Any]:
    journal = _read_journal(journal_dir)
    policy_paths, local_paths, policy_hash = _load_policy(repo, policy_path)
    try:
        transition = load_transition(repo)
    except TrackedIgnoredError as error:
        raise MigrationError(str(error)) from error
    if transition.phase != "untrack-v1":
        raise MigrationError("rewind capture requires untrack-v1 transition metadata")
    if journal.get("policy_sha256") != policy_hash:
        raise MigrationError("tracked-ignore policy changed before rewind capture")
    if journal.get("phase") not in {"applied", "rewind-captured"}:
        raise MigrationError(f"journal cannot capture rewind from phase: {journal.get('phase')}")
    if _query_tracked_ignored(repo) != policy_paths - local_paths:
        raise MigrationError("rewind capture requires the exact approved 24-path state")
    journal["rewind_worktree"] = [
        _snapshot_worktree(repo, relative, _rewind_payload_path(journal_dir, ordinal))
        for ordinal, relative in enumerate(LOCAL_ONLY_PATHS)
    ]
    journal["phase"] = "rewind-captured"
    _write_journal(journal_dir, journal)
    return journal


def apply(repo: Path, journal_dir: Path, policy_path: Path | None = None) -> dict[str, Any]:
    journal_path = journal_dir / MANIFEST_NAME
    if journal_path.exists():
        journal = _read_journal(journal_dir)
        if journal.get("phase") not in {"captured", "applying", "applied"}:
            raise MigrationError(f"journal cannot resume apply from phase: {journal.get('phase')}")
        policy_paths, local_paths, policy_hash = _load_policy(repo, policy_path)
        if journal.get("policy_sha256") != policy_hash:
            raise MigrationError("tracked-ignore policy changed after preservation capture")
    else:
        raise MigrationError("apply requires the bootstrap journal captured before the release merge")

    try:
        transition = load_transition(repo)
    except TrackedIgnoredError as error:
        raise MigrationError(str(error)) from error
    if transition.phase != "untrack-v1":
        raise MigrationError("apply requires untrack-v1 transition metadata; bootstrap remains tracked")

    actual = _query_tracked_ignored(repo)
    expected_states = [policy_paths - set(LOCAL_ONLY_PATHS[:count]) for count in range(4)]
    if actual not in expected_states:
        raise MigrationError("live tracked-ignore query drifted during apply; no broader mutation ran")
    if journal["phase"] == "applied":
        if actual != policy_paths - local_paths:
            raise MigrationError("applied journal does not match the exact approved 24-path state")
        return journal

    if journal["phase"] == "captured":
        journal["phase"] = "applying"
        _write_journal(journal_dir, journal)

    for relative in LOCAL_ONLY_PATHS:
        if relative not in actual:
            continue
        result = _git(repo, "update-index", "--force-remove", "--", relative)
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise MigrationError(detail or f"could not untrack approved local-only path: {relative}")
        actual.remove(relative)

    expected_after = policy_paths - local_paths
    if _query_tracked_ignored(repo) != expected_after:
        raise MigrationError("post-migration tracked-ignore query is not the exact approved 24-path set")
    for ordinal, relative in enumerate(LOCAL_ONLY_PATHS):
        _restore_captured_if_missing(
            repo,
            journal_dir,
            ordinal,
            relative,
            journal["entries"][ordinal]["worktree"],
        )
    journal["phase"] = "applied"
    _write_journal(journal_dir, journal)
    return journal


def _restore_index_entry(repo: Path, relative: str, index_entry: dict[str, Any]) -> None:
    removal = _git(repo, "update-index", "--force-remove", "--", relative)
    if removal.returncode != 0:
        detail = removal.stderr.decode("utf-8", "replace").strip()
        raise MigrationError(detail or f"could not clear index entry before restore: {relative}")

    oid = str(index_entry["oid"])
    flags = str(index_entry["flags"])
    intent_to_add = flags.startswith(("2", "6"))
    assume_unchanged = flags in {"8000", "2000c000", "4000c000", "6000c000"}
    skip_worktree = flags.startswith(("4", "6"))
    if intent_to_add:
        target = repo / relative
        try:
            target_stat = target.lstat()
        except FileNotFoundError:
            target_stat = None
        if target_stat is not None and not stat.S_ISREG(target_stat.st_mode):
            raise MigrationError(f"local-only path changed to a non-regular file: {relative}")
        if _has_symlink_parent(repo, relative):
            raise MigrationError(f"refusing to restore local-only index through a symlink: {relative}")
        original_mode = stat.S_IMODE(target_stat.st_mode) if target_stat is not None else None
        try:
            if target_stat is None:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"")
            target.chmod(0o755 if index_entry["mode"] == "100755" else 0o644)
            result = _git(repo, "add", "-f", "--intent-to-add", "--", relative)
        finally:
            if original_mode is None:
                target.unlink(missing_ok=True)
            else:
                target.chmod(original_mode)
    else:
        result = _git(
            repo,
            "update-index",
            "--add",
            "--cacheinfo",
            f"{index_entry['mode']},{oid},{relative}",
        )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise MigrationError(detail or f"could not restore index entry: {relative}")
    flag_commands = []
    if skip_worktree:
        flag_commands.append(("update-index", "--skip-worktree", "--", relative))
    if assume_unchanged:
        flag_commands.append(("update-index", "--assume-unchanged", "--", relative))
    for arguments in flag_commands:
        result = _git(repo, *arguments)
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise MigrationError(detail or f"could not restore index flags: {relative}")
    restored = _index_entry(repo, relative)
    if restored != index_entry:
        raise MigrationError(
            f"restored index identity does not match captured state: {relative}: {restored!r}"
        )


def rewind(
    repo: Path,
    journal_dir: Path,
    policy_path: Path | None = None,
    target_phase: str | None = None,
) -> dict[str, Any]:
    journal = _read_journal(journal_dir)
    restore_original_worktree = journal.get("phase") in {
        "captured",
        "applying",
        "rewinding-original",
    }
    if journal.get("phase") not in {
        "captured",
        "applying",
        "applied",
        "rewind-captured",
        "rewinding-original",
        "rewinding",
        "rewound",
    }:
        raise MigrationError(f"journal cannot rewind from phase: {journal.get('phase')}")
    policy_paths, local_paths, policy_hash = _load_policy(repo, policy_path)
    if target_phase == "bootstrap-legacy":
        try:
            load_transition(repo)
        except TrackedIgnoredError:
            pass
        else:
            raise MigrationError("legacy rewind target unexpectedly contains transition metadata")
    else:
        try:
            transition = load_transition(repo)
        except TrackedIgnoredError as error:
            raise MigrationError(str(error)) from error
        if transition.phase != "bootstrap-v1" or target_phase not in {None, "bootstrap-v1"}:
            raise MigrationError("rewind requires a bootstrap-v1 rollback target")
    if journal.get("policy_sha256") != policy_hash:
        raise MigrationError("tracked-ignore policy changed before rewind")
    actual = _query_tracked_ignored(repo)
    expected_after = policy_paths - local_paths
    if actual - policy_paths or actual - local_paths != expected_after:
        raise MigrationError("live tracked-ignore query drifted before rewind; no index mutation ran")
    if journal["phase"] == "rewound":
        if actual != policy_paths:
            raise MigrationError("rewound journal does not match the exact approved 27-path state")
        return journal

    if journal.get("phase") not in {"rewinding", "rewinding-original"}:
        journal["phase"] = "rewinding-original" if restore_original_worktree else "rewinding"
        _write_journal(journal_dir, journal)

    for ordinal, relative in enumerate(LOCAL_ONLY_PATHS):
        expected_index = journal["entries"][ordinal]["index"]
        if _index_entry(repo, relative, required=False) == expected_index:
            continue
        _restore_index_entry(repo, relative, expected_index)
        actual.add(relative)

    if _query_tracked_ignored(repo) != policy_paths:
        raise MigrationError("rewind did not restore the exact approved 27-path tracked-ignore set")
    snapshots = journal["rewind_worktree"]
    if snapshots is not None or restore_original_worktree:
        for ordinal, relative in enumerate(LOCAL_ONLY_PATHS):
            snapshot = snapshots[ordinal] if snapshots is not None else journal["entries"][ordinal]["worktree"]
            source = (
                _rewind_payload_path(journal_dir, ordinal)
                if snapshots is not None
                else _payload_path(journal_dir, ordinal)
            )
            _restore_exact_worktree(repo, relative, snapshot, source)
    journal["phase"] = "rewound"
    _write_journal(journal_dir, journal)
    return journal


def preview(repo: Path, policy_path: Path | None = None) -> dict[str, Any]:
    policy_paths, local_paths, _ = _load_policy(repo, policy_path)
    try:
        transition = load_transition(repo)
    except TrackedIgnoredError as error:
        raise MigrationError(str(error)) from error
    actual = _query_tracked_ignored(repo)
    if transition.phase == "bootstrap-v1" and actual == policy_paths:
        state = "bootstrap-installed"
    elif transition.phase == "untrack-v1" and actual == policy_paths:
        state = "ready-to-apply"
    elif transition.phase == "untrack-v1" and actual == policy_paths - local_paths:
        state = "already-applied"
    else:
        state = "blocked-query-mismatch"
    return {"ok": state != "blocked-query-mismatch", "state": state, "actual_count": len(actual)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "capture", "apply", "capture-rewind", "rewind"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--target-phase", choices=("bootstrap-v1", "bootstrap-legacy"))
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve()
        policy_path = args.policy.resolve() if args.policy else None
        if args.action == "preview":
            result = preview(repo, policy_path)
        else:
            if args.journal is None:
                raise MigrationError("--journal is required for capture, apply, and rewind")
            if args.action == "capture":
                result = capture(repo, args.journal.resolve(), policy_path)
            elif args.action == "apply":
                result = apply(repo, args.journal.resolve(), policy_path)
            elif args.action == "capture-rewind":
                result = capture_rewind(repo, args.journal.resolve(), policy_path)
            else:
                result = rewind(repo, args.journal.resolve(), policy_path, args.target_phase)
            result = {"ok": True, "phase": result["phase"], "paths": list(LOCAL_ONLY_PATHS)}
    except (MigrationError, OSError, ValueError, json.JSONDecodeError) as error:
        result = {"ok": False, "error": str(error)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
