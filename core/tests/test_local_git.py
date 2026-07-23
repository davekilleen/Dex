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
