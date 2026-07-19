"""Transactional, secret-aware autosave through the exact final temporary index."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.utils.integration_credentials import inspect_active_mcp_config, read_vault_env

LEGACY_YAML_FIELD = re.compile(rb"(?m)^\s*(?:api_key|token)\s*:\s*\S+")
LEGACY_SECTION = re.compile(rb"(?ms)^\s*(?:todoist|trello)\s*:\s*\n(?:[ \t]+.*\n?)*")
RAW_MCP_FIELD = re.compile(rb'"(?:TODOIST_API_KEY|TRELLO_API_KEY|TRELLO_TOKEN|api_key|token)"\s*:\s*"(?!\$|\{|<)[^"]+"')


@dataclass(frozen=True)
class AutosaveResult:
    staged: tuple[str, ...]
    refused_findings: int = 0


def _git(root: Path, *args: str, env: dict[str, str] | None = None, input_data: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=root, input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    )
    if result.returncode:
        raise RuntimeError("safe autosave Git operation failed")
    return result.stdout


def autosave_candidates(root: Path) -> tuple[str, ...]:
    entries = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").split(b"\0")
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
        if (root / decoded).is_symlink():
            raise ValueError("safe autosave refuses symlink candidates")
        paths.append(decoded)
    return tuple(sorted(set(paths)))


def _paths_to_stage(root: Path) -> tuple[str, ...]:
    paths = []
    for entry in _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").split(b"\0"):
        if not entry or entry[:1] in {b"R", b"C"}:
            continue
        if entry[:2] == b"??" or (entry[:1] == b" " and entry[1:2] != b" "):
            paths.append(os.fsdecode(entry[3:]))
    return tuple(sorted(set(paths)))


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
    elif mcp.data and RAW_MCP_FIELD.search(mcp.data):
        findings += 1
    if mcp.data and any(value in mcp.data for value in values):
        findings += 1
    return tuple(values), findings


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
    """Stage explicit candidates, inspect exact final blobs, commit, and preserve the real index."""
    candidates = autosave_candidates(root)
    if not candidates:
        return AutosaveResult(())
    git_dir = Path(_git(root, "rev-parse", "--absolute-git-dir").decode().strip())
    index_path = Path(_git(root, "rev-parse", "--git-path", "index").decode().strip())
    if not index_path.is_absolute():
        index_path = root / index_path
    original = index_path.read_bytes() if index_path.exists() else None
    descriptor, temporary = tempfile.mkstemp(prefix="dex-index-", dir=git_dir)
    os.close(descriptor)
    temporary_index = Path(temporary)
    committed_successfully = False
    try:
        if original is not None:
            temporary_index.write_bytes(original)
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(temporary_index)
        stage_paths = _paths_to_stage(root)
        if stage_paths:
            payload = b"\0".join(os.fsencode(path) for path in stage_paths) + b"\0"
            _git(root, "add", "--pathspec-from-file=-", "--pathspec-file-nul", "--", env=env, input_data=payload)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=root, env=env).returncode == 0:
            return AutosaveResult(())
        needles, authority_findings = _authority_needles(root, credential_needles)
        findings = authority_findings + _final_index_findings(root, env, needles)
        if findings:
            return AutosaveResult((), findings)
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
    result = safe_autosave_commit(Path.cwd(), (), "Auto-save before Dex lifecycle operation")
    if result.refused_findings:
        print(f"Safe autosave refused: {result.refused_findings} opaque credential finding(s).")
        return 2
    print(f"Safely autosaved {len(result.staged)} explicit candidate(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
