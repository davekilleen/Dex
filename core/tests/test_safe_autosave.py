import json
import subprocess
from pathlib import Path

import pytest

from core.utils.safe_autosave import main, safe_autosave_commit


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def _repo(tmp_path: Path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "synthetic@example.invalid")
    _git(tmp_path, "config", "user.name", "Synthetic")
    (tmp_path / "kept.txt").write_text("before\n")
    _git(tmp_path, "add", "kept.txt")
    _git(tmp_path, "commit", "-qm", "fixture")


def test_autosave_uses_explicit_candidates_and_commits_existing_index(tmp_path):
    _repo(tmp_path)
    (tmp_path / "kept.txt").write_text("already staged\n")
    _git(tmp_path, "add", "kept.txt")
    (tmp_path / "new file.txt").write_text("safe\n")
    result = safe_autosave_commit(tmp_path, (b"synthetic-secret",), "autosave")
    assert result.staged == ("kept.txt", "new file.txt")
    assert _git(tmp_path, "show", "HEAD:new file.txt") == b"safe\n"


def test_secret_preflight_refuses_without_changing_index(tmp_path):
    _repo(tmp_path)
    before = _git(tmp_path, "write-tree")
    (tmp_path / "leak.txt").write_text("synthetic-secret\n")
    result = safe_autosave_commit(tmp_path, (b"synthetic-secret",), "autosave")
    assert result.refused_findings
    assert _git(tmp_path, "write-tree") == before


def test_symlink_candidate_is_refused(tmp_path):
    _repo(tmp_path)
    (tmp_path / "link").symlink_to("kept.txt")
    with pytest.raises(ValueError, match="symlink"):
        safe_autosave_commit(tmp_path, (b"synthetic-secret",), "autosave")


@pytest.mark.parametrize("env_present", [False, True])
def test_raw_legacy_yaml_is_refused_before_migration(tmp_path, env_present):
    _repo(tmp_path)
    if env_present:
        (tmp_path / ".env").write_text("TODOIST_API_KEY=known-value\n")
    config = tmp_path / "System/integrations/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("todoist:\n  api_key: legacy-value\n")
    result = safe_autosave_commit(tmp_path, (), "autosave")
    assert result.refused_findings
    assert b"System/integrations/config.yaml" not in _git(tmp_path, "ls-tree", "-r", "--name-only", "HEAD")


def test_final_temporary_index_catches_staged_only_blob_and_index_worktree_divergence(tmp_path):
    _repo(tmp_path)
    config = tmp_path / "System/integrations/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("todoist:\n  api_key: staged-only-secret\n")
    _git(tmp_path, "add", "System/integrations/config.yaml")
    config.write_text("todoist:\n  api_key_env_var: TODOIST_API_KEY\n")
    (tmp_path / "other.txt").write_text("safe\n")
    assert safe_autosave_commit(tmp_path, (), "autosave").refused_findings


def test_active_mcp_residual_refuses_without_staging_ignored_authorities(tmp_path):
    _repo(tmp_path)
    (tmp_path / ".gitignore").write_text(".env\n.mcp.json\nSystem/.dex/\n")
    _git(tmp_path, "add", ".gitignore")
    _git(tmp_path, "commit", "-qm", "ignore authorities")
    (tmp_path / ".mcp.json").write_text('{"env":{"TODOIST_API_KEY":"active-old-value"}}')
    (tmp_path / ".env").write_text("TODOIST_API_KEY=active-old-value\n")
    (tmp_path / "safe.txt").write_text("safe\n")
    result = safe_autosave_commit(tmp_path, (), "autosave")
    assert result.refused_findings
    assert b".mcp.json" not in _git(tmp_path, "ls-files")
    assert b".env" not in _git(tmp_path, "ls-files")


def test_migration_journal_preimage_is_ephemeral_secret_authority(tmp_path):
    _repo(tmp_path)
    journal_root = tmp_path / "System/.dex/adoption/credential-journals"
    journal_root.mkdir(parents=True)
    journal = {
        "config": {"bytes_hex": b"todoist:\n  api_key: journal-old-value\n".hex()},
        "env": None,
    }
    (journal_root / "opaque.json").write_text(json.dumps(journal))
    (tmp_path / "leak.txt").write_text("journal-old-value\n")
    result = safe_autosave_commit(tmp_path, (), "autosave")
    assert result.refused_findings
    assert b"leak.txt" not in _git(tmp_path, "ls-tree", "-r", "--name-only", "HEAD")


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
