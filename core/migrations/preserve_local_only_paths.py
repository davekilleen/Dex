#!/usr/bin/env python3
"""Preserve and untrack only Dex's three approved local-only paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

LOCAL_ONLY_PATHS = (
    "System/Session_Learnings/2026-01-29.md",
    "System/Session_Learnings/2026-01-30.md",
    "System/integrations/slack.yaml",
)
APPROVED_TRACKED_ROWS = (
    "00-Inbox/Daily_Plans/README.md",
    "00-Inbox/Ideas/README.md",
    "00-Inbox/Meetings/README.md",
    "00-Inbox/README.md",
    "01-Quarter_Goals/Quarter_Goals.md",
    "02-Week_Priorities/Week_Priorities.md",
    "03-Tasks/Tasks.md",
    "04-Projects/README.md",
    "05-Areas/Career/Evidence/README.md",
    "05-Areas/Companies/README.md",
    "05-Areas/People/External/README.md",
    "05-Areas/People/Internal/README.md",
    "05-Areas/People/README.md",
    "05-Areas/README.md",
    "07-Archives/Plans/README.md",
    "07-Archives/Projects/README.md",
    "07-Archives/README.md",
    "07-Archives/Reviews/README.md",
    "System/Dex_Backlog.md",
    "System/Session_Learnings/README.md",
    "System/pillars.yaml",
    "System/usage_log.md",
    "System/user-profile.yaml",
    "System/Beta_Communications/2026-02-04_hardcoded_paths_fix.md",
)
APPROVED_ROWS = tuple(
    (path, "release-doc" if path.startswith("System/Beta_Communications/") else "intentional-seed")
    for path in APPROVED_TRACKED_ROWS
) + tuple((path, "local-only-must-be-untracked") for path in LOCAL_ONLY_PATHS)
POLICY_RELATIVE = Path("scripts/tracked-ignored-policy.yaml")
MANIFEST_NAME = "journal.json"


class MigrationError(RuntimeError):
    """The exact preservation migration cannot proceed safely."""


def _sanitized_git_env() -> dict[str, str]:
    environment = os.environ.copy()
    unsafe_exact = {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_OPTIONAL_LOCKS",
        "GIT_WORK_TREE",
    }
    for key in tuple(environment):
        if key in unsafe_exact or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            environment.pop(key, None)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_LITERAL_PATHSPECS"] = "1"
    return environment


def _git(repo: Path, *arguments: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    executable = shutil.which("git")
    if not executable:
        raise MigrationError("git is unavailable; local-only preservation requires Git")
    try:
        return subprocess.run(
            [
                executable,
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
            env=_sanitized_git_env(),
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


def _load_policy(repo: Path) -> tuple[set[str], set[str], str]:
    policy_path = repo / POLICY_RELATIVE
    try:
        policy_bytes = policy_path.read_bytes()
        payload = yaml.safe_load(policy_bytes)
    except (OSError, yaml.YAMLError) as error:
        raise MigrationError(f"could not read exact tracked-ignore policy: {error}") from error
    rows = payload.get("paths") if isinstance(payload, dict) else None
    if payload.get("schema_version") != 1 or payload.get("baseline_count") != 27 or not isinstance(rows, list):
        raise MigrationError("tracked-ignore policy is not the approved 27-row schema")
    policy_rows: list[tuple[str, str]] = []
    all_paths: list[str] = []
    local_paths: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "classification"}:
            raise MigrationError("tracked-ignore policy contains a malformed row")
        path = row.get("path")
        if not isinstance(path, str) or path in all_paths:
            raise MigrationError("tracked-ignore policy contains an invalid or duplicate path")
        all_paths.append(path)
        classification = row.get("classification")
        if not isinstance(classification, str):
            raise MigrationError("tracked-ignore policy contains an invalid classification")
        policy_rows.append((path, classification))
        if classification == "local-only-must-be-untracked":
            local_paths.append(path)
    if tuple(policy_rows) != APPROVED_ROWS or tuple(local_paths) != LOCAL_ONLY_PATHS:
        raise MigrationError("tracked-ignore policy differs from the exact approved 27 rows")
    return set(all_paths), set(local_paths), hashlib.sha256(policy_bytes).hexdigest()


def _query_tracked_ignored(repo: Path) -> set[str]:
    output = _run_git(repo, "ls-files", "-ci", "--exclude-standard", "-z")
    return {
        value.decode("utf-8", "surrogateescape")
        for value in output.split(b"\0")
        if value
    }


def _index_entry(repo: Path, relative: str) -> dict[str, Any]:
    output = _run_git(repo, "ls-files", "--stage", "-z", "--", relative)
    records = [record for record in output.split(b"\0") if record]
    if not records:
        return {"tracked": False}
    if len(records) != 1:
        raise MigrationError(f"conflicted index entry requires manual resolution: {relative}")
    metadata, encoded_path = records[0].split(b"\t", 1)
    mode, oid, stage = metadata.decode("ascii").split(" ")
    if encoded_path.decode("utf-8", "surrogateescape") != relative or stage != "0":
        raise MigrationError(f"unexpected index identity for local-only path: {relative}")
    return {"tracked": True, "mode": mode, "oid": oid, "stage": 0}


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
        "sha256": hashlib.sha256(data).hexdigest(),
        "payload": payload.name,
    }


def _current_worktree(repo: Path, relative: str) -> dict[str, Any]:
    target = repo / relative
    try:
        target_stat = target.lstat()
    except FileNotFoundError:
        return {"state": "absent"}
    if not stat.S_ISREG(target_stat.st_mode):
        raise MigrationError(f"local-only path changed to a non-regular file: {relative}")
    data = target.read_bytes()
    return {
        "state": "present",
        "mode": stat.S_IMODE(target_stat.st_mode),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _same_worktree(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    keys = {"state"} if expected.get("state") == "absent" else {"state", "mode", "sha256"}
    return all(expected.get(key) == actual.get(key) for key in keys)


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


def _read_journal(journal_dir: Path) -> dict[str, Any]:
    try:
        payload = json.loads((journal_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MigrationError(f"could not read preservation journal: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise MigrationError("preservation journal schema is unsupported")
    return payload


def _create_journal(repo: Path, journal_dir: Path, policy_hash: str) -> dict[str, Any]:
    try:
        journal_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError as error:
        raise MigrationError("journal already exists but has no resumable manifest") from error
    entries = []
    for index, relative in enumerate(LOCAL_ONLY_PATHS):
        index_entry = _index_entry(repo, relative)
        worktree = _snapshot_worktree(
            repo, relative, journal_dir / "payloads" / f"apply-{index}.bin"
        )
        if worktree["state"] == "absent":
            worktree["state"] = "deleted" if index_entry["tracked"] else "absent"
        entries.append({"path": relative, "index": index_entry, "worktree": worktree})
    payload: dict[str, Any] = {
        "schema_version": 1,
        "policy_sha256": policy_hash,
        "phase": "captured",
        "removed_paths": [],
        "entries": entries,
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
    repo: Path, journal_dir: Path, relative: str, snapshot: dict[str, Any]
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
    source = journal_dir / "payloads" / str(snapshot["payload"])
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != snapshot.get("sha256"):
        raise MigrationError(f"preservation payload hash mismatch: {relative}")
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


def capture(repo: Path, journal_dir: Path) -> dict[str, Any]:
    policy_paths, _, policy_hash = _load_policy(repo)
    if _query_tracked_ignored(repo) != policy_paths:
        raise MigrationError(
            "live tracked-ignore query differs from the exact 27-row baseline; no preservation journal was created"
        )
    return _create_journal(repo, journal_dir, policy_hash)


def apply(repo: Path, journal_dir: Path) -> dict[str, Any]:
    policy_paths, local_paths, policy_hash = _load_policy(repo)
    journal_path = journal_dir / MANIFEST_NAME
    if journal_path.exists():
        journal = _read_journal(journal_dir)
        if journal.get("phase") == "applied":
            return journal
        if journal.get("phase") not in {"captured", "applying"}:
            raise MigrationError(f"journal cannot resume apply from phase: {journal.get('phase')}")
        if journal.get("policy_sha256") != policy_hash:
            raise MigrationError("tracked-ignore policy changed after preservation capture")
    else:
        actual = _query_tracked_ignored(repo)
        if actual != policy_paths:
            raise MigrationError(
                "live tracked-ignore query differs from the exact 27-row baseline; no index mutation ran"
            )
        journal = _create_journal(repo, journal_dir, policy_hash)

    journal["phase"] = "applying"
    _write_journal(journal_dir, journal)
    removed = set(journal.get("removed_paths", []))
    actual = _query_tracked_ignored(repo)
    actual_removed = local_paths - actual
    pending_order = [path for path in LOCAL_ONLY_PATHS if path not in removed]
    allowed_interrupted = removed | ({pending_order[0]} if pending_order else set())
    allowed_removed_sets = {
        frozenset(removed),
        frozenset(allowed_interrupted),
        frozenset(local_paths),
    }
    if actual - policy_paths or frozenset(actual_removed) not in allowed_removed_sets:
        raise MigrationError("live tracked-ignore query drifted during apply; no broader mutation ran")
    if actual_removed == local_paths:
        removed = set(local_paths)
        journal["removed_paths"] = list(LOCAL_ONLY_PATHS)
        _write_journal(journal_dir, journal)
    elif actual_removed != removed:
        recovered = next(iter(actual_removed - removed))
        removed.add(recovered)
        journal["removed_paths"] = [path for path in LOCAL_ONLY_PATHS if path in removed]
        _write_journal(journal_dir, journal)

    for entry in journal["entries"]:
        relative = entry["path"]
        if relative in removed:
            continue
        result = _git(repo, "update-index", "--force-remove", "--", relative)
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise MigrationError(detail or f"could not untrack approved local-only path: {relative}")
        removed.add(relative)
        journal["removed_paths"] = [path for path in LOCAL_ONLY_PATHS if path in removed]
        _write_journal(journal_dir, journal)

    expected_after = policy_paths - local_paths
    if _query_tracked_ignored(repo) != expected_after:
        raise MigrationError("post-migration tracked-ignore query is not the exact approved 24-path set")
    final_snapshots = []
    for index, entry in enumerate(journal["entries"]):
        _restore_captured_if_missing(repo, journal_dir, entry["path"], entry["worktree"])
        final_snapshots.append(
            {
                "path": entry["path"],
                "worktree": _snapshot_worktree(
                    repo, entry["path"], journal_dir / "payloads" / f"applied-{index}.bin"
                ),
            }
        )
    journal["applied_worktree"] = final_snapshots
    journal["phase"] = "applied"
    _write_journal(journal_dir, journal)
    return journal


def _restore_index_entry(repo: Path, relative: str, index_entry: dict[str, Any]) -> None:
    if not index_entry.get("tracked"):
        return
    oid = str(index_entry["oid"])
    if set(oid) == {"0"}:
        result = _git(repo, "add", "--intent-to-add", "--", relative)
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


def rewind(repo: Path, journal_dir: Path) -> dict[str, Any]:
    policy_paths, local_paths, policy_hash = _load_policy(repo)
    journal = _read_journal(journal_dir)
    if journal.get("phase") == "rewound":
        return journal
    if journal.get("phase") not in {"applied", "rewinding"}:
        raise MigrationError(f"journal cannot rewind from phase: {journal.get('phase')}")
    if journal.get("policy_sha256") != policy_hash:
        raise MigrationError("tracked-ignore policy changed before rewind")
    actual = _query_tracked_ignored(repo)
    expected_after = policy_paths - local_paths
    restored = set(journal.get("restored_paths", []))
    if actual - policy_paths or (actual & local_paths) != restored or actual - local_paths != expected_after:
        raise MigrationError("live tracked-ignore query drifted before rewind; no index mutation ran")

    if journal.get("phase") == "applied":
        rewind_snapshots = []
        for index, relative in enumerate(LOCAL_ONLY_PATHS):
            rewind_snapshots.append(
                {
                    "path": relative,
                    "worktree": _snapshot_worktree(
                        repo, relative, journal_dir / "payloads" / f"rewind-{index}.bin"
                    ),
                }
            )
        journal["rewind_worktree"] = rewind_snapshots
        journal["restored_paths"] = []
        journal["phase"] = "rewinding"
        _write_journal(journal_dir, journal)

    restored = set(journal.get("restored_paths", []))
    by_path = {entry["path"]: entry for entry in journal["entries"]}
    for relative in LOCAL_ONLY_PATHS:
        if relative in restored:
            continue
        _restore_index_entry(repo, relative, by_path[relative]["index"])
        restored.add(relative)
        journal["restored_paths"] = [path for path in LOCAL_ONLY_PATHS if path in restored]
        _write_journal(journal_dir, journal)

    if _query_tracked_ignored(repo) != policy_paths:
        raise MigrationError("rewind did not restore the exact approved 27-path tracked-ignore set")
    for snapshot in journal["rewind_worktree"]:
        if not _same_worktree(snapshot["worktree"], _current_worktree(repo, snapshot["path"])):
            raise MigrationError(f"rewind changed the current local copy: {snapshot['path']}")
    journal["phase"] = "rewound"
    _write_journal(journal_dir, journal)
    return journal


def preview(repo: Path) -> dict[str, Any]:
    policy_paths, local_paths, _ = _load_policy(repo)
    actual = _query_tracked_ignored(repo)
    if actual == policy_paths:
        state = "ready-to-apply"
    elif actual == policy_paths - local_paths:
        state = "already-applied"
    else:
        state = "blocked-query-mismatch"
    return {"ok": state != "blocked-query-mismatch", "state": state, "actual_count": len(actual)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "capture", "apply", "rewind"))
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--journal", type=Path)
    args = parser.parse_args(argv)
    try:
        repo = args.repo.resolve()
        if args.action == "preview":
            result = preview(repo)
        else:
            if args.journal is None:
                raise MigrationError("--journal is required for capture, apply, and rewind")
            if args.action == "capture":
                result = capture(repo, args.journal.resolve())
            elif args.action == "apply":
                result = apply(repo, args.journal.resolve())
            else:
                result = rewind(repo, args.journal.resolve())
            result = {"ok": True, "phase": result["phase"], "paths": list(LOCAL_ONLY_PATHS)}
    except (MigrationError, OSError, ValueError, json.JSONDecodeError) as error:
        result = {"ok": False, "error": str(error)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
