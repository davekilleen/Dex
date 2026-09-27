"""Locate the Granola desktop app and its user-data directory.

Dex meeting sync uses Granola's official public API. This module does **not**
read Granola's local data files. It only answers "is Granola on this machine,
and where?" so installers, onboarding, and the integration concierge can detect
the app on Windows as well as macOS.

Windows app path (stable across current installer versions):
  %LOCALAPPDATA%\\Programs\\@granolaelectron\\Granola.exe
Windows data directory (Electron userData):
  %APPDATA%\\Granola

Linux is a no-op: Dex does not look for a desktop Granola install there.

Call from an installer::

    python3 -m core.integrations.granola_paths --json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable, Mapping, Sequence

logger = logging.getLogger("dex.granola_paths")

WINDOWS_PLATFORMS = frozenset({"win32", "windows", "cygwin", "msys", "mingw"})
DARWIN_PLATFORMS = frozenset({"darwin", "macos", "mac"})
OVERRIDE_APP_ENV = "DEX_GRANOLA_APP"
OVERRIDE_DATA_ENV = "DEX_GRANOLA_DATA"
DEBUG_ENV = "DEX_GRANOLA_PATHS_DEBUG"

# Electron/Squirrel per-user default, confirmed on Granola 7.128.0 and 7.580.0.
WINDOWS_APP_RELATIVES: tuple[tuple[str, ...], ...] = (
    ("Programs", "@granolaelectron", "Granola.exe"),
    ("Programs", "Granola", "Granola.exe"),
)
WINDOWS_MACHINE_APP_RELATIVES: tuple[tuple[str, ...], ...] = (
    ("@granolaelectron", "Granola.exe"),
    ("Granola", "Granola.exe"),
)


@dataclass(frozen=True)
class PathProbe:
    """One candidate that was considered, and why it was kept or skipped."""

    kind: str
    path: str
    source: str
    ok: bool
    reason: str


@dataclass
class GranolaLocations:
    """Resolved Granola locations for one platform."""

    platform: str
    installed: bool
    app_found: bool
    data_found: bool
    app_path: str | None = None
    data_path: str | None = None
    app_path_posix: str | None = None
    data_path_posix: str | None = None
    tried: list[PathProbe] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["tried"] = [asdict(item) for item in self.tried]
        return payload


KindFn = Callable[[str], str | None]


def classify_platform(raw: str | None = None) -> str:
    """Map sys.platform / platform.system() / uname-style values to a family.

    Git Bash reports OSTYPE=cygwin, and Cygwin/MSYS Python reports cygwin/msys,
    but Granola is still a native Windows app. Treat those as Windows.
    """
    value = (raw or sys.platform or "").strip().lower()
    if value in WINDOWS_PLATFORMS or value.startswith(("cygwin", "msys", "mingw")):
        return "win32"
    if value in DARWIN_PLATFORMS:
        return "darwin"
    if value.startswith("linux"):
        return "linux"
    return "linux"


def _enable_debug_logging(env: Mapping[str, str]) -> None:
    if not str(env.get(DEBUG_ENV, "")).strip():
        return
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(logging.DEBUG)


def sanitize_env_value(name: str, value: str | None) -> tuple[str | None, str | None]:
    """Return (clean_value, reject_reason). Never expand nested %VAR% tokens."""
    if value is None:
        return None, f"missing env {name}"
    cleaned = str(value).strip()
    if not cleaned:
        return None, f"empty env {name}"
    if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        return None, f"rejected env {name}: control characters"
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1].strip()
        if not cleaned:
            return None, f"empty env {name}"
    if cleaned in {".", ".."}:
        return None, f"rejected env {name}: relative path"
    return cleaned, None


def looks_posix_absolute(value: str) -> bool:
    """Git Bash / test hosts may hand us a ``/c/<name>/...`` form instead of a drive letter."""
    return value.startswith("/") and not value.startswith("//")


def join_os_path(base: str, *parts: str) -> str:
    if looks_posix_absolute(base):
        return posix_join(base, *parts) if parts else base
    return win_join(base, *parts)


def win_join(base: str, *parts: str) -> str:
    """Join Windows path parts, collapse ``.`` / ``..``, and keep UNC roots."""
    if len(base) == 2 and base[1] == ":" and base[0].isalpha():
        base = f"{base}\\"
    path = PureWindowsPath(base)
    for part in parts:
        path /= part
    parts_list = list(path.parts)
    if not parts_list:
        return str(path)
    root = parts_list[0]
    collapsed: list[str] = []
    for part in parts_list[1:]:
        if part in {"", "."}:
            continue
        if part == "..":
            if collapsed:
                collapsed.pop()
            continue
        collapsed.append(part)
    return str(PureWindowsPath(root, *collapsed))


def posix_join(base: str, *parts: str) -> str:
    path = Path(base)
    for part in parts:
        path /= part
    return str(path)


def windows_to_git_bash(win_path: str) -> str | None:
    """Translate a Windows path to the Git Bash ``/c/...`` form.

    Cygwin's ``/cygdrive/c/...`` form is a sibling alias used only for
    existence probes, not as the returned installer path.
    """
    if not win_path:
        return None
    normalized = win_path.replace("/", "\\")
    if normalized.startswith("\\\\"):
        return "//" + normalized[2:].replace("\\", "/")
    if len(normalized) >= 2 and normalized[1] == ":" and normalized[0].isalpha():
        drive = normalized[0].lower()
        rest = normalized[2:].replace("\\", "/").lstrip("/")
        return f"/{drive}/{rest}" if rest else f"/{drive}"
    return None


def windows_posix_aliases(win_path: str) -> tuple[str, ...]:
    git_bash = windows_to_git_bash(win_path)
    if not git_bash:
        return ()
    aliases = [git_bash]
    if git_bash.startswith("/") and len(git_bash) >= 2 and git_bash[1].isalpha() and (
        len(git_bash) == 2 or git_bash[2] == "/"
    ):
        aliases.append("/cygdrive" + git_bash)
    return tuple(dict.fromkeys(aliases))


def default_kind(path: str) -> str | None:
    """Return ``file``, ``dir``, or None. Tries Windows and Git Bash/Cygwin aliases."""
    candidates = (path, *windows_posix_aliases(path))
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            probe = Path(candidate)
            if probe.is_dir():
                return "dir"
            if probe.is_file():
                return "file"
        except OSError as error:
            logger.debug("probe failed for %s: %s", candidate, error)
            continue
    return None


def _first_env(
    env: Mapping[str, str], names: Sequence[str]
) -> tuple[str | None, str, str | None]:
    """Return (value, name_used, reject_reason_of_last_empty)."""
    last_reason = None
    last_name = names[0] if names else ""
    for name in names:
        value, reason = sanitize_env_value(name, env.get(name))
        if value:
            return value, name, None
        last_reason = reason
        last_name = name
    return None, last_name, last_reason


def _userprofile_home(env: Mapping[str, str]) -> tuple[str | None, str, str | None]:
    profile, name, reason = _first_env(env, ("USERPROFILE", "HOME"))
    if profile:
        return profile, name, None
    drive, _, drive_reason = _first_env(env, ("HOMEDRIVE",))
    path, _, path_reason = _first_env(env, ("HOMEPATH",))
    if drive and path:
        return join_os_path(drive, path.lstrip("\\/")), "HOMEDRIVE+HOMEPATH", None
    return None, "USERPROFILE", reason or drive_reason or path_reason


def _dedupe(paths: Iterable[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Dedupe (path, source, kind) by case-folded path, keeping first."""
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for path, source, kind in paths:
        key = path.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append((path, source, kind))
    return out


