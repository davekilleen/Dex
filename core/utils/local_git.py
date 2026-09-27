"""One sanitized, bounded policy for trusted local Git subprocesses."""

from __future__ import annotations

import ntpath
import os
import re
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

# Closed Windows list. These are the only Windows locations that may be executed.
# Git Bash (`/c/...`) and Cygwin (`/cygdrive/c/...`) spellings map to this list
# before any filesystem access. They are not extra trust roots.
#
# Per-user Git for Windows (`<LocalAppData>/Programs/Git/cmd/git.exe`) is added
# only from the OS Known Folder ID, never from the LOCALAPPDATA environment
# variable. See `_windows_local_app_data`.
WINDOWS_FIXED_GIT_CANDIDATES = (
    "C:/Program Files/Git/cmd/git.exe",
    "C:/Program Files/Git/bin/git.exe",
    "C:/Program Files (x86)/Git/cmd/git.exe",
)
_WINDOWS_LOCAL_GIT_SUFFIX = "Programs/Git/cmd/git.exe"
_WINDOWS_ABS = re.compile(r"^[A-Za-z]:[/\\]")
_WINDOWS_POSIX_ALIAS = re.compile(r"^/(?:cygdrive/)?([A-Za-z])/(.*)$")
_WINDOWS_8_3_COMPONENT = re.compile(r"^[^.]{1,8}~\d{1,2}(?:\.[^.]{1,3})?$", re.IGNORECASE)
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FOLDERID_LOCAL_APP_DATA = "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}"
_WINDOWS_LIKE_PLATFORMS = frozenset({"win32", "cygwin", "msys"})

# Windows cannot enforce the POSIX ownership/mode bar this helper applies on
# macOS/Linux. Documented gaps (honest, not aspirational):
# - No root/uid owner check: NTFS uses SIDs/ACLs, not st_uid.
# - No "not world-writable" bit check: Program Files is usually admin-only, but
#   this code does not read ACLs.
# - os.access(X_OK) is weak on Windows (often true for any existing file).
# - Intermediate junctions are detected after resolve() by requiring the
#   realpath to remain a closed-list member; we do not walk every parent with
#   a no-follow descriptor (dir_fd is POSIX).
# - Same-user planting in LocalAppData\Programs is possible because that
#   directory is user-writable. The path is still included because it is the
#   official Git for Windows per-user location, and the prefix comes from the
#   Known Folder API rather than an environment variable.
# - 8.3 short names are not in the closed list and are rejected lexically.
# - Windows is treated as case-insensitive; a case-sensitive directory (rare)
#   could hold a second file with different case. We cannot distinguish that.


def _is_windows_like() -> bool:
    return sys.platform in _WINDOWS_LIKE_PLATFORMS


def _windows_lexical_key(text: str) -> str:
    return ntpath.normcase(ntpath.normpath(text.replace("/", "\\")))


def _windows_has_dot_or_empty_component(text: str) -> bool:
    rest = _WINDOWS_ABS.sub("", text, count=1)
    return any(part in {"", ".", ".."} for part in rest.replace("/", "\\").split("\\"))


def _windows_has_short_name_component(text: str) -> bool:
    rest = _WINDOWS_ABS.sub("", text, count=1)
    return any(_WINDOWS_8_3_COMPONENT.fullmatch(part) for part in rest.replace("/", "\\").split("\\") if part)


def posix_windows_alias_to_drive_path(text: str) -> str | None:
    """Map Git Bash `/c/...` and Cygwin `/cygdrive/c/...` to `C:/...`.

    Returns None for any other spelling, including relative paths and `/usr/bin/git`.
    The result is not trusted until it is also a closed-list member.
    """
    if "\x00" in text:
        return None
    match = _WINDOWS_POSIX_ALIAS.fullmatch(text.replace("\\", "/"))
    if match is None:
        return None
    return f"{match.group(1).upper()}:/{match.group(2)}"


def windows_path_to_posix_alias(text: str, *, flavor: str) -> str | None:
    """Return the Git Bash or Cygwin spelling of a drive-letter Windows path."""
    match = re.match(r"^([A-Za-z]):[/\\](.*)$", text)
    if match is None:
        return None
    drive = match.group(1).lower()
    rest = match.group(2).replace("\\", "/")
    if flavor == "cygwin":
        return f"/cygdrive/{drive}/{rest}"
    if flavor == "msys":
        return f"/{drive}/{rest}"
    return None


def _drive_letter_windows_path(text: str) -> str | None:
    """Return `X:/...` for a Windows drive path or a Git Bash/Cygwin alias."""
    if "\x00" in text:
        return None
    if _WINDOWS_ABS.match(text):
        mapped = f"{text[0].upper()}:/{text[2:].replace(chr(92), '/').lstrip('/')}"
    else:
        mapped = posix_windows_alias_to_drive_path(text)
        if mapped is None:
            return None
    if _windows_has_dot_or_empty_component(mapped) or _windows_has_short_name_component(mapped):
        return None
    return mapped


