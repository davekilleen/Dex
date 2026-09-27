"""Windows CRT text-mode and path simulations for credential and trust writes."""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

from core.utils import credential_remediation, trust_registry
from core.utils.trust_registry import TrustRegistryError, normalize_vault_relative

SIMULATED_O_BINARY = 0x8000


def _directory_fd(path: Path) -> int:
    return os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))


def _strip_simulated_binary(flags: int) -> int:
    return flags & ~SIMULATED_O_BINARY


def _git_vault(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["/usr/bin/git", "-C", str(path), "init", "-b", "main"], check=True, capture_output=True)
    return path


def _trusted_vault(tmp_path: Path, content: bytes) -> tuple[Path, Path]:
    vault = _git_vault(tmp_path / "vault")
    (vault / "custom-mcp").mkdir()
    (vault / "System").mkdir()
    script = vault / "custom-mcp" / "server.py"
    script.write_bytes(content)
    (vault / "System" / "trusted-mcps.yaml").write_text(
        "trusted_mcps:\n"
        "  custom-server:\n"
        "    file: custom-mcp/server.py\n"
        f"    sha256: {hashlib.sha256(content).hexdigest()}\n"
    )
    return vault, script


def test_binary_write_flags_match_shared_helper_expression(monkeypatch):
    monkeypatch.setattr(os, "O_BINARY", SIMULATED_O_BINARY, raising=False)
    assert credential_remediation._binary_write_flags(os.O_WRONLY) == (
        os.O_WRONLY | getattr(os, "O_BINARY", 0)
    )
    assert trust_registry._binary_write_flags(os.O_WRONLY) == (
        os.O_WRONLY | getattr(os, "O_BINARY", 0)
    )
    monkeypatch.delattr(os, "O_BINARY", raising=False)
    assert credential_remediation._binary_write_flags(os.O_WRONLY) == os.O_WRONLY
    assert trust_registry._binary_write_flags(os.O_WRONLY) == os.O_WRONLY


def test_exclusive_write_flags_keep_o_excl_and_posix_nofollow():
    flags = credential_remediation._exclusive_binary_write_flags(
        os.O_WRONLY | os.O_CREAT | os.O_EXCL
    )
    assert flags & os.O_EXCL
    assert flags & os.O_CREAT
    assert flags & os.O_WRONLY
    assert hasattr(os, "O_NOFOLLOW")
    assert flags & os.O_NOFOLLOW