def _windows_app_candidates(env: Mapping[str, str]) -> list[tuple[str, str, str]]:
    candidates: list[tuple[str, str, str]] = []

    override, reason = sanitize_env_value(OVERRIDE_APP_ENV, env.get(OVERRIDE_APP_ENV))
    if override:
        candidates.append((join_os_path(override), f"env {OVERRIDE_APP_ENV}", "app"))
    elif reason and env.get(OVERRIDE_APP_ENV) is not None:
        logger.debug("skip app override: %s", reason)

    local, local_name, local_reason = _first_env(env, ("LOCALAPPDATA",))
    if not local:
        home, home_name, home_reason = _userprofile_home(env)
        if home:
            local = join_os_path(home, "AppData", "Local")
            local_name = f"{home_name}\\AppData\\Local"
            local_reason = None
        else:
            logger.debug("no LOCALAPPDATA: %s", local_reason or home_reason)
    if local:
        for relative in WINDOWS_APP_RELATIVES:
            candidates.append(
                (
                    join_os_path(local, *relative),
                    f"{local_name}\\{'\\'.join(relative)}",
                    "app",
                )
            )

    for env_name in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        root, used, reason = _first_env(env, (env_name,))
        if not root:
            logger.debug("skip %s: %s", env_name, reason)
            continue
        for relative in WINDOWS_MACHINE_APP_RELATIVES:
            candidates.append(
                (join_os_path(root, *relative), f"{used}\\{'\\'.join(relative)}", "app")
            )

    return _dedupe(candidates)


