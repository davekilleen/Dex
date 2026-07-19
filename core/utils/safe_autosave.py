"""Transactional, secret-aware staging for bridge update/rollback workflows."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.utils.integration_credentials import read_vault_env


@dataclass(frozen=True)
class AutosaveResult:
    staged: tuple[str, ...]
    refused_findings: int = 0


def _secret_findings(root: Path, candidates: tuple[str, ...], needles: tuple[bytes, ...]) -> int:
    findings = 0
    for relative in candidates:
        candidate = root / relative
        if candidate.is_file() and any(value in candidate.read_bytes() for value in needles):
            findings += 1
    return findings


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, env=env
    )
    if result.returncode:
        raise RuntimeError("safe autosave Git operation failed")
    return result.stdout


def autosave_candidates(root: Path) -> tuple[str, ...]:
    raw = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = raw.split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        if status[:1] in {b"R", b"C"}:
            if index >= len(entries):
                raise RuntimeError("malformed Git status")
            index += 1
        decoded = os.fsdecode(path)
        candidate = root / decoded
        if candidate.is_symlink():
            raise ValueError("safe autosave refuses symlink candidates")
        paths.append(decoded)
    return tuple(sorted(set(paths)))


def safe_stage(root: Path, credential_needles: tuple[bytes, ...]) -> AutosaveResult:
    candidates = autosave_candidates(root)
    if not candidates:
        return AutosaveResult(())
    findings = _secret_findings(root, candidates, credential_needles)
    if findings:
        return AutosaveResult((), findings)
    git_dir = Path(_git(root, "rev-parse", "--absolute-git-dir").decode().strip())
    index_path = Path(_git(root, "rev-parse", "--git-path", "index").decode().strip())
    if not index_path.is_absolute():
        index_path = root / index_path
    original = index_path.read_bytes() if index_path.exists() else None
    fd, temporary = tempfile.mkstemp(prefix="dex-index-", dir=git_dir)
    os.close(fd)
    temp_path = Path(temporary)
    try:
        if original is not None:
            temp_path.write_bytes(original)
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(temp_path)
        payload = b"\0".join(os.fsencode(path) for path in candidates) + b"\0"
        result = subprocess.run(
            ["git", "add", "--pathspec-from-file=-", "--pathspec-file-nul", "--"],
            cwd=root,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        if result.returncode:
            raise RuntimeError("safe autosave explicit staging failed")
        os.replace(temp_path, index_path)
        return AutosaveResult(candidates)
    except Exception:
        if original is None:
            index_path.unlink(missing_ok=True)
        else:
            index_path.write_bytes(original)
        raise
    finally:
        temp_path.unlink(missing_ok=True)


def safe_autosave_commit(root: Path, credential_needles: tuple[bytes, ...], message: str) -> AutosaveResult:
    """Commit explicit candidates through a temporary index; preserve the real index exactly."""
    candidates = autosave_candidates(root)
    if not candidates:
        return AutosaveResult(())
    findings = _secret_findings(root, candidates, credential_needles)
    if findings:
        return AutosaveResult((), findings)
    git_dir = Path(_git(root, "rev-parse", "--absolute-git-dir").decode().strip())
    index_path = Path(_git(root, "rev-parse", "--git-path", "index").decode().strip())
    if not index_path.is_absolute():
        index_path = root / index_path
    original = index_path.read_bytes() if index_path.exists() else None
    fd, temporary = tempfile.mkstemp(prefix="dex-index-", dir=git_dir)
    os.close(fd)
    temporary_index = Path(temporary)
    committed_successfully = False
    try:
        if original is not None:
            temporary_index.write_bytes(original)
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(temporary_index)
        payload = b"\0".join(os.fsencode(path) for path in candidates) + b"\0"
        staged = subprocess.run(
            ["git", "add", "--pathspec-from-file=-", "--pathspec-file-nul", "--"],
            cwd=root,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        if staged.returncode:
            raise RuntimeError("safe autosave explicit staging failed")
        changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=root, env=env).returncode
        if changed == 0:
            return AutosaveResult(())
        committed = subprocess.run(
            ["git", "commit", "-m", message], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
        )
        if committed.returncode:
            raise RuntimeError("safe autosave commit failed")
        if (index_path.read_bytes() if index_path.exists() else None) != original:
            raise RuntimeError("Git index changed during safe autosave")
        os.replace(temporary_index, index_path)
        committed_successfully = True
        return AutosaveResult(candidates)
    finally:
        temporary_index.unlink(missing_ok=True)
        current = index_path.read_bytes() if index_path.exists() else None
        if not committed_successfully and current != original:
            if original is None:
                index_path.unlink(missing_ok=True)
            else:
                index_path.write_bytes(original)


def main() -> int:
    root = Path.cwd()
    credentials = tuple(value.encode() for value in read_vault_env(root).values() if value)
    result = safe_autosave_commit(root, credentials, "Auto-save before Dex lifecycle operation")
    if result.refused_findings:
        print(f"Safe autosave refused: {result.refused_findings} opaque credential finding(s).")
        return 2
    print(f"Safely autosaved {len(result.staged)} explicit candidate(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