def test_exclusive_write_flags_never_drop_posix_nofollow_when_os_name_is_nt(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    flags = credential_remediation._exclusive_binary_write_flags(
        os.O_WRONLY | os.O_CREAT | os.O_EXCL
    )
    assert flags & os.O_NOFOLLOW
    snapshot_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is not None:
        snapshot_flags |= nofollow
    snapshot_flags = trust_registry._binary_write_flags(snapshot_flags)
    assert snapshot_flags & os.O_NOFOLLOW


def test_atomic_replace_opens_with_o_binary_o_excl_and_nofollow(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "O_BINARY", SIMULATED_O_BINARY, raising=False)
    seen: list[int] = []
    real_open = os.open

    def capturing_open(path, flags, mode=0o777, **kwargs):
        seen.append(flags)
        return real_open(path, _strip_simulated_binary(flags), mode, **kwargs)

    monkeypatch.setattr(os, "open", capturing_open)
    directory = _directory_fd(tmp_path)
    try:
        credential_remediation._atomic_replace_at(
            directory, "config.yaml", b"todoist:\n  api_key_env_var: TODOIST_API_KEY\n", 0o600
        )
    finally:
        os.close(directory)

    write_flags = [flags for flags in seen if flags & os.O_WRONLY]
    assert write_flags
    assert all(flags & SIMULATED_O_BINARY for flags in write_flags)
    assert all(flags & os.O_EXCL for flags in write_flags)
    assert all(flags & os.O_NOFOLLOW for flags in write_flags)
    assert (tmp_path / "config.yaml").read_bytes() == (
        b"todoist:\n  api_key_env_var: TODOIST_API_KEY\n"
    )


def test_atomic_replace_survives_simulated_windows_crlf_translation(tmp_path, monkeypatch):
    """Without O_BINARY the Windows CRT inserts CR before LF; writes must opt out."""
    monkeypatch.setattr(os, "O_BINARY", SIMULATED_O_BINARY, raising=False)
    last_write_flags: list[int] = []
    real_open = os.open
    real_write = os.write
    real_fdopen = os.fdopen

    def tracking_open(path, flags, mode=0o777, **kwargs):
        if flags & os.O_WRONLY:
            last_write_flags.append(flags)
        return real_open(path, _strip_simulated_binary(flags), mode, **kwargs)

    def translating_write(fd: int, data):
        payload = bytes(data)
        flags = last_write_flags[-1] if last_write_flags else 0
        if not (flags & SIMULATED_O_BINARY):
            payload = payload.replace(b"\n", b"\r\n")
        return real_write(fd, payload)

    def translating_fdopen(fd, mode="r", *args, **kwargs):
        handle = real_fdopen(fd, mode, *args, **kwargs)
        if "w" in mode:
            original_write = handle.write

            def write(data):
                flags = last_write_flags[-1] if last_write_flags else 0
                payload = data
                if not (flags & SIMULATED_O_BINARY) and isinstance(data, (bytes, bytearray)):
                    payload = bytes(data).replace(b"\n", b"\r\n")
                return original_write(payload)

            handle.write = write  # type: ignore[method-assign]
        return handle

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "write", translating_write)
    monkeypatch.setattr(os, "fdopen", translating_fdopen)
    payload = b"TODOIST_API_KEY=synthetic-old-key\nPRESERVED=before\n"
    directory = _directory_fd(tmp_path)
    try:
        credential_remediation._atomic_replace_at(directory, ".env", payload, 0o600)
    finally:
        os.close(directory)

    assert (tmp_path / ".env").read_bytes() == payload
    assert b"\r\n" not in (tmp_path / ".env").read_bytes()


def test_missing_o_binary_would_corrupt_lf_payload(tmp_path, monkeypatch):
    """CPython FileIO bypasses ``os.write``; wrap ``fdopen`` to simulate CRT text mode."""
    monkeypatch.setattr(os, "O_BINARY", SIMULATED_O_BINARY, raising=False)
    monkeypatch.setattr(
        credential_remediation,
        "_binary_write_flags",
        lambda base: base,
    )
    last_write_flags: list[int] = []
    real_open = os.open
    real_fdopen = os.fdopen

    def tracking_open(path, flags, mode=0o777, **kwargs):
        if flags & os.O_WRONLY:
            last_write_flags.append(flags)
        return real_open(path, _strip_simulated_binary(flags), mode, **kwargs)

    def translating_fdopen(fd, mode="r", *args, **kwargs):
        handle = real_fdopen(fd, mode, *args, **kwargs)
        if "w" in mode:
            original_write = handle.write

            def write(data):
                flags = last_write_flags[-1] if last_write_flags else 0
                payload = data
                if not (flags & SIMULATED_O_BINARY) and isinstance(data, (bytes, bytearray)):
                    payload = bytes(data).replace(b"\n", b"\r\n")
                return original_write(payload)

            handle.write = write  # type: ignore[method-assign]
        return handle

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "fdopen", translating_fdopen)
    directory = _directory_fd(tmp_path)
    try:
        with pytest.raises(OSError, match="readback mismatch"):
            credential_remediation._atomic_replace_at(
                directory, ".env", b"TODOIST_API_KEY=synthetic-old-key\n", 0o600
            )
    finally:
        os.close(directory)


def test_windows_reparse_point_is_refused_even_when_s_islnk_is_false():
    reparse = type("Stat", (), {"st_file_attributes": 0x400})()
    regular = type("Stat", (), {})()
    assert credential_remediation._is_reparse_point(reparse)
    assert trust_registry._is_reparse_point(reparse)
    assert not credential_remediation._is_reparse_point(regular)
    assert not trust_registry._is_reparse_point(regular)


