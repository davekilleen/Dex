"""One sanitized, bounded policy for trusted local Git subprocesses."""

from __future__ import annotations

import ntpath
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal, NamedTuple

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

# Closed Windows suffixes. Prefixes come from SHGetKnownFolderPath, never from
# hardcoded C: or process environment. Git Bash (`/c/...`) and Cygwin
# (`/cygdrive/c/...`) spellings map to these same closed paths before any
# filesystem access. They are not extra trust roots.
#
# Per-user Git for Windows (`LOCALAPPDATA/Programs/Git/cmd/git.exe`) is kept
# on purpose. A process running as the user can already modify Dex's own files,
# so this candidate does not lower the bar. Dropping it would refuse the common
# "install for this user only" Git for Windows layout.
_WINDOWS_PF_GIT_SUFFIXES = ("Git/cmd/git.exe", "Git/bin/git.exe")
_WINDOWS_PF86_GIT_SUFFIX = "Git/cmd/git.exe"
_WINDOWS_LOCAL_GIT_SUFFIX = "Programs/Git/cmd/git.exe"
_WINDOWS_ABS = re.compile(r"^[A-Za-z]:[/\\]")
_WINDOWS_POSIX_ALIAS = re.compile(r"^/(?:cygdrive/)?([A-Za-z])/(.*)$")
_WINDOWS_8_3_COMPONENT = re.compile(r"^[^.]{1,8}~\d{1,2}(?:\.[^.]{1,3})?$", re.IGNORECASE)
_WINDOWS_SHIM_SUFFIXES = (".cmd", ".bat")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_WINDOWS_LIKE_PLATFORMS = frozenset({"win32", "cygwin", "msys"})
_FOLDERID_PROGRAM_FILES = "{905E63B6-C1BF-494E-B29C-65B732D3D21A}"
_FOLDERID_PROGRAM_FILES_X86 = "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}"
_FOLDERID_LOCAL_APP_DATA = "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}"
_FOLDERID_SYSTEM = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
_FOLDERID_PROFILE = "{5E6C858F-0E22-4760-9AFE-EA3317B67173}"

# Windows cannot enforce the POSIX ownership/mode bar this helper applies on
# macOS/Linux. Documented gaps (honest, not aspirational):
# - No root/uid owner check: NTFS uses SIDs/ACLs, not st_uid.
# - No "not world-writable" bit check: Program Files is usually admin-only, but
#   this code does not read ACLs.
# - os.access(X_OK) is weak on Windows (often true for any existing file).
# - Intermediate junctions: the leaf and each parent are rejected if they are
#   a symlink, junction, or reparse point. After resolve() the realpath must
#   still be a closed-list member. We do not have POSIX dir_fd no-follow.
# - .cmd / .bat shims are rejected even if they sit next to git.exe.
# - 8.3 short names are not in the closed list and are rejected lexically.
# - Windows is treated as case-insensitive; a case-sensitive directory (rare)
#   could hold a second file with different case. We cannot distinguish that.
# - If SHGetKnownFolderPath fails for Program Files, those candidates are
#   refused. There is no hardcoded C: fallback.


class WindowsFolders(NamedTuple):
    """One Known Folder snapshot. Lookups happen once per resolution."""

    program_files: str | None
    program_files_x86: str | None
    local_app_data: str | None
    system32: str | None
    profile: str | None


_WINDOWS_HOOKS_DIR: Path | None = None


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


def _windows_leaf_name(text: str) -> str:
    return text.replace("\\", "/").rsplit("/", 1)[-1].casefold()


def _windows_leaf_is_git_exe(text: str) -> bool:
    return _windows_leaf_name(text) == "git.exe"


def _windows_leaf_is_cmd_or_bat_shim(text: str) -> bool:
    return _windows_leaf_name(text).endswith(_WINDOWS_SHIM_SUFFIXES)


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


def _strip_win32_namespace_prefix(text: str) -> str:
    """Drop a `\\\\?\\` or `\\\\.\\` prefix only when a drive-letter path remains."""
    normalized = text.replace("/", "\\")
    if normalized.startswith("\\\\?\\UNC\\") or normalized.startswith("\\\\.\\UNC\\"):
        return text
    for prefix in ("\\\\?\\", "\\\\.\\"):
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
    return text


def _drive_letter_windows_path(text: str) -> str | None:
    """Return `X:/...` for a Windows drive path or a Git Bash/Cygwin alias."""
    if "\x00" in text:
        return None
    stripped = _strip_win32_namespace_prefix(text)
    if _WINDOWS_ABS.match(stripped):
        mapped = f"{stripped[0].upper()}:/{stripped[2:].replace(chr(92), '/').lstrip('/')}".rstrip("/")
        if len(mapped) == 2 and mapped.endswith(":"):
            mapped += "/"
    else:
        mapped = posix_windows_alias_to_drive_path(stripped)
        if mapped is None:
            return None
        mapped = mapped.rstrip("/")
        if len(mapped) == 2 and mapped.endswith(":"):
            mapped += "/"
    if _windows_has_dot_or_empty_component(mapped) or _windows_has_short_name_component(mapped):
        return None
    return mapped


