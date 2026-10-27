"""Client for the Dex Helper app (Calendar and Reminders).

Permission-bearing EventKit calls go through LaunchServices:

    open -W -n -a "Dex Helper.app" --args <op> <json-out> [json-in]

so the helper is the responsible app. Never spawn the helper binary as a
child of the MCP server for those calls. Titles and other event data stay
in vault temp JSON files, not argv.

The helper shares EventKit logic with the fallback scripts through
``core.utils.eventkit_ops``. Dev builds ad-hoc sign with ``codesign --sign -``.
Developer ID plus notarization is a later, separately approved release step.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

HELPER_VERSION = "1.0.0"
HELPER_BUNDLE_ID = "ai.heydex.DexHelper"
HELPER_APP_NAME = "Dex Helper.app"
HELPER_EXECUTABLE_NAME = "DexHelper"
HELPER_TIMEOUT_SECONDS = 120

_SCRIPT_DOMAIN = {
    "calendar_eventkit.py": "calendar",
    "reminders_eventkit.py": "reminders",
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


def vault_tmp_dir(vault_root: Path | None = None) -> Path:
    root = Path(vault_root) if vault_root is not None else _vault_root()
    return root / "System" / ".dex" / "tmp"


def _vault_root() -> Path:
    try:
        from core.paths import VAULT_ROOT
    except Exception:
        return Path.cwd()
    return Path(VAULT_ROOT)


def helper_executable_from_app(app_path: Path) -> Path:
    return app_path / "Contents" / "MacOS" / HELPER_EXECUTABLE_NAME


def app_bundle_from_path(path: Path) -> Path | None:
    current = path
    for candidate in (current, *current.parents):
        if candidate.name.endswith(".app"):
            return candidate
    return None


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
        if os.environ.get("DEX_HELPER_PATH"):
            return _first_existing(helper_search_paths(os.environ, vault_root))
        return None
    return _first_existing(helper_search_paths(None, vault_root))


def helper_app_bundle(env: Mapping[str, str] | None = None, vault_root: Path | None = None) -> Path | None:
    executable = helper_executable(env=env, vault_root=vault_root)
    if executable is None:
        return None
    return app_bundle_from_path(executable)


def _first_existing(paths: Sequence[Path]) -> Path | None:
    for path in paths:
        try:
            if path.is_file() and os.access(path, os.X_OK):
                return path
        except OSError:
            continue
    return None


def helper_is_available(env: Mapping[str, str] | None = None, vault_root: Path | None = None) -> bool:
    return helper_app_bundle(env=env, vault_root=vault_root) is not None


def helper_op_for_script(script_name: str, args: Sequence[str]) -> tuple[str, dict[str, Any]] | None:
    if script_name == "calendar_create_event.sh":
        return "calendar.create", {"args": [str(item) for item in args]}
    domain = _SCRIPT_DOMAIN.get(script_name)
    if domain is None or not args:
        return None
    command, *rest = [str(item) for item in args]
    return f"{domain}.{command}", {"args": rest}


def _write_temp_json(directory: Path, payload: Mapping[str, Any] | None) -> Path | None:
    if payload is None:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"helper-{uuid.uuid4().hex}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def open_helper_argv(app: Path, op: str, out_path: Path, in_path: Path | None = None) -> list[str]:
    argv = ["open", "-W", "-n", "-a", str(app), "--args", op, str(out_path)]
    if in_path is not None:
        argv.append(str(in_path))
    return argv


def run_helper_op(
    op: str,
    payload: Mapping[str, Any] | None = None,
    *,
    timeout: int = HELPER_TIMEOUT_SECONDS,
    vault_root: Path | None = None,
) -> tuple[bool, str] | None:
    """Launch the helper through LaunchServices. Returns None if it cannot start."""
    app = helper_app_bundle(vault_root=vault_root)
    if app is None:
        return None
    tmp = vault_tmp_dir(vault_root)
    tmp.mkdir(parents=True, exist_ok=True)
    out_path = tmp / f"helper-out-{uuid.uuid4().hex}.json"
    out_path.write_text("", encoding="utf-8")
    out_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    in_path = _write_temp_json(tmp, payload)
    command = open_helper_argv(app, op, out_path, in_path)
    try:
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
            return False, f"Dex Helper timed out after {timeout} seconds"
        except OSError:
            return None
        try:
            output = out_path.read_text(encoding="utf-8").strip()
        except OSError:
            output = ""
        if result.returncode == 0:
            return True, output
        return False, (
            output
            or result.stderr.strip()
            or result.stdout.strip()
            or f"Exit code: {result.returncode}"
        )
    finally:
        for path in (out_path, in_path):
            if path is None:
                continue
            try:
                path.unlink()
            except OSError:
                pass


def run_helper(
    args: Sequence[str],
    *,
    timeout: int = HELPER_TIMEOUT_SECONDS,
    vault_root: Path | None = None,
) -> tuple[bool, str] | None:
    if not args:
        return None
    op, *rest = [str(item) for item in args]
    payload = {"args": rest} if rest else None
    return run_helper_op(op, payload, timeout=timeout, vault_root=vault_root)


def run_mapped_helper(
    script_name: str,
    args: Sequence[str],
    *,
    timeout: int = HELPER_TIMEOUT_SECONDS,
    vault_root: Path | None = None,
) -> tuple[bool, str] | None:
    """Run the helper for a mapped script through LaunchServices.

    Returns None when the helper is not installed so the caller can fall
    back. A helper that starts and then reports a Calendar/Reminders error
    is a real result — do not fall back after that.
    """
    mapped = helper_op_for_script(script_name, args)
    if mapped is None:
        return None
    op, payload = mapped
    return run_helper_op(op, payload, timeout=timeout, vault_root=vault_root)


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


def read_bundle_id(app_path: Path) -> str | None:
    plist = app_path / "Contents" / "Info.plist"
    if not plist.is_file():
        return None
    try:
        text = plist.read_text(encoding="utf-8")
    except OSError:
        return None
    key = "<key>CFBundleIdentifier</key>"
    if key not in text:
        return None
    after = text.split(key, 1)[1]
    start = after.find("<string>")
    end = after.find("</string>")
    if start == -1 or end == -1 or end <= start:
        return None
    return after[start + len("<string>"):end].strip() or None


def read_signing_identity(app_path: Path) -> dict[str, str | None]:
    """Return adhoc / developer_id / unsigned and Team ID when readable."""
    identity: dict[str, str | None] = {
        "kind": "unsigned",
        "team_id": None,
        "bundle_id": read_bundle_id(app_path),
    }
    if sys.platform != "darwin" or not shutil.which("codesign"):
        return identity
    try:
        result = subprocess.run(
            ["codesign", "-dv", "--verbose=2", str(app_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return identity
    text = f"{result.stdout}\n{result.stderr}"
    if "Signature=adhoc" in text or "Signature=Adhoc" in text or "TeamIdentifier=-" in text:
        identity["kind"] = "adhoc"
        identity["team_id"] = "-"
        return identity
    for line in text.splitlines():
        if line.startswith("TeamIdentifier="):
            team = line.split("=", 1)[1].strip()
            identity["team_id"] = team
            identity["kind"] = "developer_id" if team and team != "-" else "adhoc"
    if "Authority=Developer ID Application" in text:
        identity["kind"] = "developer_id"
    elif identity["kind"] == "unsigned" and "Authority=" in text:
        identity["kind"] = "developer_id"
    return identity


def identities_match(source_app: Path, destination_app: Path) -> bool:
    if not destination_app.is_dir():
        return True
    source = read_signing_identity(source_app)
    dest = read_signing_identity(destination_app)
    return source.get("bundle_id") == dest.get("bundle_id") and source.get("team_id") == dest.get("team_id")


def install_or_update_helper(
    *,
    source_app: Path | None = None,
    destination_app: Path | None = None,
    vault_root: Path | None = None,
) -> dict[str, object]:
    """Copy a built helper into the install location when newer and same identity."""
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
                "core/macos/dex-helper/build.sh (it ad-hoc signs). "
                "Developer ID signing is a later, separately approved release step."
            ),
        }

    source_version = read_installed_version(source) or helper_source_version()
    installed_version = read_installed_version(destination)
    source_identity = read_signing_identity(source)
    if destination.is_dir() and not identities_match(source, destination):
        dest_identity = read_signing_identity(destination)
        return {
            "ok": False,
            "skipped": True,
            "reason": "identity_mismatch",
            "message": (
                "Dex Helper is already installed with a different identity "
                f"(bundle {dest_identity.get('bundle_id')}, "
                f"Team ID {dest_identity.get('team_id')}). "
                "Replace it only after you are ready to grant Calendar and "
                "Reminders again."
            ),
            "path": str(destination),
        }
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
    _write_dex_root(destination, vault_root)

    record = {
        "ok": True,
        "skipped": False,
        "reason": "installed" if installed_version is None else "updated",
        "version": source_version,
        "path": str(destination),
        "signed": source_identity.get("kind") != "unsigned",
        "signing": source_identity.get("kind"),
        "team_id": source_identity.get("team_id"),
        "bundle_id": HELPER_BUNDLE_ID,
    }
    _write_install_record(record, vault_root)
    return record


def _write_dex_root(app_path: Path, vault_root: Path | None) -> None:
    marker = app_path / "Contents" / "Resources" / "dex-root.txt"
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(_vault_root() if vault_root is None else Path(vault_root)) + "\n", encoding="utf-8")
    except OSError:
        return


def _write_install_record(record: Mapping[str, object], vault_root: Path | None) -> None:
    root = Path(vault_root) if vault_root is not None else _vault_root()
    path = root / "System" / ".dex" / "helpers" / "installed.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(record), indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def build_unsigned_helper(*, output_dir: Path | None = None) -> dict[str, object]:
    """Run the helper build script (ad-hoc sign on a Mac). Skips cleanly off macOS."""
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
    env.setdefault("DEX_HELPER_CORE_ROOT", str(Path(__file__).resolve().parents[2]))
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
    identity = read_signing_identity(built) if built.is_dir() else {"kind": "unsigned"}
    return {
        "ok": True,
        "skipped": False,
        "reason": "built",
        "path": str(built),
        "signed": identity.get("kind") != "unsigned",
        "signing": identity.get("kind"),
        "version": helper_source_version(),
    }


def doctor_status_line(vault_root: Path | None = None) -> str:
    """One Doctor line: installed or not, signing identity, auth status."""
    app = helper_app_bundle(vault_root=vault_root)
    if app is None:
        return "Dex Helper: not installed"
    identity = read_signing_identity(app)
    kind_raw = identity.get("kind") or "unsigned"
    kind = {"developer_id": "Developer ID", "adhoc": "adhoc", "unsigned": "unsigned"}.get(
        kind_raw, kind_raw
    )
    auth = {"calendar": "unknown", "reminders": "unknown"}
    status = run_helper_op("status", vault_root=vault_root)
    if status is not None and status[0]:
        try:
            parsed = json.loads(status[1])
            if isinstance(parsed, dict):
                auth["calendar"] = str(parsed.get("calendar") or "unknown")
                auth["reminders"] = str(parsed.get("reminders") or "unknown")
        except json.JSONDecodeError:
            pass
    return (
        f"Dex Helper: installed, {kind}, "
        f"Calendar {auth['calendar']}, Reminders {auth['reminders']}"
    )


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
        print(doctor_status_line())
        return 0
    print("Usage: python -m core.utils.macos_privacy_helper [status|install]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
