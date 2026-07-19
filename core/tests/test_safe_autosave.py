import subprocess
from pathlib import Path

import pytest

from core.utils.safe_autosave import main, safe_autosave_commit, safe_stage


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def _repo(tmp_path: Path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "synthetic@example.invalid")
    _git(tmp_path, "config", "user.name", "Synthetic")
    (tmp_path / "kept.txt").write_text("before\n")
    _git(tmp_path, "add", "kept.txt")
    _git(tmp_path, "commit", "-qm", "fixture")


def test_safe_stage_uses_explicit_candidates_and_preserves_existing_index(tmp_path):
    _repo(tmp_path)
    (tmp_path / "kept.txt").write_text("already staged\n")
    _git(tmp_path, "add", "kept.txt")
    (tmp_path / "new file.txt").write_text("safe\n")
    result = safe_stage(tmp_path, (b"synthetic-secret",))
    assert result.staged == ("kept.txt", "new file.txt")
    names = _git(tmp_path, "diff", "--cached", "--name-only", "-z").split(b"\0")
    assert b"kept.txt" in names and b"new file.txt" in names


def test_secret_preflight_refuses_without_changing_index(tmp_path):
    _repo(tmp_path)
    before = _git(tmp_path, "write-tree")
    (tmp_path / "leak.txt").write_text("synthetic-secret\n")
    result = safe_stage(tmp_path, (b"synthetic-secret",))
    assert result.refused_findings
    assert _git(tmp_path, "write-tree") == before


def test_symlink_candidate_is_refused(tmp_path):
    _repo(tmp_path)
    (tmp_path / "link").symlink_to("kept.txt")
    with pytest.raises(ValueError, match="symlink"):
        safe_stage(tmp_path, (b"synthetic-secret",))


def test_safe_autosave_commit_uses_temporary_index_and_finishes_clean(tmp_path):
    _repo(tmp_path)
    (tmp_path / "new.txt").write_text("safe\n")
    result = safe_autosave_commit(tmp_path, (b"synthetic-secret",), "synthetic autosave")
    assert result.staged == ("new.txt",)
    assert _git(tmp_path, "show", "HEAD:new.txt") == b"safe\n"
    assert _git(tmp_path, "diff", "--cached", "--name-only") == b""


def test_cli_without_configured_credentials_does_not_invent_a_scan_needle(tmp_path, monkeypatch):
    _repo(tmp_path)
    (tmp_path / "new.txt").write_text("__DEX_NO_CONFIGURED_CREDENTIAL__\n")
    monkeypatch.chdir(tmp_path)
    assert main() == 0
    assert _git(tmp_path, "show", "HEAD:new.txt") == b"__DEX_NO_CONFIGURED_CREDENTIAL__\n"


def test_safe_autosave_commit_failure_restores_exact_index(tmp_path, monkeypatch):
    _repo(tmp_path)
    (tmp_path / "kept.txt").write_text("staged before failure\n")
    _git(tmp_path, "add", "kept.txt")
    (tmp_path / "new.txt").write_text("safe\n")
    index = Path(_git(tmp_path, "rev-parse", "--git-path", "index").decode().strip())
    if not index.is_absolute():
        index = tmp_path / index
    before = index.read_bytes()
    real_run = subprocess.run

    def fail_commit(command, **kwargs):
        if command[:2] == ["git", "commit"]:
            return subprocess.CompletedProcess(command, 1, b"", b"synthetic failure")
        return real_run(command, **kwargs)

    monkeypatch.setattr("core.utils.safe_autosave.subprocess.run", fail_commit)
    with pytest.raises(RuntimeError, match="commit failed"):
        safe_autosave_commit(tmp_path, (b"synthetic-secret",), "synthetic autosave")
    assert index.read_bytes() == before
