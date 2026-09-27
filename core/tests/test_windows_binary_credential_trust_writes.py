"""Windows fail-closed contained writes; POSIX behaviour must stay unchanged."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path, PureWindowsPath

import pytest

from core.utils import credential_remediation, integration_credentials, local_git, trust_registry
from core.utils.trust_registry import TrustRegistryError, load_trusted_mcp_registry, normalize_vault_relative


def _directory_fd(path: Path) -> int:
    return os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))


@pytest.mark.skipif(os.name == "nt", reason="POSIX containment primitives")
def test_contained_nofollow_is_available_on_posix():
    assert hasattr(os, "O_NOFOLLOW")
    assert credential_remediation._contained_nofollow_available()
    assert trust_registry._contained_nofollow_available()


@pytest.mark.skipif(os.name == "nt", reason="POSIX containment primitives")
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


@pytest.mark.skipif(os.name == "nt", reason="POSIX containment primitives")
def test_posix_require_contained_nofollow_is_noop():
    credential_remediation._require_contained_nofollow("posix no-op")
    credential_remediation._require_contained_nofollow("posix write no-op", require_fchmod=True)
    trust_registry._require_contained_nofollow("posix no-op")


@pytest.mark.skipif(os.name == "nt", reason="needs a POSIX directory fd to prove no write")
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
    windows_absolute = str(PureWindowsPath("C:/Temp/Dex/custom-mcp/server.py"))
    assert "\\" in windows_relative
    with pytest.raises(TrustRegistryError, match="vault-relative"):
        normalize_vault_relative(windows_relative)
    with pytest.raises(TrustRegistryError, match="vault-relative"):
        normalize_vault_relative(windows_absolute)
    assert normalize_vault_relative(PureWindowsPath("custom-mcp", "server.py").as_posix()) == (
        "custom-mcp/server.py"
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX containment primitives")
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


def test_git_executable_uses_hardened_trusted_git_binary():
    assert trust_registry.trusted_git_binary is local_git.trusted_git_binary
    if local_git._is_windows_like():
        assert local_git._hooks_path_config() == "core.hooksPath=//./NUL"
        assert local_git._WINDOWS_PF_GIT_SUFFIXES == ("Git/cmd/git.exe", "Git/bin/git.exe")
    else:
        assert local_git._hooks_path_config() == "core.hooksPath=/dev/null"


def test_git_executable_uses_trusted_git_binary(monkeypatch):
    sentinel = Path("/usr/bin/git")
    monkeypatch.setattr(trust_registry, "trusted_git_binary", lambda: sentinel)
    assert trust_registry._git_executable() == sentinel


def test_git_executable_maps_unavailable_trusted_git_to_none(monkeypatch):
    def _unavailable() -> Path:
        raise RuntimeError("trusted absolute local Git is unavailable")

    monkeypatch.setattr(trust_registry, "trusted_git_binary", _unavailable)
    assert trust_registry._git_executable() is None


def _plant_cwd_and_path_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    cwd = tmp_path / "cwd"
    path_dir = tmp_path / "on-path"
    cwd.mkdir()
    path_dir.mkdir()
    planted: list[Path] = []
    names = ("git", "git.exe")
    for directory in (cwd, path_dir):
        for name in names:
            shim = directory / name
            shim.write_text("#!/bin/sh\nexit 99\n")
            shim.chmod(0o755)
            planted.append(shim.resolve())
    monkeypatch.chdir(cwd)
    monkeypatch.setenv("PATH", os.pathsep.join((str(path_dir), os.environ.get("PATH", ""))))
    return planted


def test_git_resolution_relies_on_trusted_binary_without_blanking_defpath(tmp_path, monkeypatch):
    """Uses #749's resolver. os.defpath on Windows is '.;C:\\bin' — do not blank it."""
    original_defpath = os.defpath
    planted = _plant_cwd_and_path_git(tmp_path, monkeypatch)
    assert os.defpath == original_defpath
    resolved = trust_registry._git_executable()
    try:
        trusted = local_git.trusted_git_binary()
    except RuntimeError:
        assert resolved is None
    else:
        assert resolved == trusted
        assert resolved.resolve() not in planted
    assert {path.resolve() for path in planted}.isdisjoint(
        {resolved.resolve()} if resolved is not None else set()
    )