def test_windows_follow_open_refuses_symlink_temp_before_writing_secrets(tmp_path, monkeypatch):
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    monkeypatch.setattr(
        credential_remediation.uuid,
        "uuid4",
        lambda: type("Token", (), {"hex": "ab" * 16})(),
    )
    outside = tmp_path / "created-through-symlink"
    temp_name = f".secret.{'ab' * 16}"
    (tmp_path / temp_name).symlink_to(outside)
    real_open = os.open

    def windows_follow_open(path, flags, mode=0o777, dir_fd=None, **kwargs):
        target_fd = dir_fd
        name = path
        if target_fd is not None:
            try:
                metadata = os.stat(path, dir_fd=target_fd, follow_symlinks=False)
            except FileNotFoundError:
                metadata = None
            if metadata is not None and stat.S_ISLNK(metadata.st_mode):
                followed = os.readlink(path, dir_fd=target_fd)
                return real_open(followed, flags, mode)
        return real_open(name, flags, mode, dir_fd=dir_fd, **kwargs)

    monkeypatch.setattr(os, "open", windows_follow_open)
    secret = b"TODOIST_API_KEY=must-not-leak\n"
    directory = _directory_fd(tmp_path)
    try:
        with pytest.raises(OSError, match="unfollowed regular file"):
            credential_remediation._atomic_replace_at(directory, "secret", secret, 0o600)
    finally:
        os.close(directory)

    leaked = outside.read_bytes() if outside.exists() else b""
    assert secret not in leaked
    assert b"must-not-leak" not in leaked


def test_posix_mode_is_unenforceable_on_simulated_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    payload = b"line\nline\n"
    directory = _directory_fd(tmp_path)
    try:
        credential_remediation._atomic_replace_at(directory, "journal.json", payload, 0o600)
        metadata = os.stat(tmp_path / "journal.json")
        assert credential_remediation._posix_mode_matches(metadata, 0o600)
        assert not credential_remediation._posix_mode_enforced()
    finally:
        os.close(directory)
    assert (tmp_path / "journal.json").read_bytes() == payload


def test_posix_mode_still_required_on_linux_macos(tmp_path):
    assert credential_remediation._posix_mode_enforced()
    directory = _directory_fd(tmp_path)
    try:
        credential_remediation._atomic_replace_at(directory, "mode.json", b"{}\n", 0o600)
        metadata = os.stat(tmp_path / "mode.json")
        assert stat.S_IMODE(metadata.st_mode) == 0o600
    finally:
        os.close(directory)


def test_write_failure_debug_log_omits_secret_bytes(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger=credential_remediation.logger.name)
    secret = b"TODOIST_API_KEY=synthetic-old-key-should-never-be-logged\n"
    directory = _directory_fd(tmp_path)
    real_open = os.open

    def boom(path, flags, mode=0o777, **kwargs):
        if flags & os.O_WRONLY:
            raise OSError(13, "permission denied")
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", boom)
    try:
        with pytest.raises(OSError):
            credential_remediation._atomic_replace_at(directory, ".env", secret, 0o600)
    finally:
        os.close(directory)

    logged = caplog.text
    assert "credential" in logged
    assert "errno=13" in logged
    assert "synthetic-old-key-should-never-be-logged" not in logged
    assert secret.decode() not in logged


def test_trust_registry_rejects_simulated_windows_paths():
    windows_relative = str(PureWindowsPath("System") / "trusted-mcps.yaml")
    windows_absolute = str(PureWindowsPath("C:/Users/Joe/Dex/custom-mcp/server.py"))
    assert "\\" in windows_relative
    assert "\\" in windows_absolute
    with pytest.raises(TrustRegistryError, match="vault-relative"):
        normalize_vault_relative(windows_relative)
    with pytest.raises(TrustRegistryError, match="vault-relative"):
        normalize_vault_relative(windows_absolute)
    with pytest.raises(TrustRegistryError, match="vault path"):
        trust_registry._configured_relative(
            Path("C:/Users/Joe/Dex"),
            windows_absolute,
        )
    assert normalize_vault_relative(PureWindowsPath("custom-mcp", "server.py").as_posix()) == (
        "custom-mcp/server.py"
    )


