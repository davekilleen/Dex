"""Policy-matrix coverage for every sanitized local-Git consumer."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.utils import credential_remediation, credential_scanner, history_hygiene, local_git, safe_autosave

C_DRIVE_FOLDERS = local_git.WindowsFolders(
    program_files="C:/Program Files",
    program_files_x86="C:/Program Files (x86)",
    local_app_data="C:/Users/Sam/AppData/Local",
    system32="C:/Windows/System32",
    profile="C:/Users/Sam",
)
D_DRIVE_FOLDERS = local_git.WindowsFolders(
    program_files="D:/Program Files",
    program_files_x86="D:/Program Files (x86)",
    local_app_data="D:/Users/Sam/AppData/Local",
    system32="D:/Windows/System32",
    profile="D:/Users/Sam",
)
EMPTY_FOLDERS = local_git.WindowsFolders(
    program_files=None,
    program_files_x86=None,
    local_app_data=None,
    system32=None,
    profile=None,
)
C_DRIVE_CANDIDATES = (
    "C:/Program Files/Git/cmd/git.exe",
    "C:/Program Files/Git/bin/git.exe",
    "C:/Program Files (x86)/Git/cmd/git.exe",
    "C:/Users/Sam/AppData/Local/Programs/Git/cmd/git.exe",
)
D_DRIVE_CANDIDATES = (
    "D:/Program Files/Git/cmd/git.exe",
    "D:/Program Files/Git/bin/git.exe",
    "D:/Program Files (x86)/Git/cmd/git.exe",
    "D:/Users/Sam/AppData/Local/Programs/Git/cmd/git.exe",
)
LOCALAPPDATA_GIT = C_DRIVE_CANDIDATES[3]
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
    "C:/Program Files/Git/mingw64/bin/git.exe",
    "C:/Program Files (x86)/Git/bin/git.exe",
    "C:/Program Files/Git/cmd/git.cmd",
    "C:/Program Files/Git/cmd/git.bat",
    "C:/Program Files/Git/bin/git.cmd",
    "C:/Program Files/Git/bin/git.bat",
    "C:/Program Files (x86)/Git/cmd/git.cmd",
    "/c/Program Files/Git/cmd/git.cmd",
    r"C:\PROGRA~1\Git\cmd\git.exe",
    "C:/PROGRA~1/Git/cmd/git.exe",
    r"\\?\UNC\server\share\Git\cmd\git.exe",
    r"\\server\share\Git\cmd\git.exe",
    "/c/evil/Git/cmd/git.exe",
    "/cygdrive/c/evil/Git/cmd/git.exe",
    "C:/Program Files/Git/cmd/../cmd/git.exe",
    "C:/Program Files/Git/cmd/./git.exe",
    "/c/Program Files/Git/cmd/../cmd/git.exe",
)


def _force_windows(monkeypatch, *, platform: str = "win32") -> None:
    monkeypatch.setattr(local_git.sys, "platform", platform)


def _use_folders(monkeypatch, folders: local_git.WindowsFolders) -> None:
    monkeypatch.setattr(local_git, "_windows_folder_snapshot", lambda: folders)


def _present_windows_binaries(monkeypatch, present: dict[str, str]) -> None:
    """Treat `present` (canonical text -> resolved text) as existing trusted files."""

    keys = {local_git._windows_lexical_key(src): dest for src, dest in present.items()}

    def usable(path: Path) -> Path | None:
        dest = keys.get(local_git._windows_lexical_key(os.fspath(path)))
        if dest is None:
            return None
        return Path(dest)

    monkeypatch.setattr(local_git, "_passes_windows_trust_checks", usable)


def _assert_win_path(actual, expected) -> None:
    """Compare Windows paths by ntpath-normalised form, not slash spelling."""
    assert local_git._windows_lexical_key(os.fspath(actual)) == local_git._windows_lexical_key(
        os.fspath(expected)
    )


def _hooks_setting(joined: str) -> None:
    if local_git._is_windows_like():
        assert "core.hooksPath=/dev/null" not in joined
        assert "core.hooksPath=NUL" in joined
        assert "dex-git-hooks-" not in joined
        return
    assert "core.hooksPath=/dev/null" in joined


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

    git = Path("/usr/bin/git")
    monkeypatch.setattr(local_git.subprocess, "run", run)
    monkeypatch.setattr(local_git, "trusted_git_binary", lambda: git)
    assert local_git.git_output(tmp_path, "status", profile="read-only") == b"ok"
    command = observed["command"]
    assert Path(command[0]) == git
    joined = " ".join(command)
    for setting in (
        "credential.helper=",
        "protocol.file.allow=never",
        "commit.gpgSign=false",
        "tag.gpgSign=false",
        "core.fsmonitor=false",
    ):
        assert setting in joined
    _hooks_setting(joined)
    assert observed["kwargs"]["timeout"] == local_git.DEFAULT_TIMEOUT
    assert observed["kwargs"]["env"]["GIT_CONFIG_GLOBAL"] == os.devnull


def test_git_result_resolves_trusted_git_once_for_command_and_path(tmp_path, monkeypatch):
    observed = {}
    resolves: list[str] = []
    git = (
        Path("C:/Program Files/Git/cmd/git.exe")
        if local_git._is_windows_like()
        else Path("/usr/bin/git")
    )

    def fake_trusted() -> Path:
        resolves.append(os.fspath(git))
        return git

    def run(command, **kwargs):
        observed["command"] = command
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, b"ok", b"")

    monkeypatch.setattr(local_git, "trusted_git_binary", fake_trusted)
    monkeypatch.setattr(local_git.subprocess, "run", run)
    if local_git._is_windows_like():
        _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    local_git.git_output(tmp_path, "status", profile="read-only")
    assert resolves == [os.fspath(git)]
    assert observed["command"][0] == os.fspath(git)
    assert os.fspath(git.parent) in observed["env"]["PATH"].split(os.pathsep)


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


def test_planted_pre_commit_hook_is_not_run(tmp_path):
    """Autosave runs commit and update-ref; a planted hook must not execute."""
    repo = tmp_path / "repo"
    repo.mkdir()
    init = local_git.git_result(repo, "init", profile="mutation")
    assert init.returncode == 0, init.stderr
    marker = tmp_path / "hook-ran"
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        f"#!/bin/sh\necho planted > '{marker.as_posix()}'\nexit 1\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    result = local_git.git_result(
        repo,
        "-c",
        "user.name=Dex",
        "-c",
        "user.email=dex@example.com",
        "commit",
        "--allow-empty",
        "-m",
        "hook-test",
        profile="mutation",
    )
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    if local_git._is_windows_like():
        assert local_git._hooks_path_config() == "core.hooksPath=NUL"
    else:
        assert local_git._hooks_path_config() == "core.hooksPath=/dev/null"


def test_windows_closed_list_comes_from_known_folders_not_hardcoded_c():
    assert local_git.windows_git_candidate_texts(C_DRIVE_FOLDERS) == C_DRIVE_CANDIDATES
    assert local_git.windows_git_candidate_texts(D_DRIVE_FOLDERS) == D_DRIVE_CANDIDATES
    assert local_git.windows_git_candidate_texts(EMPTY_FOLDERS) == ()
    assert "C:/Program Files/Git/cmd/git.exe" not in local_git.windows_git_candidate_texts(D_DRIVE_FOLDERS)
    assert "C:/Program Files/Git/cmd/git.exe" not in local_git.windows_git_candidate_texts(EMPTY_FOLDERS)


@pytest.mark.parametrize("candidate", C_DRIVE_CANDIDATES)
def test_windows_accepts_each_c_drive_candidate(monkeypatch, candidate):
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    _present_windows_binaries(monkeypatch, {candidate: candidate})
    _assert_win_path(local_git.trusted_git_binary(), candidate)


@pytest.mark.parametrize("candidate", D_DRIVE_CANDIDATES)
def test_windows_accepts_program_files_on_d_when_known_folder_is_d(monkeypatch, candidate):
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, D_DRIVE_FOLDERS)
    _present_windows_binaries(monkeypatch, {candidate: candidate})
    _assert_win_path(local_git.trusted_git_binary(), candidate)
    _assert_win_path(local_git.canonical_windows_git_path(candidate, D_DRIVE_FOLDERS), candidate)
    assert local_git.canonical_windows_git_path(candidate, C_DRIVE_FOLDERS) is None


def test_windows_refuses_hardcoded_c_when_known_folders_fail(monkeypatch):
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, EMPTY_FOLDERS)
    planted = "C:/Program Files/Git/cmd/git.exe"
    _present_windows_binaries(monkeypatch, {planted: planted})
    assert local_git.windows_git_candidate_texts() == ()
    assert local_git.canonical_windows_git_path(planted) is None
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()


@pytest.mark.parametrize("candidate", C_DRIVE_CANDIDATES)
def test_windows_maps_git_bash_alias_of_each_candidate(candidate):
    alias = local_git.windows_path_to_posix_alias(candidate, flavor="msys")
    assert alias is not None
    assert local_git.canonical_windows_git_path(alias, C_DRIVE_FOLDERS) == candidate


@pytest.mark.parametrize("candidate", C_DRIVE_CANDIDATES)
def test_windows_maps_cygwin_alias_of_each_candidate(candidate):
    alias = local_git.windows_path_to_posix_alias(candidate, flavor="cygwin")
    assert alias is not None
    assert local_git.canonical_windows_git_path(alias, C_DRIVE_FOLDERS) == candidate
    assert alias.startswith("/cygdrive/c/")


def test_windows_keeps_per_user_localappdata_git_and_states_the_bar(monkeypatch):
    source = Path(local_git.__file__).read_text(encoding="utf-8")
    assert "does not lower the bar" in source
    assert "LOCALAPPDATA/Programs/Git" in source or "Programs/Git/cmd/git.exe" in source
    assert LOCALAPPDATA_GIT in local_git.windows_git_candidate_texts(C_DRIVE_FOLDERS)
    assert local_git.canonical_windows_git_path(LOCALAPPDATA_GIT, C_DRIVE_FOLDERS) == LOCALAPPDATA_GIT
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    _present_windows_binaries(monkeypatch, {LOCALAPPDATA_GIT: LOCALAPPDATA_GIT})
    _assert_win_path(local_git.trusted_git_binary(), LOCALAPPDATA_GIT)


def test_windows_localappdata_env_does_not_inject_a_candidate(monkeypatch):
    _force_windows(monkeypatch)
    folders = C_DRIVE_FOLDERS._replace(local_app_data=None)
    _use_folders(monkeypatch, folders)
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/Sam/AppData/Local")
    monkeypatch.setenv("USERPROFILE", "C:/Users/Sam")
    assert LOCALAPPDATA_GIT not in local_git.windows_git_candidate_texts()
    assert local_git.canonical_windows_git_path(LOCALAPPDATA_GIT) is None
    _present_windows_binaries(monkeypatch, {LOCALAPPDATA_GIT: LOCALAPPDATA_GIT})
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()


def test_windows_source_uses_private_known_folder_handle_not_env():
    source = Path(local_git.__file__).read_text(encoding="utf-8")
    assert "SHGetKnownFolderPath" in source
    assert "WinDLL" in source
    assert "WINFUNCTYPE" in source
    assert "windll.shell32" not in source or "Does not mutate ctypes.windll.shell32" in source
    assert ".argtypes" not in source
    assert ".restype" not in source
    assert 'os.environ.get("LOCALAPPDATA"' not in source
    assert 'os.environ["LOCALAPPDATA"]' not in source


@pytest.mark.parametrize(
    "shim",
    (
        "C:/Program Files/Git/cmd/git.cmd",
        "C:/Program Files/Git/cmd/git.bat",
        "C:/Program Files/Git/bin/git.cmd",
        "C:/Program Files/Git/bin/git.bat",
        "/c/Program Files/Git/cmd/git.cmd",
    ),
)
def test_windows_rejects_cmd_and_bat_shims(monkeypatch, shim):
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    assert local_git.canonical_windows_git_path(shim, C_DRIVE_FOLDERS) is None
    _present_windows_binaries(monkeypatch, {shim: shim, C_DRIVE_CANDIDATES[0]: shim})
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()


def test_windows_rejects_resolved_cmd_shim(monkeypatch):
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    monkeypatch.setattr(local_git, "_path_is_symlink", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_junction", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_reparse_point", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_file", lambda _path: True)
    monkeypatch.setattr(local_git, "_path_access_execute", lambda _path: True)
    monkeypatch.setattr(local_git, "_path_resolve_strict", lambda _path: Path("C:/Program Files/Git/cmd/git.cmd"))
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()


@pytest.mark.parametrize("rejected", REJECTED_WINDOWS_LOCATIONS)
def test_windows_rejects_path_relative_and_other_locations(rejected):
    assert local_git.canonical_windows_git_path(rejected, C_DRIVE_FOLDERS) is None
    assert local_git.canonical_windows_git_path(rejected, D_DRIVE_FOLDERS) is None
    assert local_git.canonical_windows_git_path(rejected, EMPTY_FOLDERS) is None


def test_windows_never_resolves_via_path_or_defpath(monkeypatch, tmp_path):
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
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
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
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
    assert local_git.canonical_windows_git_path("/c/Users/Public/Git/cmd/git.exe", C_DRIVE_FOLDERS) is None
    assert local_git.canonical_windows_git_path(
        "/cygdrive/d/Program Files/Git/cmd/git.exe",
        C_DRIVE_FOLDERS,
    ) is None
    assert local_git.canonical_windows_git_path(
        "/cygdrive/d/Program Files/Git/cmd/git.exe",
        D_DRIVE_FOLDERS,
    ) == "D:/Program Files/Git/cmd/git.exe"


def test_windows_native_python_does_not_open_git_bash_spellings(monkeypatch):
    _force_windows(monkeypatch, platform="win32")
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    alias = "/c/Program Files/Git/cmd/git.exe"
    _present_windows_binaries(monkeypatch, {alias: alias})
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()


@pytest.mark.parametrize("platform", ("cygwin", "msys"))
def test_windows_posix_python_does_not_open_git_bash_or_cygwin_aliases(monkeypatch, platform):
    _force_windows(monkeypatch, platform=platform)
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    alias = (
        "/cygdrive/c/Program Files/Git/cmd/git.exe"
        if platform == "cygwin"
        else "/c/Program Files/Git/cmd/git.exe"
    )
    _present_windows_binaries(monkeypatch, {alias: alias})
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()


def test_windows_cygwin_python_opens_drive_letter_closed_candidate(monkeypatch):
    _force_windows(monkeypatch, platform="cygwin")
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    canonical = "C:/Program Files/Git/cmd/git.exe"
    _present_windows_binaries(monkeypatch, {canonical: canonical})
    _assert_win_path(local_git.trusted_git_binary(), canonical)
    _assert_win_path(
        local_git.canonical_windows_git_path("/cygdrive/c/Program Files/Git/cmd/git.exe"),
        canonical,
    )


def test_windows_rejects_symlink_junction_and_reparse(monkeypatch):
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
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
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    escaped = "C:/evil/git.exe"
    monkeypatch.setattr(local_git, "_path_is_symlink", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_junction", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_reparse_point", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_file", lambda _path: True)
    monkeypatch.setattr(local_git, "_path_access_execute", lambda _path: True)
    monkeypatch.setattr(local_git, "_path_resolve_strict", lambda _path: Path(escaped))
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()
    assert local_git.canonical_windows_git_path(escaped, C_DRIVE_FOLDERS) is None
    assert C_DRIVE_CANDIDATES[0] in local_git.windows_git_candidate_texts(C_DRIVE_FOLDERS)
    assert escaped not in local_git.windows_git_candidate_texts(C_DRIVE_FOLDERS)


def test_windows_accepts_extended_prefix_on_resolved_closed_path(monkeypatch):
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    monkeypatch.setattr(local_git, "_path_is_symlink", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_junction", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_reparse_point", lambda _path: False)
    monkeypatch.setattr(local_git, "_path_is_file", lambda _path: True)
    monkeypatch.setattr(local_git, "_path_access_execute", lambda _path: True)
    monkeypatch.setattr(
        local_git,
        "_path_resolve_strict",
        lambda _path: Path(r"\\?\C:\Program Files\Git\cmd\git.exe"),
    )
    assert local_git.canonical_windows_git_path(r"\\?\C:\Program Files\Git\cmd\git.exe") == (
        "C:/Program Files/Git/cmd/git.exe"
    )
    assert local_git.canonical_windows_git_path(r"\\?\UNC\server\share\Git\cmd\git.exe") is None
    _assert_win_path(local_git.trusted_git_binary(), "C:/Program Files/Git/cmd/git.exe")


def test_windows_accepts_case_insensitive_closed_list_match(monkeypatch):
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    on_disk = "C:/PROGRAM FILES/GIT/CMD/GIT.EXE"
    _present_windows_binaries(monkeypatch, {C_DRIVE_CANDIDATES[0]: on_disk})
    _assert_win_path(local_git.canonical_windows_git_path(on_disk), "C:/PROGRAM FILES/GIT/CMD/GIT.EXE")
    _assert_win_path(local_git.trusted_git_binary(), on_disk)


def test_windows_git_env_path_is_only_trusted_git_dir_and_system32(monkeypatch):
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    git = Path("C:/Program Files/Git/cmd/git.exe")
    env = local_git.git_env(git=git)
    # Linux hosts use ':' as os.pathsep, which fragments 'C:/...' if PATH is split.
    # Compare the closed directory list, not split PATH entries.
    expected_dirs = (os.fspath(git.parent), C_DRIVE_FOLDERS.system32)
    assert env["PATH"] == os.pathsep.join(expected_dirs)
    assert "/usr/bin" not in expected_dirs
    assert "/bin" not in expected_dirs
    assert local_git._windows_lexical_key(os.fspath(git.parent)) in {
        local_git._windows_lexical_key(item) for item in expected_dirs
    }
    assert local_git._windows_lexical_key("C:/Windows/System32") in {
        local_git._windows_lexical_key(item) for item in expected_dirs
    }
    assert local_git._windows_lexical_key(env["HOME"]) == local_git._windows_lexical_key("C:/Users/Sam")


def test_windows_git_env_home_empty_when_profile_lookup_fails(monkeypatch):
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, C_DRIVE_FOLDERS._replace(profile=None))
    monkeypatch.setenv("USERPROFILE", r"E:\Users\Pat")
    env = local_git.git_env(git=Path("C:/Program Files/Git/cmd/git.exe"))
    assert env["HOME"] == ""


def test_windows_hooks_path_is_nul(tmp_path, monkeypatch):
    _force_windows(monkeypatch)
    _use_folders(monkeypatch, C_DRIVE_FOLDERS)
    observed = {}

    def run(command, **kwargs):
        observed["command"] = command
        return subprocess.CompletedProcess(command, 0, b"ok", b"")

    monkeypatch.setattr(local_git.subprocess, "run", run)
    monkeypatch.setattr(local_git, "trusted_git_binary", lambda: Path("C:/Program Files/Git/cmd/git.exe"))
    local_git.git_output(tmp_path, "status", profile="read-only")
    joined = " ".join(observed["command"])
    assert "core.hooksPath=NUL" in joined
    assert "core.hooksPath=/dev/null" not in joined
    assert "dex-git-hooks-" not in joined
    source = Path(local_git.__file__).read_text(encoding="utf-8")
    assert "mkdtemp" not in source
    assert "windows_empty_hooks_directory" not in source


def test_windows_missing_windll_refuses_cleanly(monkeypatch):
    import ctypes

    _force_windows(monkeypatch, platform="cygwin")

    def no_windll(*_args, **_kwargs):
        raise AttributeError("WinDLL")

    monkeypatch.setattr(ctypes, "WinDLL", no_windll, raising=False)
    assert local_git._sh_get_known_folder(local_git._FOLDERID_PROGRAM_FILES) is None
    assert local_git.windows_git_candidate_texts() == ()
    with pytest.raises(RuntimeError, match="trusted absolute local Git is unavailable"):
        local_git.trusted_git_binary()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive-root /dev/null hook plant")
def test_windows_planted_drive_dev_null_hook_is_not_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init = local_git.git_result(repo, "init", profile="mutation")
    assert init.returncode == 0, init.stderr
    drive = Path(f"{repo.resolve().drive}\\")
    planted_dir = drive / "dev" / "null"
    marker = tmp_path / "drive-null-hook-ran"
    hook = planted_dir / "pre-commit"
    try:
        planted_dir.mkdir(parents=True, exist_ok=True)
        hook.write_text(
            f"#!/bin/sh\necho planted > '{marker.as_posix()}'\nexit 1\n",
            encoding="utf-8",
        )
    except OSError:
        pytest.skip("could not plant a hook at the drive-root /dev/null path")
    try:
        result = local_git.git_result(
            repo,
            "-c",
            "user.name=Dex",
            "-c",
            "user.email=dex@example.com",
            "commit",
            "--allow-empty",
            "-m",
            "drive-null-hook-test",
            profile="mutation",
        )
        assert result.returncode == 0, result.stderr
        assert not marker.exists()
        joined = " ".join(
            [
                str(local_git.trusted_git_binary()),
                local_git._hooks_path_config(),
            ]
        )
        assert local_git._hooks_path_config() == "core.hooksPath=NUL"
        assert "core.hooksPath=/dev/null" not in joined
    finally:
        try:
            hook.unlink()
        except OSError:
            pass


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows git rev-parse")
def test_windows_real_trusted_git_rev_parse(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init = local_git.git_result(repo, "init", profile="mutation")
    assert init.returncode == 0, init.stderr
    git = local_git.trusted_git_binary()
    folders = local_git._windows_folder_snapshot()
    assert local_git.canonical_windows_git_path(os.fspath(git), folders) is not None
    result = local_git.git_result(repo, "rev-parse", "--is-inside-work-tree", profile="read-only")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == b"true"
    env = local_git.git_env(git=git)
    entries = env["PATH"].split(os.pathsep)
    assert "/usr/bin" not in entries
    assert "/bin" not in entries
    assert os.fspath(git.parent) in entries


@pytest.mark.skipif(local_git._is_windows_like(), reason="macOS and Linux resolver")
def test_macos_linux_behaviour_is_unchanged_and_still_uses_defpath(monkeypatch):
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
    trusted = {Path("/usr/bin/git").resolve(), Path("/bin/git").resolve()}
    discovered = real_which("git", path=os.defpath)
    if discovered:
        try:
            trusted.add(Path(discovered).resolve(strict=True))
        except OSError:
            pass
    assert binary in trusted
    assert binary.is_file()
    assert os.access(binary, os.X_OK)
    assert "Program Files" not in os.fspath(binary)
    assert local_git.windows_git_candidate_texts() == ()
    assert local_git.windows_git_candidate_texts(C_DRIVE_FOLDERS) == C_DRIVE_CANDIDATES
    env = local_git.git_env(git=binary)
    entries = env["PATH"].split(os.pathsep)
    assert "/usr/bin" in entries
    assert "/bin" in entries


@pytest.mark.skipif(local_git._is_windows_like(), reason="macOS and Linux resolver")
def test_macos_linux_does_not_consult_windows_candidates(monkeypatch, tmp_path):
    assert not local_git._is_windows_like()
    monkeypatch.setattr(
        local_git,
        "windows_git_candidate_texts",
        lambda *_args, **_kwargs: pytest.fail("macOS/Linux trusted git must not build Windows candidates"),
    )
    monkeypatch.setattr(
        local_git,
        "_trusted_windows_git_binary",
        lambda: pytest.fail("macOS/Linux trusted git must not enter the Windows resolver"),
    )
    hostile = tmp_path / "git"
    hostile.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    hostile.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    binary = local_git.trusted_git_binary()
    assert binary != hostile
    assert binary.is_absolute()
    assert local_git._hooks_path_config() == "core.hooksPath=/dev/null"