def _parse_folder_guid(folder_guid: str) -> tuple[int, int, int, bytes] | None:
    hexed = folder_guid.strip("{}").split("-")
    if len(hexed) != 5:
        return None
    try:
        data4 = bytes.fromhex(hexed[3] + hexed[4])
    except ValueError:
        return None
    if len(data4) != 8:
        return None
    return int(hexed[0], 16), int(hexed[1], 16), int(hexed[2], 16), data4


def _sh_get_known_folder(folder_guid: str) -> str | None:
    """Resolve one Known Folder via a private ctypes handle.

    Binds SHGetKnownFolderPath / CoTaskMemFree on a dedicated WinDLL instance
    through WINFUNCTYPE. Does not mutate ctypes.windll.shell32 prototypes.
    """
    if not _is_windows_like():
        return None
    parsed = _parse_folder_guid(folder_guid)
    if parsed is None:
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8),
        ]

    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    except OSError:
        return None
    get_known = ctypes.WINFUNCTYPE(
        ctypes.HRESULT,
        ctypes.POINTER(GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    )(("SHGetKnownFolderPath", shell32))
    free = ctypes.WINFUNCTYPE(None, ctypes.c_void_p)(("CoTaskMemFree", ole32))
    data1, data2, data3, data4 = parsed
    folder_id = GUID(data1, data2, data3, (wintypes.BYTE * 8).from_buffer_copy(data4))
    path_ptr = ctypes.c_wchar_p()
    try:
        status = get_known(ctypes.byref(folder_id), 0, None, ctypes.byref(path_ptr))
    except (OSError, TypeError, ValueError):
        return None
    if status != 0 or not path_ptr.value:
        if path_ptr:
            free(path_ptr)
        return None
    try:
        value = path_ptr.value
    finally:
        free(path_ptr)
    if not value or "\x00" in value:
        return None
    return value


def _validated_known_folder(raw: str | None, *, required_suffix: str | None) -> str | None:
    if raw is None:
        return None
    drive_path = _drive_letter_windows_path(raw)
    if drive_path is None:
        return None
    if required_suffix:
        suffix = ntpath.normcase("\\" + required_suffix.replace("/", "\\").strip("\\"))
        if not _windows_lexical_key(drive_path).endswith(suffix):
            return None
    elif drive_path.replace("\\", "/").rstrip("/")[1:] == ":":
        return None
    return drive_path


def _windows_folder_snapshot() -> WindowsFolders:
    """Resolve every Windows prefix once. No C: fallback if a lookup fails."""
    return WindowsFolders(
        program_files=_validated_known_folder(
            _sh_get_known_folder(_FOLDERID_PROGRAM_FILES),
            required_suffix="Program Files",
        ),
        program_files_x86=_validated_known_folder(
            _sh_get_known_folder(_FOLDERID_PROGRAM_FILES_X86),
            required_suffix="Program Files (x86)",
        ),
        local_app_data=_validated_known_folder(
            _sh_get_known_folder(_FOLDERID_LOCAL_APP_DATA),
            required_suffix="AppData/Local",
        ),
        system32=_validated_known_folder(
            _sh_get_known_folder(_FOLDERID_SYSTEM),
            required_suffix="System32",
        ),
        profile=_validated_known_folder(_sh_get_known_folder(_FOLDERID_PROFILE), required_suffix=None),
    )


def windows_git_candidate_texts(folders: WindowsFolders | None = None) -> tuple[str, ...]:
    """Closed Windows candidate texts from one Known Folder snapshot."""
    snap = folders if folders is not None else _windows_folder_snapshot()
    candidates: list[str] = []
    if snap.program_files:
        candidates.extend(f"{snap.program_files.rstrip('/')}/{suffix}" for suffix in _WINDOWS_PF_GIT_SUFFIXES)
    if snap.program_files_x86:
        candidates.append(f"{snap.program_files_x86.rstrip('/')}/{_WINDOWS_PF86_GIT_SUFFIX}")
    if snap.local_app_data:
        candidates.append(f"{snap.local_app_data.rstrip('/')}/{_WINDOWS_LOCAL_GIT_SUFFIX}")
    return tuple(dict.fromkeys(candidates))


def canonical_windows_git_path(text: str, folders: WindowsFolders | None = None) -> str | None:
    """Return the closed-list Windows path for `text`, or None."""
    snap = folders if folders is not None else _windows_folder_snapshot()
    drive_path = _drive_letter_windows_path(text)
    if drive_path is None:
        return None
    if _windows_leaf_is_cmd_or_bat_shim(drive_path) or not _windows_leaf_is_git_exe(drive_path):
        return None
    key = _windows_lexical_key(drive_path)
    allowed = {_windows_lexical_key(item) for item in windows_git_candidate_texts(snap)}
    if key not in allowed:
        return None
    return drive_path


def _windows_probe_texts(candidate: str, folders: WindowsFolders) -> tuple[str, ...]:
    """Paths we may open for one closed candidate.

    Only the drive-letter form is opened, including on Cygwin/MSYS Python.
    Opening a Git Bash spelling on native Windows would touch
    `\\c\\Program Files\\...` on the current drive — a plantable location.
    """
    canonical = canonical_windows_git_path(candidate, folders)
    if canonical is None:
        return ()
    return (canonical,)


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


def _windows_path_has_reparse_in_chain(path: Path) -> bool:
    """Fail closed if the leaf or any parent is a symlink, junction, or reparse point."""
    current = path
    for _ in range(64):
        if _path_is_symlink(current) or _path_is_junction(current) or _path_is_reparse_point(current):
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent
    return True


def _passes_windows_trust_checks(path: Path) -> Path | None:
    """Apply the POSIX file/symlink/execute/realpath checks, adapted for Windows."""
    try:
        if _windows_leaf_is_cmd_or_bat_shim(os.fspath(path)) or not _windows_leaf_is_git_exe(os.fspath(path)):
            return None
        if _windows_path_has_reparse_in_chain(path):
            return None
        if not _path_is_file(path) or not _path_access_execute(path):
            return None
        resolved = _path_resolve_strict(path)
        if _windows_leaf_is_cmd_or_bat_shim(os.fspath(resolved)) or not _windows_leaf_is_git_exe(os.fspath(resolved)):
            return None
        return resolved
    except OSError:
        return None


def _trusted_windows_git_binary() -> Path:
    folders = _windows_folder_snapshot()
    for candidate in windows_git_candidate_texts(folders):
        for text in _windows_probe_texts(candidate, folders):
            if canonical_windows_git_path(text, folders) is None:
                continue
            accepted = _passes_windows_trust_checks(Path(text))
            if accepted is None:
                continue
            resolved_canonical = canonical_windows_git_path(os.fspath(accepted), folders)
            if resolved_canonical is None:
                continue
            return Path(resolved_canonical)
    raise RuntimeError("trusted absolute local Git is unavailable")


def _trusted_posix_git_binary() -> Path:
    """Resolve Git from trusted absolute macOS/Linux locations, never an ambient PATH shim."""
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


def windows_empty_hooks_directory() -> Path:
    """Empty directory Dex creates for Windows ``core.hooksPath``.

    On Windows, ``/dev/null`` is not the POSIX sink. Git treats hooksPath as a
    directory, so ``core.hooksPath=/dev/null`` can become ``<drive>:\\dev\\null``
    and run a planted ``pre-commit``. Autosave runs ``commit`` and ``update-ref``.
    """
    global _WINDOWS_HOOKS_DIR
    if _WINDOWS_HOOKS_DIR is not None and _WINDOWS_HOOKS_DIR.is_dir():
        return _WINDOWS_HOOKS_DIR
    created = Path(tempfile.mkdtemp(prefix="dex-git-hooks-"))
    _WINDOWS_HOOKS_DIR = created
    return created


def _hooks_path_config() -> str:
    if _is_windows_like():
        return f"core.hooksPath={windows_empty_hooks_directory().as_posix()}"
    return "core.hooksPath=/dev/null"


def _windows_home(folders: WindowsFolders) -> str:
    """USERPROFILE location from the Known Folder, else a validated USERPROFILE."""
    if folders.profile:
        return folders.profile
    return _drive_letter_windows_path(os.environ.get("USERPROFILE", "")) or ""


def _windows_path_dirs(git: Path, folders: WindowsFolders) -> tuple[str, ...]:
    """Only the trusted Git directory plus System32. Never /usr/bin or /bin."""
    dirs = [str(git.parent)]
    if folders.system32:
        dirs.append(folders.system32)
    return tuple(dict.fromkeys(dirs))


def git_env(*, git: Path | None = None, index_path: Path | None = None) -> dict[str, str]:
    """Return the closed baseline environment used by every Git consumer."""
    resolved = git if git is not None else trusted_git_binary()
    if _is_windows_like():
        folders = _windows_folder_snapshot()
        executable_dirs = _windows_path_dirs(resolved, folders)
        home = _windows_home(folders)
    else:
        executable_dirs = tuple(
            dict.fromkeys(
                (str(resolved.parent), str(Path(sys.executable).resolve().parent), "/usr/bin", "/bin")
            )
        )
        home = os.environ.get("HOME", "")
    env = {
        "PATH": os.pathsep.join(executable_dirs),
        "HOME": home,
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
    git = trusted_git_binary()
    command = [
        str(git),
        "-c",
        _hooks_path_config(),
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
        env=git_env(git=git, index_path=index_path),
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