def test_snapshot_write_opens_with_o_binary_and_keeps_o_excl(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "O_BINARY", SIMULATED_O_BINARY, raising=False)
    seen: list[int] = []
    real_open = os.open

    def capturing_open(path, flags, mode=0o777, **kwargs):
        seen.append(flags)
        return real_open(path, _strip_simulated_binary(flags), mode, **kwargs)

    monkeypatch.setattr(os, "open", capturing_open)
    content = b"print('trusted')\nprint('second line')\n"
    vault, script = _trusted_vault(tmp_path, content)
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir(mode=0o700)
    decision = trust_registry.snapshot_trusted_mcp(
        vault,
        "custom-server",
        {"command": sys.executable, "args": [str(script)]},
        trust_registry.load_trusted_mcp_registry(vault),
        snapshots,
    )

    write_flags = [flags for flags in seen if flags & os.O_WRONLY]
    assert decision.trusted is True
    assert decision.snapshot_path is not None
    assert decision.snapshot_path.read_bytes() == content
    assert write_flags
    assert all(flags & SIMULATED_O_BINARY for flags in write_flags)
    assert all(flags & os.O_EXCL for flags in write_flags)
    assert all(flags & os.O_NOFOLLOW for flags in write_flags)


def test_snapshot_write_survives_simulated_windows_crlf_translation(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "O_BINARY", SIMULATED_O_BINARY, raising=False)
    last_write_flags: list[int] = []
    real_open = os.open
    real_write = os.write

    def tracking_open(path, flags, mode=0o777, **kwargs):
        if flags & os.O_WRONLY:
            last_write_flags.append(flags)
        return real_open(path, _strip_simulated_binary(flags), mode, **kwargs)

    def translating_write(fd: int, data):
        payload = bytes(data)
        flags = last_write_flags[-1] if last_write_flags else 0
        if not (flags & SIMULATED_O_BINARY):
            payload = payload.replace(b"\n", b"\r\n")
        return real_write(fd, payload)

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "write", translating_write)
    content = b"print('one')\nprint('two')\n"
    vault, script = _trusted_vault(tmp_path, content)
    digest = hashlib.sha256(content).hexdigest()
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir(mode=0o700)
    decision = trust_registry.snapshot_trusted_mcp(
        vault,
        "custom-server",
        {"command": sys.executable, "args": [str(script)]},
        trust_registry.load_trusted_mcp_registry(vault),
        snapshots,
    )
    assert decision.trusted is True
    assert decision.sha256 == digest
    assert decision.snapshot_path is not None
    assert decision.snapshot_path.read_bytes() == content


def test_snapshot_failure_debug_log_omits_script_bytes(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger=trust_registry.logger.name)
    secretish = b"print('not-a-credential-but-must-not-be-logged')\n"
    vault, script = _trusted_vault(tmp_path, secretish)
    (vault / "System" / "trusted-mcps.yaml").write_text(
        "trusted_mcps:\n"
        "  custom-server:\n"
        "    file: custom-mcp/server.py\n"
        "    sha256: 0" + "a" * 63 + "\n"
    )
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir(mode=0o700)
    decision = trust_registry.snapshot_trusted_mcp(
        vault,
        "custom-server",
        {"command": sys.executable, "args": [str(script)]},
        trust_registry.load_trusted_mcp_registry(vault),
        snapshots,
    )
    assert decision.trusted is False
    assert "not-a-credential-but-must-not-be-logged" not in caplog.text
    assert secretish.decode() not in caplog.text


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