def test_windows_present_registry_is_invalid_without_running_git(tmp_path, monkeypatch):
    """os.name=nt must refuse before Git. Planted helpers must not be invoked."""
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "trusted-mcps.yaml").write_text("trusted_mcps: {}\n")

    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("git must not run on Windows from trust_registry")

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(trust_registry, "trusted_git_binary", boom)
    monkeypatch.setattr(trust_registry.subprocess, "run", boom)

    registry = load_trusted_mcp_registry(vault)
    assert registry.present is True
    assert registry.entries == {}
    assert registry.invalid_reason


def test_inspect_vault_env_authority_is_unsupported_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    (tmp_path / ".env").write_bytes(b"TODOIST_API_KEY=synthetic-old-key\n")
    inspection = integration_credentials.inspect_vault_env_authority(tmp_path)
    assert inspection.valid is False
    assert inspection.reason == "unsupported-platform"
    assert "0600" not in (inspection.repair or "")
    assert "chmod" not in (inspection.repair or "").lower()


@pytest.mark.skipif(os.name == "nt", reason="owner check is reached only after POSIX vault open")
def test_env_owner_check_fails_closed_without_getuid(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("TODOIST_API_KEY=value\n")
    path.chmod(0o600)
    monkeypatch.delattr(integration_credentials.os, "getuid", raising=False)
    with pytest.raises(ValueError, match="owned"):
        integration_credentials.read_vault_env(tmp_path)


def test_legacy_migration_refuses_when_getuid_is_missing(tmp_path, monkeypatch):
    root = tmp_path
    (root / "System" / "integrations").mkdir(parents=True)
    (root / "System" / "integrations" / "config.yaml").write_bytes(
        b"todoist:\n  enabled: true\n  api_key: synthetic-old-key\n"
    )
    monkeypatch.delattr(credential_remediation.os, "getuid", raising=False)
    assert credential_remediation.migrate_legacy_credentials(root).state == "refused"


@pytest.mark.skipif(os.name != "nt", reason="native Windows refusal path")
def test_windows_refusals_raise_cleanly(tmp_path):
    vault = tmp_path / "vault"
    (vault / "System" / "integrations").mkdir(parents=True)
    (vault / "System" / "trusted-mcps.yaml").write_text("trusted_mcps: {}\n")
    (vault / "System" / "integrations" / "config.yaml").write_bytes(
        b"todoist:\n  enabled: true\n  api_key: synthetic-old-key\n"
    )
    (vault / ".env").write_bytes(b"TODOIST_API_KEY=synthetic-old-key\n")

    try:
        registry = load_trusted_mcp_registry(vault)
        assert registry.present is True
        assert registry.entries == {}
        assert registry.invalid_reason
        with pytest.raises(TrustRegistryError):
            trust_registry._open_component_file(
                vault, Path("System/trusted-mcps.yaml"), label="registry"
            )
        with pytest.raises(OSError):
            integration_credentials.update_vault_env(vault, {"TODOIST_API_KEY": "replacement"})
        inspection = integration_credentials.inspect_vault_env_authority(vault)
        assert inspection.valid is False
        assert inspection.reason == "unsupported-platform"
        result = credential_remediation.probe_atomic_migration(
            vault, vault / "System/.dex/adoption/credential-journals"
        )
        assert not result.authorized
        assert credential_remediation.migrate_legacy_credentials(vault).state == "refused"
    except (AttributeError, NotImplementedError) as exc:
        pytest.fail(f"Windows refusal raised {type(exc).__name__}: {exc}")
