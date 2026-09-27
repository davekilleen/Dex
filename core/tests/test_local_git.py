"""Policy-matrix coverage for every sanitized local-Git consumer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from core.utils import credential_remediation, credential_scanner, history_hygiene, local_git, safe_autosave


def test_local_git_ignores_hostile_path_and_git_config(tmp_path, monkeypatch):
    hostile = tmp_path / "git"
    hostile.write_text("#!/bin/sh\nexit 99\n")
    hostile.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "hostile-config"))

    binary = local_git.trusted_git_binary()
    assert binary != hostile
    env = local_git.git_env()
    assert str(tmp_path) not in env["PATH"].split(os.pathsep)
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_local_git_command_policy_disables_execution_surfaces(tmp_path, monkeypatch):
    observed = {}

    def run(command, **kwargs):
        observed.update(command=command, kwargs=kwargs)
        return subprocess.CompletedProcess(command, 0, b"ok", b"")

    monkeypatch.setattr(local_git.subprocess, "run", run)
    monkeypatch.setattr(local_git, "trusted_git_binary", lambda: Path("/usr/bin/git"))
    assert local_git.git_output(tmp_path, "status", profile="read-only") == b"ok"
    command = observed["command"]
    assert command[0] == "/usr/bin/git"
    joined = " ".join(command)
    for setting in (
        "core.hooksPath=/dev/null",
        "credential.helper=",
        "protocol.file.allow=never",
        "commit.gpgSign=false",
        "tag.gpgSign=false",
        "core.fsmonitor=false",
    ):
        assert setting in joined
    assert observed["kwargs"]["timeout"] == local_git.DEFAULT_TIMEOUT
    assert observed["kwargs"]["env"]["GIT_CONFIG_GLOBAL"] == os.devnull


def test_every_task_one_git_consumer_uses_the_shared_policy():
    assert safe_autosave.git_result.__module__ == "core.utils.local_git"
    assert credential_scanner.git_output.__module__ == "core.utils.local_git"
    assert history_hygiene.git_output.__module__ == "core.utils.local_git"
    assert credential_remediation.git_output.__module__ == "core.utils.local_git"
    scanner = Path(__file__).resolve().parents[2] / "scripts/security-scan.py"
    assert "from core.utils.local_git import git_output" in scanner.read_text()


def test_output_bound_is_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(local_git, "trusted_git_binary", lambda: Path("/usr/bin/git"))
    monkeypatch.setattr(
        local_git.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, b"x" * 5, b""),
    )
    with pytest.raises(RuntimeError, match="output exceeded"):
        local_git.git_output(tmp_path, "status", profile="read-only", max_output=4)


def test_read_only_profile_refuses_mutation_before_subprocess(tmp_path, monkeypatch):
    monkeypatch.setattr(
        local_git.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("mutation must be refused before subprocess"),
    )
    with pytest.raises(ValueError, match="read-only"):
        local_git.git_output(tmp_path, "update-ref", "HEAD", "0" * 40, profile="read-only")


FIXED_WINDOWS_CANDIDATES = local_git.WINDOWS_FIXED_GIT_CANDIDATES
LOCALAPPDATA_GIT = "C:/Users/Sam/AppData/Local/Programs/Git/cmd/git.exe"
REJECTED_WINDOWS_LOCATIONS = (
    "git",
    "git.exe",
    "./git.exe",
    "../git.exe",
    "Git/cmd/git.exe",
    "C:git.exe",
    r"C:Git\cmd\git.exe",
    "/usr/bin/git",
    "/bin/git",
    "C:/Windows/System32/git.exe",
    "C:/Users/Public/git.exe",
    "C:/evil/Git/cmd/git.exe",
    "D:/Program Files/Git/cmd/git.exe",
    "C:/Program Files/Git/mingw64/bin/git.exe",
    "C:/Program Files (x86)/Git/bin/git.exe",
    r"C:\PROGRA~1\Git\cmd\git.exe",
    "C:/PROGRA~1/Git/cmd/git.exe",
    r"\\?\C:\Program Files\Git\cmd\git.exe",
    r"\\server\share\Git\cmd\git.exe",
    "/c/evil/Git/cmd/git.exe",
    "/cygdrive/c/evil/Git/cmd/git.exe",
    "C:/Program Files/Git/cmd/../cmd/git.exe",
    "C:/Program Files/Git/cmd/./git.exe",
    "/c/Program Files/Git/cmd/../cmd/git.exe",
)


def _force_windows(monkeypatch, *, platform: str = "win32", local_app_data: str | None = None) -> None:
    monkeypatch.setattr(local_git.sys, "platform", platform)
    monkeypatch.setattr(local_git, "_windows_local_app_data", lambda: local_app_data)


def _present_windows_binaries(monkeypatch, present: dict[str, str]) -> None:
    """Treat `present` (canonical text -> resolved text) as existing trusted files."""

    keys = {local_git._windows_lexical_key(src): dest for src, dest in present.items()}

    def usable(path: Path) -> Path | None:
        dest = keys.get(local_git._windows_lexical_key(os.fspath(path)))
        if dest is None:
            return None
        return Path(dest)

    monkeypatch.setattr(local_git, "_passes_windows_trust_checks", usable)


def test_windows_closed_list_is_the_documented_absolute_paths():
    assert FIXED_WINDOWS_CANDIDATES == (
        "C:/Program Files/Git/cmd/git.exe",
        "C:/Program Files/Git/bin/git.exe",
        "C:/Program Files (x86)/Git/cmd/git.exe",
    )


@pytest.mark.parametrize("candidate", FIXED_WINDOWS_CANDIDATES)
def test_windows_accepts_each_fixed_candidate(monkeypatch, candidate):
    _force_windows(monkeypatch)
    _present_windows_binaries(monkeypatch, {candidate: candidate})
    assert os.fspath(local_git.trusted_git_binary()) == candidate


@pytest.mark.parametrize("candidate", FIXED_WINDOWS_CANDIDATES)
def test_windows_maps_git_bash_alias_of_each_candidate(candidate):
    alias = local_git.windows_path_to_posix_alias(candidate, flavor="msys")
    assert alias is not None
    assert local_git.canonical_windows_git_path(alias) == candidate


@pytest.mark.parametrize("candidate", FIXED_WINDOWS_CANDIDATES)
def test_windows_maps_cygwin_alias_of_each_candidate(candidate):
    alias = local_git.windows_path_to_posix_alias(candidate, flavor="cygwin")
    assert alias is not None
    assert local_git.canonical_windows_git_path(alias) == candidate
    assert alias.startswith("/cygdrive/c/")


def test_windows_per_user_localappdata_candidate_when_known_folder_is_safe(monkeypatch):
    _force_windows(monkeypatch, local_app_data="C:/Users/Sam/AppData/Local")
    _present_windows_binaries(monkeypatch, {LOCALAPPDATA_GIT: LOCALAPPDATA_GIT})
    assert LOCALAPPDATA_GIT in local_git.windows_git_candidate_texts()
    assert os.fspath(local_git.trusted_git_binary()) == LOCALAPPDATA_GIT
    assert local_git.canonical_windows_git_path("/c/Users/Sam/AppData/Local/Programs/Git/cmd/git.exe") == LOCALAPPDATA_GIT


def test_windows_ignores_localappdata_environment_injection(monkeypatch):
    _force_windows(monkeypatch, local_app_data="C:/Users/Sam/AppData/Local")
    monkeypatch.setenv("LOCALAPPDATA", "C:/evil/AppData/Local")
    monkeypatch.setenv("USERPROFILE", "C:/evil")
    monkeypatch.setenv("HOME", "C:/evil")
    planted = "C:/evil/AppData/Local/Programs/Git/cmd/git.exe"
    assert local_git.canonical_windows_git_path(planted) is None
    assert planted not in local_git.windows_git_candidate_texts()
    _present_windows_binaries(monkeypatch, {planted: planted})
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()


def test_windows_known_folder_localappdata_never_reads_process_environment():
    source = Path(local_git.__file__).read_text(encoding="utf-8")
    assert "LOCALAPPDATA" in source
    assert 'os.environ.get("LOCALAPPDATA"' not in source
    assert "os.environ[\"LOCALAPPDATA\"]" not in source
    assert "os.environ.get('LOCALAPPDATA'" not in source
    assert "SHGetKnownFolderPath" in source


@pytest.mark.parametrize("rejected", REJECTED_WINDOWS_LOCATIONS)
def test_windows_rejects_path_relative_and_other_locations(rejected):
    assert local_git.canonical_windows_git_path(rejected) is None


def test_windows_never_resolves_via_path_or_defpath(monkeypatch, tmp_path):
    _force_windows(monkeypatch)
    hostile = tmp_path / "git.exe"
    hostile.write_text("evil", encoding="utf-8")
    hostile.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(local_git.os, "defpath", str(tmp_path))

    def boom(*_args, **_kwargs):
        raise AssertionError("Windows trusted git must not consult PATH")

    monkeypatch.setattr(local_git.shutil, "which", boom)
    _present_windows_binaries(monkeypatch, {})
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()


def test_windows_rejects_relative_and_cwd_even_when_file_exists(monkeypatch, tmp_path):
    _force_windows(monkeypatch)
    planted = tmp_path / "git.exe"
    planted.write_bytes(b"MZ")
    planted.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    _present_windows_binaries(
        monkeypatch,
        {
            "git.exe": str(planted),
            "./git.exe": str(planted),
            str(planted): str(planted),
        },
    )
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()


def test_windows_rejects_git_bash_alias_that_is_not_in_the_closed_list():
    assert local_git.canonical_windows_git_path("/c/Users/Public/Git/cmd/git.exe") is None
    assert local_git.canonical_windows_git_path("/cygdrive/d/Program Files/Git/cmd/git.exe") is None


def test_windows_native_python_does_not_open_git_bash_spellings(monkeypatch):
    _force_windows(monkeypatch, platform="win32")
    alias = "/c/Program Files/Git/cmd/git.exe"
    _present_windows_binaries(monkeypatch, {alias: alias})
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()


def test_windows_cygwin_python_opens_mapped_alias_of_closed_candidate(monkeypatch):
    _force_windows(monkeypatch, platform="cygwin")
    alias = "/cygdrive/c/Program Files/Git/cmd/git.exe"
    canonical = "C:/Program Files/Git/cmd/git.exe"
    _present_windows_binaries(monkeypatch, {alias: alias})
    assert os.fspath(local_git.trusted_git_binary()) == alias
    assert local_git.canonical_windows_git_path(alias) == canonical


def test_windows_rejects_symlink_junction_and_reparse(monkeypatch):
    _force_windows(monkeypatch)
    monkeypatch.setattr(local_git, "_path_is_file", lambda _path: True)
    monkeypatch.setattr(local_git, "_path_access_execute", lambda _path: True)
    monkeypatch.setattr(local_git, "_path_resolve_strict", lambda path: path)

    monkeypatch.setattr(local_git, "_path_is_symlink", lambda _path: True)
    monkeypatch.setattr(local_git, "_path_is_junction", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_reparse_point", lambda _path: False)
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()

    monkeypatch.setattr(local_git, "_path_is_symlink", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_junction", lambda _path: True)
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()

    monkeypatch.setattr(local_git, "_path_is_junction", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_reparse_point", lambda _path: True)
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()


def test_windows_rejects_realpath_that_escapes_the_closed_list(monkeypatch):
    _force_windows(monkeypatch)
    candidate = Path(FIXED_WINDOWS_CANDIDATES[0])
    monkeypatch.setattr(local_git, "_path_is_symlink", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_junction", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_reparse_point", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_file", lambda _path: True)
    monkeypatch.setattr(local_git, "_path_access_execute", lambda _path: True)
    monkeypatch.setattr(local_git, "_path_resolve_strict", lambda _path: Path("C:/evil/git.exe"))
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()
    assert candidate.as_posix().startswith("C:/")


def test_windows_accepts_case_insensitive_closed_list_match(monkeypatch):
    _force_windows(monkeypatch)
    on_disk = "C:/PROGRAM FILES/GIT/CMD/GIT.EXE"
    _present_windows_binaries(monkeypatch, {FIXED_WINDOWS_CANDIDATES[0]: on_disk})
    assert local_git.canonical_windows_git_path(on_disk) == "C:/PROGRAM FILES/GIT/CMD/GIT.EXE"
    assert os.fspath(local_git.trusted_git_binary()) == on_disk


def test_posix_behaviour_is_unchanged_and_still_uses_defpath(monkeypatch):
    assert not local_git._is_windows_like()
    observed = {}
    real_which = local_git.shutil.which

    def wrapped(name, path=None):
        observed["name"] = name
        observed["path"] = path
        return real_which(name, path=path)

    monkeypatch.setattr(local_git.shutil, "which", wrapped)
    binary = local_git.trusted_git_binary()
    assert observed == {"name": "git", "path": os.defpath}
    assert binary in {Path("/usr/bin/git").resolve(), Path("/bin/git").resolve(), binary}
    assert "Program Files" not in os.fspath(binary)
    assert local_git.windows_git_candidate_texts() == FIXED_WINDOWS_CANDIDATES


def test_posix_does_not_consult_windows_candidates(monkeypatch, tmp_path):
    assert not local_git._is_windows_like()
    monkeypatch.setattr(
        local_git,
        "windows_git_candidate_texts",
        lambda: pytest.fail("POSIX trusted git must not build Windows candidates"),
    )
    monkeypatch.setattr(
        local_git,
        "_trusted_windows_git_binary",
        lambda: pytest.fail("POSIX trusted git must not enter the Windows resolver"),
    )
    hostile = tmp_path / "git"
    hostile.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    hostile.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    binary = local_git.trusted_git_binary()
    assert binary != hostile
    assert binary.is_absolute()
