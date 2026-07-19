"""One sanitized, bounded policy for trusted local Git subprocesses."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

GitProfile = Literal["read-only", "mutation"]
DEFAULT_MAX_OUTPUT = 16 * 1024 * 1024
DEFAULT_TIMEOUT = 30.0
_MUTATING_COMMANDS = frozenset(
    {
        "add", "am", "apply", "branch", "checkout", "cherry-pick", "clean", "clone",
        "commit", "commit-tree", "fetch", "gc", "init", "merge", "mv", "prune", "pull",
        "push", "rebase", "repack", "reset", "restore", "rm", "stash", "switch", "tag",
        "update-index", "update-ref", "worktree",
    }
)


def trusted_git_binary() -> Path:
    """Resolve Git from trusted absolute locations, never an ambient PATH shim."""
    candidates = [Path("/usr/bin/git"), Path("/bin/git")]
    discovered = shutil.which("git", path=os.defpath)
    if discovered:
        candidates.append(Path(discovered))
    for candidate in candidates:
        try:
            absolute = candidate.absolute()
            if absolute.is_symlink() or not absolute.is_file() or not os.access(absolute, os.X_OK):
                continue
            return absolute.resolve(strict=True)
        except OSError:
            continue
    raise RuntimeError("trusted absolute local Git is unavailable")


def git_env(*, index_path: Path | None = None) -> dict[str, str]:
    """Return the closed baseline environment used by every Git consumer."""
    git = trusted_git_binary()
    executable_dirs = dict.fromkeys(
        (str(git.parent), str(Path(sys.executable).resolve().parent), "/usr/bin", "/bin")
    )
    env = {
        "PATH": os.pathsep.join(executable_dirs),
        "HOME": os.environ.get("HOME", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_ASKPASS": "",
        "SSH_ASKPASS": "",
    }
    if index_path is not None:
        env["GIT_INDEX_FILE"] = str(index_path)
    return env


def git_result(
    root: Path,
    *args: str,
    profile: GitProfile,
    index_path: Path | None = None,
    input_data: bytes | None = None,
    pass_fds: tuple[int, ...] = (),
    timeout: float = DEFAULT_TIMEOUT,
    max_output: int = DEFAULT_MAX_OUTPUT,
) -> subprocess.CompletedProcess[bytes]:
    """Run local Git with disabled hooks/helpers/prompts and bounded output."""
    if profile not in {"read-only", "mutation"}:
        raise ValueError("unknown local Git policy profile")
    if profile == "read-only" and args and args[0] in _MUTATING_COMMANDS:
        raise ValueError("read-only local Git policy refuses mutation commands")
    command = [
        str(trusted_git_binary()),
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "credential.helper=",
        "-c",
        "protocol.file.allow=never",
        "-c",
        "commit.gpgSign=false",
        "-c",
        "tag.gpgSign=false",
        "-c",
        "core.fsmonitor=false",
        *args,
    ]
    result = subprocess.run(
        command,
        cwd=root,
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
        env=git_env(index_path=index_path),
        pass_fds=pass_fds,
    )
    if len(result.stdout) > max_output or len(result.stderr) > max_output:
        raise RuntimeError("sanitized local Git output exceeded its bound")
    return result


def git_output(
    root: Path,
    *args: str,
    profile: GitProfile,
    index_path: Path | None = None,
    input_data: bytes | None = None,
    pass_fds: tuple[int, ...] = (),
    timeout: float = DEFAULT_TIMEOUT,
    max_output: int = DEFAULT_MAX_OUTPUT,
) -> bytes:
    """Return bounded stdout or a redacted failure."""
    result = git_result(
        root,
        *args,
        profile=profile,
        index_path=index_path,
        input_data=input_data,
        pass_fds=pass_fds,
        timeout=timeout,
        max_output=max_output,
    )
    if result.returncode:
        raise RuntimeError("sanitized local Git operation failed")
    return result.stdout
