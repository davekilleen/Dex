from pathlib import Path

import pytest

from core.utils.integration_credentials import (
    mcp_credential_key_names,
    parse_env_assignments,
    read_vault_env,
    resolve_service_credentials,
    update_vault_env,
)


def test_env_is_only_authority_and_process_environment_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("TODOIST_API_KEY", "ambient-must-not-win")
    (tmp_path / ".mcp.json").write_text('{"env":{"TODOIST_API_KEY":"mcp-must-not-win"}}')
    (tmp_path / ".env").write_text("TODOIST_API_KEY=synthetic-local-value\n")
    (tmp_path / ".env").chmod(0o600)
    settings = {"api_key_env_var": "TODOIST_API_KEY", "api_key": "tracked-must-not-win"}
    assert resolve_service_credentials("todoist", settings, tmp_path) == {"api_key": "synthetic-local-value"}


def test_missing_env_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("TODOIST_API_KEY", "ambient")
    with pytest.raises(ValueError, match="does not define"):
        resolve_service_credentials("todoist", {"api_key_env_var": "TODOIST_API_KEY"}, tmp_path)


def test_update_preserves_comments_crlf_and_is_restrictive(tmp_path):
    path = tmp_path / ".env"
    path.write_bytes(b"# keep\r\nOTHER=value\r\nTODOIST_API_KEY=old\r\n")
    path.chmod(0o600)
    update_vault_env(tmp_path, {"TODOIST_API_KEY": "synthetic-new", "TRELLO_TOKEN": "synthetic-token"})
    assert (
        path.read_bytes()
        == b'# keep\r\nOTHER=value\r\nTODOIST_API_KEY="synthetic-new"\r\nTRELLO_TOKEN="synthetic-token"\r\n'
    )
    assert path.stat().st_mode & 0o777 == 0o600
    assert read_vault_env(tmp_path)["OTHER"] == "value"


def test_duplicate_env_name_is_refused(tmp_path):
    (tmp_path / ".env").write_text("TODOIST_API_KEY=one\nTODOIST_API_KEY=two\n")
    (tmp_path / ".env").chmod(0o600)
    with pytest.raises(ValueError, match="duplicate"):
        read_vault_env(tmp_path)


def test_update_rejects_duplicate_assignments_before_mutation(tmp_path):
    path = tmp_path / ".env"
    original = b"TODOIST_API_KEY=one\nTODOIST_API_KEY=two\n"
    path.write_bytes(original)
    path.chmod(0o600)
    with pytest.raises(ValueError, match="duplicate"):
        update_vault_env(tmp_path, {"TODOIST_API_KEY": "replacement"})
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "value",
    [" leading", "trailing ", '"matching quotes"', r"back\\slash", "hash#value", "equals=value"],
)
def test_lossless_dotenv_round_trip_for_every_accepted_scalar(tmp_path, value):
    path = tmp_path / ".env"
    update_vault_env(tmp_path, {"TODOIST_API_KEY": value})
    assert read_vault_env(tmp_path)["TODOIST_API_KEY"] == value
    assert parse_env_assignments(path.read_bytes())["TODOIST_API_KEY"] == value


@pytest.mark.parametrize("mode", [0o640, 0o644])
def test_runtime_rejects_non_owner_only_env_permissions(tmp_path, mode):
    path = tmp_path / ".env"
    path.write_text("TODOIST_API_KEY=value\n")
    path.chmod(mode)
    with pytest.raises(ValueError, match="0600"):
        read_vault_env(tmp_path)


def test_runtime_accepts_owner_only_env_permissions(tmp_path):
    path = tmp_path / ".env"
    path.write_text("TODOIST_API_KEY=value\n")
    path.chmod(0o600)
    assert read_vault_env(tmp_path) == {"TODOIST_API_KEY": "value"}


def test_runtime_rejects_wrong_env_owner_where_supported(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("TODOIST_API_KEY=value\n")
    path.chmod(0o600)
    monkeypatch.setattr("core.utils.integration_credentials.os.getuid", lambda: path.stat().st_uid + 1)
    with pytest.raises(ValueError, match="owned"):
        read_vault_env(tmp_path)


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_runtime_rejects_linked_env_authority(tmp_path, link_kind):
    source = tmp_path / "source"
    source.write_text("TODOIST_API_KEY=value\n")
    source.chmod(0o600)
    env = tmp_path / ".env"
    if link_kind == "symlink":
        env.symlink_to(source)
    else:
        env.hardlink_to(source)
    with pytest.raises((OSError, ValueError)):
        read_vault_env(tmp_path)


@pytest.mark.parametrize(
    "malformed",
    [
        b"todoist:\n  api_key_env_var: [unbalanced\n : : :\n",  # ParserError
        b"todoist:\n\tapi_key_env_var: TABS\n",                  # ScannerError (tab indent)
        b'todoist:\n  api_key_env_var: "unterminated\n',          # ScannerError
    ],
)
def test_mcp_credential_key_names_survives_malformed_yaml(malformed):
    """A syntactically-broken config.yaml raises yaml.YAMLError (a ParserError/ScannerError,
    NOT a ValueError) from load_yaml_bytes. mcp_credential_key_names must fail safe to the
    canonical name set rather than let the parser error crash the residual path."""
    names = mcp_credential_key_names(malformed)
    assert {"TODOIST_API_KEY", "TRELLO_API_KEY", "TRELLO_TOKEN", "api_key", "token"} <= names
    # No configured-custom name could be extracted from unparseable YAML.
    assert names == frozenset({"TODOIST_API_KEY", "TRELLO_API_KEY", "TRELLO_TOKEN", "api_key", "token"})