def _windows_data_candidates(env: Mapping[str, str]) -> list[tuple[str, str, str]]:
    candidates: list[tuple[str, str, str]] = []

    override, reason = sanitize_env_value(OVERRIDE_DATA_ENV, env.get(OVERRIDE_DATA_ENV))
    if override:
        candidates.append((join_os_path(override), f"env {OVERRIDE_DATA_ENV}", "data"))
    elif reason and env.get(OVERRIDE_DATA_ENV) is not None:
        logger.debug("skip data override: %s", reason)

    roaming, roaming_name, roaming_reason = _first_env(env, ("APPDATA",))
    if roaming:
        candidates.append((join_os_path(roaming, "Granola"), f"{roaming_name}\\Granola", "data"))
    else:
        logger.debug("no APPDATA: %s", roaming_reason)

    home, home_name, home_reason = _userprofile_home(env)
    if home:
        # Physical default even when APPDATA is redirected (OneDrive, roaming profiles).
        candidates.append(
            (
                join_os_path(home, "AppData", "Roaming", "Granola"),
                f"{home_name}\\AppData\\Roaming\\Granola",
                "data",
            )
        )
        candidates.append(
            (
                join_os_path(home, "AppData", "Local", "Granola"),
                f"{home_name}\\AppData\\Local\\Granola",
                "data",
            )
        )
    else:
        logger.debug("no user home for data fallbacks: %s", home_reason)

    local, local_name, local_reason = _first_env(env, ("LOCALAPPDATA",))
    if local:
        candidates.append(
            (join_os_path(local, "Granola"), f"{local_name}\\Granola", "data")
        )
    else:
        logger.debug("no LOCALAPPDATA for data fallback: %s", local_reason)

    return _dedupe(candidates)


def _darwin_app_candidates(
    env: Mapping[str, str], home: str | None
) -> list[tuple[str, str, str]]:
    candidates: list[tuple[str, str, str]] = []
    override, reason = sanitize_env_value(OVERRIDE_APP_ENV, env.get(OVERRIDE_APP_ENV))
    if override:
        candidates.append((override, f"env {OVERRIDE_APP_ENV}", "app"))
    elif reason and env.get(OVERRIDE_APP_ENV) is not None:
        logger.debug("skip app override: %s", reason)
    candidates.append(("/Applications/Granola.app", "/Applications/Granola.app", "app"))
    if home:
        candidates.append(
            (
                posix_join(home, "Applications", "Granola.app"),
                "~/Applications/Granola.app",
                "app",
            )
        )
    return _dedupe(candidates)


def _darwin_data_candidates(
    env: Mapping[str, str], home: str | None
) -> list[tuple[str, str, str]]:
    candidates: list[tuple[str, str, str]] = []
    override, reason = sanitize_env_value(OVERRIDE_DATA_ENV, env.get(OVERRIDE_DATA_ENV))
    if override:
        candidates.append((override, f"env {OVERRIDE_DATA_ENV}", "data"))
    elif reason and env.get(OVERRIDE_DATA_ENV) is not None:
        logger.debug("skip data override: %s", reason)
    if home:
        candidates.append(
            (
                posix_join(home, "Library", "Application Support", "Granola"),
                "~/Library/Application Support/Granola",
                "data",
            )
        )
    else:
        logger.debug("no HOME for macOS Granola data directory")
    return _dedupe(candidates)


