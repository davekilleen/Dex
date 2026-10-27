"""Client for the unsigned Dex Helper app (Calendar and Reminders).

The helper is a small Mac app with its own identity so the Calendar and
Reminders permission ask can appear when Dex is running inside VS Code or
the Claude app. Signing that app is a later, separately approved release
step — this module works with an unsigned local build and falls back to
the existing Python EventKit / AppleScript scripts when the helper is
missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

HELPER_VERSION = "1.0.0"
HELPER_BUNDLE_ID = "ai.heydex.DexHelper"
HELPER_APP_NAME = "Dex Helper.app"
HELPER_EXECUTABLE_NAME = "DexHelper"
HELPER_TIMEOUT_SECONDS = 120

_SCRIPT_DOMAIN = {
    "calendar_eventkit.py": "calendar",
    "reminders_eventkit.py": "reminders",
}

_SCRIPT_FIXED_COMMAND = {
    "calendar_create_event.sh": ("calendar", "create"),
}


def helper_source_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "macos" / "dex-helper"


def helper_source_version() -> str:
    version_file = helper_source_dir() / "VERSION"
    try:
        text = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return HELPER_VERSION
    return text or HELPER_VERSION


def default_install_app_path() -> Path:
    return Path.home() / "Applications" / HELPER_APP_NAME


def vault_install_app_path(vault_root: Path | None = None) -> Path:
    root = Path(vault_root) if vault_root is not None else _vault_root()
    return root / "System" / ".dex" / "helpers" / HELPER_APP_NAME


def _vault_root() -> Path:
    try:
        from core.paths import VAULT_ROOT
    except Exception:
        return Path.cwd()
    return Path(VAULT_ROOT)


def helper_executable_from_app(app_path: Path) -> Path:
    return app_path / "Contents" / "MacOS" / HELPER_EXECUTABLE_NAME


def _env_helper_path(env: Mapping[str, str] | None = None) -> Path | None:
    environment = os.environ if env is None else env
    raw = (environment.get("DEX_HELPER_PATH") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.name == HELPER_EXECUTABLE_NAME:
        return path
    if path.name.endswith(".app"):
        return helper_executable_from_app(path)
    candidate = path / HELPER_APP_NAME
    if candidate.is_dir():
        return helper_executable_from_app(candidate)
    return path


def helper_search_paths(env: Mapping[str, str] | None = None, vault_root: Path | None = None) -> list[Path]:
    paths: list[Path] = []
    env_path = _env_helper_path(env)
    if env_path is not None:
        paths.append(env_path)
    paths.append(helper_executable_from_app(default_install_app_path()))
    paths.append(helper_executable_from_app(Path("/Applications") / HELPER_APP_NAME))
    paths.append(helper_executable_from_app(vault_install_app_path(vault_root)))
    seen: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.append(path)
    return seen


def helper_executable(env: Mapping[str, str] | None = None, vault_root: Path | None = None) -> Path | None:
    if env is not None:
        return _first_existing(helper_search_paths(env, vault_root))
    if sys.platform != "darwin":
        # Linux/Windows never run the Mac app unless a test points at a stub.
        if os.environ.get("DEX_HELPER_PATH"):
            return _first_existing(helper_search_paths(os.environ, vault_root))
        return None
    return _first_existing(helper_search_paths(None, vault_root))


def _first_existing(paths: Sequence[Path]) -> Path | None:
    for path in paths:
        try:
            if path.is_file() and os.access(path, os.X_OK):
                return path
        except OSError:
            continue
    return None


def helper_is_available(env: Mapping[str, str] | None = None, vault_root: Path | None = None) -> bool:
    return helper_executable(env=env, vault_root=vault_root) is not None


def helper_argv(script_name: str, args: Sequence[str]) -> list[str] | None:
    """Return helper argv for a calendar/reminders script, or None to fall back."""
    executable = helper_executable()
    if executable is None:
        return None
    if script_name in _SCRIPT_FIXED_COMMAND:
        domain, command = _SCRIPT_FIXED_COMMAND[script_name]
        return [str(executable), domain, command, *args]
    domain = _SCRIPT_DOMAIN.get(script_name)
    if domain is None:
        return None
    return [str(executable), domain, *args]


def run_helper(
    args: Sequence[str],
    *,
    timeout: int = HELPER_TIMEOUT_SECONDS,
) -> tuple[bool, str] | None:
    executable = helper_executable()
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [str(executable), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return False, f"Dex Helper timed out after {timeout} seconds"
    except OSError:
        return None
    if result.returncode == 0:
        return True, result.stdout.strip()
    return False, (
        result.stderr.strip()
        or result.stdout.strip()
        or f"Exit code: {result.returncode}"
    )


def run_mapped_helper(
    script_name: str,
    args: Sequence[str],
    *,
    timeout: int = HELPER_TIMEOUT_SECONDS,
) -> tuple[bool, str] | None:
    """Run the helper for a mapped script.

    Returns None when the helper is not installed so the caller can fall
    back to the existing Python or AppleScript path. A helper that starts
    and then reports a Calendar/Reminders error is a real result — do not
    fall back after that, or the editor identity would be asked instead.
    """
    command = helper_argv(script_name, args)
    if command is None:
        return None
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return False, f"Script '{script_name}' timed out after {timeout} seconds"
    except OSError:
        return None
    if result.returncode == 0:
        return True, result.stdout.strip()
    return False, (
        result.stderr.strip()
        or result.stdout.strip()
        or f"Exit code: {result.returncode}"
    )


def compare_versions(left: str, right: str) -> int:
    """Return 1 if left > right, 0 if equal, -1 if left < right."""
    def parts(value: str) -> list[int]:
        tokens: list[int] = []
        for piece in value.split("."):
            try:
                tokens.append(int(piece))
            except ValueError:
                tokens.append(0)
        return tokens

    a = parts(left)
    b = parts(right)
    width = max(len(a), len(b))
    a.extend([0] * (width - len(a)))
    b.extend([0] * (width - len(b)))
    if a > b:
        return 1
    if a < b:
        return -1
    return 0


def read_installed_version(app_path: Path) -> str | None:
    plist = app_path / "Contents" / "Info.plist"
    if not plist.is_file():
        return None
    try:
        text = plist.read_text(encoding="utf-8")
    except OSError:
        return None
    key = "<key>CFBundleShortVersionString</key>"
    if key not in text:
        return None
    after = text.split(key, 1)[1]
    start = after.find("<string>")
    end = after.find("</string>")
    if start == -1 or end == -1 or end <= start:
        return None
    return after[start + len("<string>"):end].strip() or None


def install_or_update_helper(
    *,
    source_app: Path | None = None,
    destination_app: Path | None = None,
    vault_root: Path | None = None,
) -> dict[str, object]:
    """Copy a built unsigned helper into the install location when newer."""
    if sys.platform != "darwin" and source_app is None:
        return {
            "ok": True,
            "skipped": True,
            "reason": "not_macos",
            "message": "The Calendar and Reminders helper is Mac-only.",
        }

    source = source_app if source_app is not None else (
        helper_source_dir() / "build" / HELPER_APP_NAME
    )
    destination = destination_app if destination_app is not None else default_install_app_path()
    if not source.is_dir():
        return {
            "ok": False,
            "skipped": True,
            "reason": "source_missing",
            "message": (
                "The Dex Helper app is not built yet. On a Mac, run "
                "core/macos/dex-helper/build.sh to make an unsigned copy. "
                "Signing is a later, separately approved release step."
            ),
        }

    source_version = read_installed_version(source) or helper_source_version()
    installed_version = read_installed_version(destination)
    if installed_version and compare_versions(source_version, installed_version) <= 0:
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_current",
            "version": installed_version,
            "path": str(destination),
        }

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=True)

    record = {
        "ok": True,
        "skipped": False,
        "reason": "installed" if installed_version is None else "updated",
        "version": source_version,
        "path": str(destination),
        "signed": False,
        "bundle_id": HELPER_BUNDLE_ID,
    }
    _write_install_record(record, vault_root)
    return record


def _write_install_record(record: Mapping[str, object], vault_root: Path | None) -> None:
    root = Path(vault_root) if vault_root is not None else _vault_root()
    path = root / "System" / ".dex" / "helpers" / "installed.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        import json

        path.write_text(json.dumps(dict(record), indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def build_unsigned_helper(*, output_dir: Path | None = None) -> dict[str, object]:
    """Run the unsigned build script. Skips cleanly off macOS."""
    script = helper_source_dir() / "build.sh"
    if sys.platform != "darwin":
        return {
            "ok": True,
            "skipped": True,
            "reason": "not_macos",
            "message": "The Calendar and Reminders helper builds only on a Mac.",
        }
    if not script.is_file():
        return {"ok": False, "skipped": True, "reason": "build_script_missing"}
    env = os.environ.copy()
    if output_dir is not None:
        env["DEX_HELPER_BUILD_DIR"] = str(output_dir)
    try:
        result = subprocess.run(
            ["/bin/bash", str(script)],
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "skipped": False, "reason": "build_failed", "error": str(exc)}
    if result.returncode != 0:
        return {
            "ok": False,
            "skipped": False,
            "reason": "build_failed",
            "error": (result.stderr or result.stdout).strip(),
        }
    if "skipping" in (result.stdout + result.stderr).lower():
        return {
            "ok": True,
            "skipped": True,
            "reason": "toolchain_missing",
            "message": result.stdout.strip(),
        }
    built = Path(env.get("DEX_HELPER_BUILD_DIR", helper_source_dir() / "build")) / HELPER_APP_NAME
    return {
        "ok": True,
        "skipped": False,
        "reason": "built",
        "path": str(built),
        "signed": False,
        "version": helper_source_version(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "status"
    if command == "install":
        built = build_unsigned_helper()
        if built.get("skipped") and built.get("reason") == "not_macos":
            print(built["message"])
            return 0
        if not built.get("ok"):
            print(built.get("error") or built.get("message") or "Could not build Dex Helper.")
            return 0 if built.get("skipped") else 1
        if built.get("skipped"):
            print(built.get("message") or "Dex Helper build skipped.")
            return 0
        result = install_or_update_helper(source_app=Path(str(built["path"])))
        print(result.get("message") or result.get("reason"))
        return 0 if result.get("ok") else 1
    if command == "status":
        executable = helper_executable()
        print(
            f"available={executable is not None} "
            f"version={helper_source_version()} "
            f"path={executable or ''}"
        )
        return 0
    print("Usage: python -m core.utils.macos_privacy_helper [status|install]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
