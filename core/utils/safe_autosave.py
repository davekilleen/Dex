"""Transactional, secret-aware autosave through the exact final temporary index."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.utils.integration_credentials import (
    MAX_ACTIVE_CONFIG_BYTES,
    active_mcp_raw_residual,
    inspect_active_mcp_config,
    mcp_credential_key_names,
    read_vault_env,
)
from core.utils.local_git import git_env, git_result

LEGACY_YAML_FIELD = re.compile(rb"(?m)^\s*(?:api_key|token)\s*:\s*\S+")
LEGACY_SECTION = re.compile(rb"(?ms)^\s*(?:todoist|trello)\s*:\s*\n(?:[ \t]+.*\n?)*")
EXECUTABLE_CONFIG = re.compile(
    rb"(?i)^(?:filter\.|include(?:if)?\.|extensions\.worktreeconfig$|"
    rb"core\.(?:attributesfile|hookspath|fsmonitor|sshcommand|worktree)|"
    rb"commit\.gpgsign$|tag\.gpgsign$|gpg\.|user\.signingkey$|diff\..*\.(?:command|textconv)$|"
    rb"merge\..*\.driver$)"
)
LOCAL_AUTHORITY_PATHS = frozenset({b".env", b".mcp.json"})
LOCAL_AUTHORITY_PREFIXES = (b"System/.dex/adoption/credential-journals/",)


@dataclass(frozen=True)
class AutosaveResult:
    staged: tuple[str, ...]
    refused_findings: int = 0


AUTOSAVE_JOURNAL = "dex-autosave-recovery.json"
AUTOSAVE_INDEX_BACKUP = "dex-autosave-index.backup"


def _digest(data: bytes | None) -> str:
    return hashlib.sha256(data if data is not None else b"<absent>").hexdigest()


def _write_durable(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _read_recovery_artifact(path: Path, *, max_bytes: int) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_size > max_bytes
    ):
        raise RuntimeError("safe autosave recovery-required: unsafe recovery artifact")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = path.lstat()
    identities = {
        (item.st_dev, item.st_ino, item.st_mode, item.st_nlink, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        for item in (before, opened, after, current)
    }
    if len(identities) != 1 or len(data) != opened.st_size or len(data) > max_bytes:
        raise RuntimeError("safe autosave recovery-required: recovery artifact changed")
    return data


def _recover_pending_autosave(root: Path, git_dir: Path, index_path: Path) -> None:
    """Deterministically restore an interrupted ref/index publication."""
    journal = git_dir / AUTOSAVE_JOURNAL
    backup = git_dir / AUTOSAVE_INDEX_BACKUP
    if not journal.exists():
        if backup.exists():
            metadata = backup.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise RuntimeError("safe autosave recovery-required: unsafe orphaned index backup")
            backup.unlink()
        return
    try:
        record = json.loads(_read_recovery_artifact(journal, max_bytes=64 * 1024).decode("utf-8"))
        original_index = _read_recovery_artifact(backup, max_bytes=64 * 1024 * 1024)
        if _digest(original_index) != record["original_index_sha256"]:
            raise RuntimeError("safe autosave recovery-required: corrupt index backup")
        current_head = _git(root, "rev-parse", "--verify", "HEAD").decode().strip()
        if current_head == record["target_head"]:
            update = _git_result(
                root,
                "update-ref",
                "HEAD",
                record["original_head"],
                record["target_head"],
            )
            if update.returncode:
                raise RuntimeError("safe autosave recovery-required: HEAD recovery conflict")
        elif current_head != record["original_head"]:
            raise RuntimeError("safe autosave recovery-required: HEAD changed independently")
        current_index = index_path.read_bytes() if index_path.exists() else None
        if _digest(current_index) not in {record["original_index_sha256"], record["target_index_sha256"]}:
            raise RuntimeError("safe autosave recovery-required: index changed independently")
        descriptor, temporary = tempfile.mkstemp(prefix="dex-index-recover-", dir=index_path.parent)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(original_index)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, index_path)
        backup.unlink()
        journal.unlink()
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("safe autosave recovery-required: invalid recovery journal") from error


def _git_env(index_path: Path | None = None) -> dict[str, str]:
    return git_env(index_path=index_path)


def _git_result(
    root: Path,
    *args: str,
    env: dict[str, str] | None = None,
    input_data: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    index_path = Path(env["GIT_INDEX_FILE"]) if env and env.get("GIT_INDEX_FILE") else None
    return git_result(root, *args, profile="mutation", index_path=index_path, input_data=input_data)


def _git(root: Path, *args: str, env: dict[str, str] | None = None, input_data: bytes | None = None) -> bytes:
    result = _git_result(root, *args, env=env, input_data=input_data)
    if result.returncode:
        raise RuntimeError("safe autosave Git operation failed")
    return result.stdout


def _reject_executable_git_config(root: Path) -> None:
    entries = _git(root, "config", "--local", "--no-includes", "--null", "--list").split(b"\0")
    parsed = [entry.partition(b"\n") for entry in entries if entry]
    if any(EXECUTABLE_CONFIG.search(name) for name, _, _ in parsed) or any(
        name.lower() == b"core.bare" and value.lower() not in {b"false", b"no", b"off", b"0"}
        for name, _, value in parsed
    ):
        raise RuntimeError("safe autosave refuses executable local Git configuration")


def _autosave_paths(root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    entries = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").split(b"\0")
    candidates: list[str] = []
    stage_paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2:3] != b" ":
            raise RuntimeError("malformed Git status")
        status, path = entry[:2], entry[3:]
        related_path = None
        if status[:1] in {b"R", b"C"} or status[1:2] in {b"R", b"C"}:
            if index >= len(entries):
                raise RuntimeError("malformed Git status")
            related_path = entries[index]
            index += 1
        decoded = os.fsdecode(path)
        if (root / decoded).is_symlink():
            raise ValueError("safe autosave refuses symlink candidates")
        candidates.append(decoded)
        if status == b"??" or (status[:1] == b" " and status[1:2] != b" "):
            stage_paths.append(decoded)
            if related_path:
                related = os.fsdecode(related_path)
                if (root / related).is_symlink():
                    raise ValueError("safe autosave refuses symlink candidates")
                stage_paths.append(related)
    return tuple(sorted(set(candidates))), tuple(sorted(set(stage_paths)))


def _authority_needles(root: Path, configured: tuple[bytes, ...]) -> tuple[tuple[bytes, ...], int]:
    values = {value for value in configured if value}
    findings = 0
    try:
        values.update(value.encode() for value in read_vault_env(root).values() if value)
    except (OSError, UnicodeDecodeError, ValueError):
        findings += 1
    journal_root = root / "System/.dex/adoption/credential-journals"
    if journal_root.exists():
        if journal_root.is_symlink() or not journal_root.is_dir():
            findings += 1
        else:
            for journal in journal_root.glob("*.json"):
                try:
                    metadata = journal.lstat()
                    if (
                        not stat.S_ISREG(metadata.st_mode)
                        or metadata.st_nlink != 1
                        or metadata.st_size > 8 * 1024 * 1024
                    ):
                        raise OSError("unsafe journal")
                    descriptor = os.open(journal, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    try:
                        raw_journal = os.read(descriptor, 8 * 1024 * 1024 + 1)
                    finally:
                        os.close(descriptor)
                    if len(raw_journal) != metadata.st_size:
                        raise OSError("journal identity changed")
                    payload = json.loads(raw_journal.decode("utf-8"))
                    for entry in (payload.get("config"), payload.get("env")):
                        if isinstance(entry, dict) and isinstance(entry.get("bytes_hex"), str):
                            raw = bytes.fromhex(entry["bytes_hex"])
                            for match in re.finditer(
                                rb"(?m)^\s*(?:api_key|token|[A-Z][A-Z0-9_]*)\s*[=:]\s*([^\r\n]+)", raw
                            ):
                                value = match.group(1).strip(b" '\"")
                                if value:
                                    values.add(value)
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    findings += 1
    mcp = inspect_active_mcp_config(root)
    if not mcp.inspected:
        findings += 1
    elif mcp.data:
        key_names = mcp_credential_key_names(_read_optional_config_bytes(root))
        try:
            if active_mcp_raw_residual(mcp.data, key_names):
                findings += 1
        except ValueError:
            findings += 1  # unparseable active .mcp.json → fail closed, refuse autosave
    if mcp.data and any(value in mcp.data for value in values):
        findings += 1
    return tuple(values), findings


def _read_optional_config_bytes(root: Path) -> bytes | None:
    """Best-effort read of the integration config so the raw-residual key-name set can
    include configured custom env-var names. Fails safe: any unsafe/unreadable file
    yields None, and the residual detector falls back to the canonical key-name set."""
    path = root / "System/integrations/config.yaml"
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size > MAX_ACTIVE_CONFIG_BYTES
        ):
            return None
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            return os.read(descriptor, MAX_ACTIVE_CONFIG_BYTES + 1)
        finally:
            os.close(descriptor)
    except OSError:
        return None


def _final_index_findings(root: Path, env: dict[str, str], needles: tuple[bytes, ...]) -> int:
    findings = 0
    for entry in _git(root, "ls-files", "-s", "-z", env=env).split(b"\0"):
        if not entry:
            continue
        metadata, _, relative = entry.partition(b"\t")
        fields = metadata.split()
        if len(fields) != 3 or fields[2] != b"0":
            findings += 1
            continue
        if relative in LOCAL_AUTHORITY_PATHS or relative.startswith(LOCAL_AUTHORITY_PREFIXES):
            findings += 1
            continue
        data = _git(root, "cat-file", "blob", fields[1].decode("ascii"), env=env)
        if any(value in data for value in needles):
            findings += 1
            continue
        if relative.endswith((b".yaml", b".yml")) and any(
            LEGACY_YAML_FIELD.search(section) for section in LEGACY_SECTION.findall(data)
        ):
            findings += 1
    return findings


def safe_autosave_commit(root: Path, credential_needles: tuple[bytes, ...], message: str) -> AutosaveResult:
    """Stage explicit candidates and publish ref/index through recoverable CAS."""
    _reject_executable_git_config(root)
    git_dir = Path(_git(root, "rev-parse", "--absolute-git-dir").decode().strip())
    index_path = Path(_git(root, "rev-parse", "--git-path", "index").decode().strip())
    if not index_path.is_absolute():
        index_path = root / index_path
    _recover_pending_autosave(root, git_dir, index_path)
    candidates, stage_paths = _autosave_paths(root)
    if not candidates:
        return AutosaveResult(())
    original = index_path.read_bytes() if index_path.exists() else None
    descriptor, temporary = tempfile.mkstemp(prefix="dex-index-", dir=git_dir)
    os.close(descriptor)
    temporary_index = Path(temporary)
    publication_complete = False
    journal = git_dir / AUTOSAVE_JOURNAL
    backup = git_dir / AUTOSAVE_INDEX_BACKUP
    try:
        if original is not None:
            temporary_index.write_bytes(original)
        env = _git_env(temporary_index)
        if stage_paths:
            payload = b"\0".join(os.fsencode(path) for path in stage_paths) + b"\0"
            _git(root, "add", "--pathspec-from-file=-", "--pathspec-file-nul", "--", env=env, input_data=payload)
        if _git_result(root, "diff", "--cached", "--quiet", env=env).returncode == 0:
            return AutosaveResult(())
        needles, authority_findings = _authority_needles(root, credential_needles)
        findings = authority_findings + _final_index_findings(root, env, needles)
        if findings:
            return AutosaveResult((), findings)
        tree = _git(root, "write-tree", env=env).decode().strip()
        original_head = _git(root, "rev-parse", "--verify", "HEAD").decode().strip()
        committed = _git_result(
            root,
            "commit-tree",
            tree,
            "-p",
            original_head,
            env=env,
            input_data=(message + "\n").encode(),
        )
        if committed.returncode:
            raise RuntimeError("safe autosave commit-object creation failed")
        target_head = committed.stdout.decode().strip()
        if (index_path.read_bytes() if index_path.exists() else None) != original:
            raise RuntimeError("Git index changed during safe autosave")
        target_index = temporary_index.read_bytes()
        if original is None:
            raise RuntimeError("safe autosave requires an existing real index")
        _write_durable(backup, original)
        record = {
            "schema_version": 1,
            "original_head": original_head,
            "target_head": target_head,
            "original_index_sha256": _digest(original),
            "target_index_sha256": _digest(target_index),
        }
        _write_durable(journal, (json.dumps(record, sort_keys=True) + "\n").encode())
        published = _git_result(root, "update-ref", "HEAD", target_head, original_head)
        if published.returncode:
            raise RuntimeError("safe autosave HEAD compare-and-swap failed")
        os.replace(temporary_index, index_path)
        if _digest(index_path.read_bytes()) != record["target_index_sha256"]:
            raise RuntimeError("safe autosave index publication readback failed")
        backup.unlink()
        journal.unlink()
        publication_complete = True
        return AutosaveResult(candidates)
    except BaseException:
        if journal.exists():
            _recover_pending_autosave(root, git_dir, index_path)
        elif backup.exists():
            backup.unlink()
        raise
    finally:
        temporary_index.unlink(missing_ok=True)
        current = index_path.read_bytes() if index_path.exists() else None
        if not publication_complete and not journal.exists() and current != original:
            if original is None:
                index_path.unlink(missing_ok=True)
            else:
                index_path.write_bytes(original)


def main() -> int:
    result = safe_autosave_commit(Path.cwd(), (), "Auto-save before Dex lifecycle operation")
    if result.refused_findings:
        print(f"Safe autosave refused: {result.refused_findings} opaque credential finding(s).")
        return 2
    print(f"Safely autosaved {len(result.staged)} explicit candidate(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
