from pathlib import Path

import pytest

from core.utils.integration_credentials import read_vault_env, resolve_service_credentials, update_vault_env


def test_env_is_only_authority_and_process_environment_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("TODOIST_API_KEY", "ambient-must-not-win")
    (tmp_path / ".mcp.json").write_text('{"env":{"TODOIST_API_KEY":"mcp-must-not-win"}}')
    (tmp_path / ".env").write_text("TODOIST_API_KEY=synthetic-local-value\n")
    settings = {"api_key_env_var": "TODOIST_API_KEY", "api_key": "tracked-must-not-win"}
    assert resolve_service_credentials("todoist", settings, tmp_path) == {"api_key": "synthetic-local-value"}


def test_missing_env_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("TODOIST_API_KEY", "ambient")
    with pytest.raises(ValueError, match="does not define"):
        resolve_service_credentials("todoist", {"api_key_env_var": "TODOIST_API_KEY"}, tmp_path)


def test_update_preserves_comments_crlf_and_is_restrictive(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"# keep\r\nOTHER=value\r\nTODOIST_API_KEY=old\r\n")
    update_vault_env(tmp_path, {"TODOIST_API_KEY": "synthetic-new", "TRELLO_TOKEN": "synthetic-token"})
    assert (
        path.read_bytes()
        == b"# keep\r\nOTHER=value\r\nTODOIST_API_KEY=synthetic-new\r\nTRELLO_TOKEN=synthetic-token\r\n"
    )
    assert path.stat().st_mode & 0o777 == 0o600
    assert read_vault_env(tmp_path)["OTHER"] == "value"


def test_duplicate_env_name_is_refused(tmp_path):
    (tmp_path / ".env").write_text("TODOIST_API_KEY=one\nTODOIST_API_KEY=two\n")
    with pytest.raises(ValueError, match="duplicate"):
        read_vault_env(tmp_path)


def test_update_rejects_duplicate_assignments_before_mutation(tmp_path):
    path = tmp_path / ".env"
    original = b"TODOIST_API_KEY=one\nTODOIST_API_KEY=two\n"
    path.write_bytes(original)
    with pytest.raises(ValueError, match="duplicate"):
        update_vault_env(tmp_path, {"TODOIST_API_KEY": "replacement"})
    assert path.read_bytes() == original