def _windows_local_app_data() -> str | None:
    """Return the OS-known LocalAppData folder.

    Uses SHGetKnownFolderPath(FOLDERID_LocalAppData). Never reads LOCALAPPDATA,
    USERPROFILE, or HOME. A hijacked environment therefore cannot redirect this
    prefix. Returns None when the API is unavailable or the result is not a
    drive-letter absolute path.
    """
    if not _is_windows_like():
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None
    if not hasattr(ctypes, "windll"):
        return None

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        ]

    hexed = _FOLDERID_LOCAL_APP_DATA.strip("{}").split("-")
    if len(hexed) != 5:
        return None
    data4 = bytes.fromhex(hexed[3] + hexed[4])
    if len(data4) != 8:
        return None
    folder_id = GUID(
        int(hexed[0], 16),
        int(hexed[1], 16),
        int(hexed[2], 16),
        (wintypes.BYTE * 8).from_buffer_copy(data4),
    )
    path_ptr = ctypes.c_wchar_p()
    try:
        get_known = ctypes.windll.shell32.SHGetKnownFolderPath
        get_known.argtypes = [
            ctypes.POINTER(GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        get_known.restype = ctypes.HRESULT
        status = get_known(ctypes.byref(folder_id), 0, None, ctypes.byref(path_ptr))
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if status != 0 or not path_ptr.value:
        return None
    try:
        value = path_ptr.value
    finally:
        try:
            ctypes.windll.ole32.CoTaskMemFree(path_ptr)
        except (AttributeError, OSError, TypeError, ValueError):
            pass
    if not value or "\x00" in value:
        return None
    drive_path = _drive_letter_windows_path(value)
    if drive_path is None:
        return None
    return drive_path


def windows_git_candidate_texts() -> tuple[str, ...]:
    """Closed Windows candidate texts, including a validated per-user path."""
    candidates = list(WINDOWS_FIXED_GIT_CANDIDATES)
    local_app_data = _windows_local_app_data()
    if local_app_data is not None:
        per_user = f"{local_app_data.rstrip('/')}/{_WINDOWS_LOCAL_GIT_SUFFIX}"
        if canonical_windows_git_path(per_user) == per_user:
            candidates.append(per_user)
    return tuple(dict.fromkeys(candidates))


def canonical_windows_git_path(text: str) -> str | None:
    """Return the closed-list Windows path for `text`, or None.

    Accepts the three fixed Git for Windows locations, their Git Bash/Cygwin
    spellings, and the Known-Folder per-user path. Rejects PATH names, relative
    paths, the current directory, UNC/extended prefixes, 8.3 names, and any
    other location.
    """
    drive_path = _drive_letter_windows_path(text)
    if drive_path is None:
        return None
    if not drive_path.replace("\\", "/").casefold().endswith("/git.exe"):
        return None
    key = _windows_lexical_key(drive_path)
    allowed = {_windows_lexical_key(item) for item in WINDOWS_FIXED_GIT_CANDIDATES}
    local_app_data = _windows_local_app_data()
    if local_app_data is not None:
        allowed.add(_windows_lexical_key(f"{local_app_data.rstrip('/')}/{_WINDOWS_LOCAL_GIT_SUFFIX}"))
    if key not in allowed:
        return None
    return drive_path


def _windows_probe_texts(candidate: str) -> tuple[str, ...]:
    """Paths we may open for one closed candidate.

    Native Windows Python (win32) opens only the drive-letter form. Opening a
    Git Bash spelling there would touch `\\c\\Program Files\\...` on the current
    drive — a plantable location, not Git for Windows. Cygwin/MSYS Python may
    only see the POSIX alias, so that spelling is opened there after it maps
    back to the same closed candidate.
    """
    canonical = canonical_windows_git_path(candidate)
    if canonical is None:
        return ()
    texts = [canonical]
    if sys.platform in {"cygwin", "msys"}:
        alias = windows_path_to_posix_alias(canonical, flavor=sys.platform)
        if alias is not None and canonical_windows_git_path(alias) == canonical:
            texts.append(alias)
    return tuple(texts)


def _path_is_symlink(path: Path) -> bool:
    return path.is_symlink()


def _path_is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    if not callable(checker):
        return False
    return bool(checker())


def _path_is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _path_is_file(path: Path) -> bool:
    return path.is_file()


def _path_access_execute(path: Path) -> bool:
    return os.access(path, os.X_OK)


def _path_resolve_strict(path: Path) -> Path:
    return path.resolve(strict=True)


def _passes_windows_trust_checks(path: Path) -> Path | None:
    """Apply the POSIX file/symlink/execute/realpath checks, adapted for Windows."""
    try:
        if _path_is_symlink(path) or _path_is_junction(path) or _path_is_reparse_point(path):
            return None
        if not _path_is_file(path) or not _path_access_execute(path):
            return None
        return _path_resolve_strict(path)
    except OSError:
        return None


def _trusted_windows_git_binary() -> Path:
    for candidate in windows_git_candidate_texts():
        for text in _windows_probe_texts(candidate):
            if canonical_windows_git_path(text) is None:
                continue
            accepted = _passes_windows_trust_checks(Path(text))
            if accepted is None:
                continue
            if canonical_windows_git_path(os.fspath(accepted)) is None:
                continue
            return accepted
    raise RuntimeError("trusted absolute local Git is unavailable")


def _trusted_posix_git_binary() -> Path:
    """Resolve Git from trusted absolute POSIX locations, never an ambient PATH shim."""
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


def trusted_git_binary() -> Path:
    """Resolve Git from trusted absolute locations, never an ambient PATH shim."""
    if _is_windows_like():
        return _trusted_windows_git_binary()
    return _trusted_posix_git_binary()


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
