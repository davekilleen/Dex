"""Windows fail-closed contained writes; POSIX behaviour must stay unchanged."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path, PureWindowsPath

import pytest

from core.utils import credential_remediation, integration_credentials, trust_registry
from core.utils.trust_registry import TrustRegistryError, normalize_vault_relative


def _directory_fd(path: Path) -> int:
    return os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))


def test_contained_nofollow_is_available_on_posix():
    assert os.name != "nt"
    assert hasattr(os, "O_NOFOLLOW")
    assert credential_remediation._contained_nofollow_available()
    assert trust_registry._contained_nofollow_available()


def test_posix_atomic_replace_bytes_and_mode_unchanged(tmp_path):
    payload = b"todoist:\n  api_key_env_var: TODOIST_API_KEY\n"
    directory = _directory_fd(tmp_path)
    try:
        credential_remediation._atomic_replace_at(directory, "config.yaml", payload, 0o600)
    finally:
        os.close(directory)

    written = tmp_path / "config.yaml"
    assert written.read_bytes() == payload
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert not hasattr(os, "O_BINARY") or not (os.O_WRONLY | os.O_CREAT | os.O_EXCL) & os.O_BINARY


def test_posix_require_contained_nofollow_is_noop():
    credential_remediation._require_contained_nofollow("posix no-op")
    credential_remediation._require_contained_nofollow("posix write no-op", require_fchmod=True)
    trust_registry._require_contained_nofollow("posix no-op")


def test_windows_name_refuses_credential_write_without_creating_file(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=credential_remediation.logger.name)
    monkeypatch.setattr(os, "name", "nt")
    secret = b"TODOIST_API_KEY=synthetic-old-key-must-not-be-written\n"
    directory = _directory_fd(tmp_path)
    try:
        with pytest.raises(OSError, match="no-follow descriptor-relative writes are unavailable"):
            credential_remediation._atomic_replace_at(directory, ".env", secret, 0o600)
    finally:
        os.close(directory)

    assert not (tmp_path / ".env").exists()
    assert "refused" in caplog.text
    assert "os.name=nt" in caplog.text
    assert "synthetic-old-key-must-not-be-written" not in caplog.text


def test_missing_nofollow_refuses_directory_chain(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=credential_remediation.logger.name)
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    with pytest.raises(OSError, match="no-follow descriptor-relative writes are unavailable"):
        credential_remediation._open_directory_chain(tmp_path, ())
    assert "O_NOFOLLOW=False" in caplog.text
    assert list(tmp_path.iterdir()) == []


def test_windows_name_refuses_trust_registry_open(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=trust_registry.logger.name)
    monkeypatch.setattr(os, "name", "nt")
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "trusted-mcps.yaml").write_text("trusted_mcps: {}\n")
    with pytest.raises(TrustRegistryError, match="safe no-follow file operations are unavailable"):
        trust_registry._open_component_file(vault, Path("System/trusted-mcps.yaml"), label="registry")
    assert "os.name=nt" in caplog.text
    assert "trusted_mcps" not in caplog.text


def test_windows_name_refuses_env_authority(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=integration_credentials.logger.name)
    monkeypatch.setattr(os, "name", "nt")
    (tmp_path / ".env").write_bytes(b"TODOIST_API_KEY=synthetic-old-key\n")
    (tmp_path / ".env").chmod(0o600)
    with pytest.raises(OSError, match="descriptor-relative no-follow .env authority is unavailable"):
        integration_credentials.update_vault_env(tmp_path, {"TODOIST_API_KEY": "replacement"})
    assert (tmp_path / ".env").read_bytes() == b"TODOIST_API_KEY=synthetic-old-key\n"
    assert "os.name=nt" in caplog.text
    assert "synthetic-old-key" not in caplog.text
    assert "replacement" not in caplog.text


def test_trust_registry_still_rejects_simulated_windows_paths():
    windows_relative = str(PureWindowsPath("System") / "trusted-mcps.yaml")
    windows_absolute = str(PureWindowsPath("C:/Users/Joe/Dex/custom-mcp/server.py"))
    assert "\\" in windows_relative
    with pytest.raises(TrustRegistryError, match="vault-relative"):
        normalize_vault_relative(windows_relative)
    with pytest.raises(TrustRegistryError, match="vault-relative"):
        normalize_vault_relative(windows_absolute)
    assert normalize_vault_relative(PureWindowsPath("custom-mcp", "server.py").as_posix()) == (
        "custom-mcp/server.py"
    )


def test_capability_probe_still_authorizes_on_posix(tmp_path):
    root = tmp_path
    (root / "System" / "integrations").mkdir(parents=True)
    (root / "System" / "integrations" / "config.yaml").write_bytes(
        b"todoist:\n  enabled: true\n  api_key: synthetic-old-key\n"
    )
    result = credential_remediation.probe_atomic_migration(
        root, root / "System/.dex/adoption/credential-journals"
    )
    assert result.authorized


def test_windows_name_probe_does_not_authorise(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    root = tmp_path
    (root / "System" / "integrations").mkdir(parents=True)
    (root / "System" / "integrations" / "config.yaml").write_bytes(
        b"todoist:\n  enabled: true\n  api_key: synthetic-old-key\n"
    )
    result = credential_remediation.probe_atomic_migration(
        root, root / "System/.dex/adoption/credential-journals"
    )
    assert not result.authorized
    assert result.results["no-follow-containment"] is False
    assert not (root / "System/.dex").exists() or not any(
        (root / "System/.dex").rglob("*")
    )