def _probe(
    path: str,
    source: str,
    kind: str,
    kind_of: KindFn,
    *,
    expect: str,
) -> PathProbe:
    found = kind_of(path)
    if found is None:
        probe = PathProbe(kind, path, source, False, "missing")
    elif found != expect:
        probe = PathProbe(kind, path, source, False, f"not a {expect}")
    else:
        probe = PathProbe(kind, path, source, True, "found")
    logger.debug(
        "tried %s %s (%s): %s",
        kind,
        path,
        source,
        probe.reason,
    )
    return probe


def detect_granola(
    *,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    kind: KindFn | None = None,
    home: str | None = None,
) -> GranolaLocations:
    """Resolve Granola app and data locations for the given platform.

    ``kind(path)`` returns ``"file"``, ``"dir"``, or ``None``. Tests inject a
    fake filesystem; production uses :func:`default_kind`.
    """
    env = dict(os.environ if env is None else env)
    _enable_debug_logging(env)
    family = classify_platform(platform)
    kind_of = kind or default_kind
    tried: list[PathProbe] = []

    if family == "linux":
        logger.debug("linux: Granola desktop detection is a no-op")
        return GranolaLocations(
            platform="linux",
            installed=False,
            app_found=False,
            data_found=False,
            tried=tried,
        )

    if home is None:
        home_value, _reason = sanitize_env_value("HOME", env.get("HOME"))
        home = home_value

    app_path = None
    data_path = None

    if family == "win32":
        app_expect = "file"
        data_expect = "dir"
        app_candidates = _windows_app_candidates(env)
        data_candidates = _windows_data_candidates(env)
    else:
        app_expect = "dir"
        data_expect = "dir"
        app_candidates = _darwin_app_candidates(env, home)
        data_candidates = _darwin_data_candidates(env, home)

    for path, source, kind_name in app_candidates:
        probe = _probe(path, source, kind_name, kind_of, expect=app_expect)
        tried.append(probe)
        if probe.ok and app_path is None:
            app_path = probe.path

    for path, source, kind_name in data_candidates:
        probe = _probe(path, source, kind_name, kind_of, expect=data_expect)
        tried.append(probe)
        if probe.ok and data_path is None:
            data_path = probe.path

    app_found = app_path is not None
    data_found = data_path is not None
    # Windows: the data directory is enough when the exe was installed to a
    # custom path. macOS keeps the historical rule: the .app bundle must exist.
    installed = app_found or (family == "win32" and data_found)

    result = GranolaLocations(
        platform=family,
        installed=installed,
        app_found=app_found,
        data_found=data_found,
        app_path=app_path,
        data_path=data_path,
        app_path_posix=windows_to_git_bash(app_path) if family == "win32" and app_path else None,
        data_path_posix=windows_to_git_bash(data_path) if family == "win32" and data_path else None,
        tried=tried,
    )
    logger.debug(
        "granola detect platform=%s installed=%s app=%s data=%s",
        family,
        installed,
        app_path,
        data_path,
    )
    return result


def check_granola_status(
    *,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    kind: KindFn | None = None,
    home: str | None = None,
) -> dict[str, object]:
    """Onboarding-shaped status dict used by ``check_granola()``."""
    locations = detect_granola(platform=platform, env=env, kind=kind, home=home)
    if locations.installed:
        payload: dict[str, object] = {
            "installed": True,
            "app_found": locations.app_found,
            "path": locations.app_path or locations.data_path,
            "setup": "/granola-setup",
        }
        if locations.data_path:
            payload["data_path"] = locations.data_path
        return payload
    return {
        "installed": False,
        "app_found": False,
        "optional": True,
        "setup": "/granola-setup",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Locate the Granola desktop app and its user-data directory."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="Print the detection result as JSON (default).",
    )
    parser.add_argument(
        "--platform",
        help="Override platform detection (win32, darwin, linux, cygwin).",
    )
    args = parser.parse_args(argv)
    locations = detect_granola(platform=args.platform)
    json.dump(locations.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if locations.installed else 1


if __name__ == "__main__":
    raise SystemExit(main())
