"""Client for the Dex Helper app (Calendar and Reminders).

Permission-bearing EventKit calls go through LaunchServices:

    open -W -n -a "Dex Helper.app" --args <op> <json-out> [json-in]

so the helper is the responsible app. Never spawn the helper binary as a
child of the MCP server for those calls. Titles and other event data stay
in vault temp JSON files, not argv.

The helper is a compiled native app. Dex never writes inside a signed
bundle after copying it. People using Dex install the signed copy pinned
in ``release-manifest.json``. ``DEX_HELPER_DEV=1`` is the local ad-hoc
build path for people building Dex.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

HELPER_VERSION = "1.1.0"
MIN_HELPER_VERSION = "1.1.0"
HELPER_BUNDLE_ID = "ai.heydex.DexHelper"
HELPER_APP_NAME = "Dex Helper.app"
HELPER_EXECUTABLE_NAME = "DexHelper"
HELPER_TEAM_ID = "6WVLPMNTL5"
HELPER_TIMEOUT_SECONDS = 120
HELPER_DOWNLOAD_LIMIT_BYTES = 20 * 1024 * 1024

_SCRIPT_DOMAIN = {
    "calendar_eventkit.py": "calendar",
    "reminders_eventkit.py": "reminders",
}

HELPER_MISSING_MESSAGE = (
    "Dex Helper is not installed. Run /calendar-setup, or run /dex-update if you already use Dex."
)
HELPER_SCRIPT_MESSAGE = (
    "This Dex Helper is the old script copy and cannot ask for Calendar. "
    "Install the signed Dex Helper from this Dex release."
)
HELPER_UNSIGNED_MESSAGE = (
    "This Dex Helper is not the trusted signed copy. Install the one from the Dex release."
)
HELPER_TOO_OLD_MESSAGE = "Dex Helper is too old for this Dex. Run /dex-update."
HELPER_NOT_IN_RELEASE_MESSAGE = "The signed Dex Helper is not in this Dex yet."
HELPER_QUARANTINE_MESSAGE = (
    "Right-click Dex Helper in Applications, choose Open, then grant Calendar and Reminders."
)
HELPER_GATEKEEPER_MESSAGE = HELPER_QUARANTINE_MESSAGE


def helper_unusable_payload(message: str) -> str:
    return json.dumps({"error": message, "code": "helper_unusable"})


def helper_source_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "macos" / "dex-helper"


def helper_source_version() -> str:
    version_file = helper_source_dir() / "VERSION"
    try:
        text = version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return HELPER_VERSION
    return text or HELPER_VERSION


def release_manifest_path() -> Path:
    return helper_source_dir() / "release-manifest.json"


def load_release_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_file = path if path is not None else release_manifest_path()
    try:
        parsed = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def default_install_app_path() -> Path:
    return Path.home() / "Applications" / HELPER_APP_NAME


def vault_install_app_path(vault_root: Path | None = None) -> Path:
    root = Path(vault_root) if vault_root is not None else _vault_root()
    return root / "System" / ".dex" / "helpers" / HELPER_APP_NAME


def vault_tmp_dir(vault_root: Path | None = None) -> Path:
    root = Path(vault_root) if vault_root is not None else _vault_root()
    return root / "System" / ".dex" / "tmp"


def helper_support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "Dex" / "helper"


def resolve_support_dir(
    vault_root: Path | None = None,
    support_dir: Path | None = None,
) -> Path:
    if support_dir is not None:
        return Path(support_dir)
    if vault_root is not None:
        return Path(vault_root) / "System" / ".dex" / "helper-support"
    return helper_support_dir()


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


def executable_is_native(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            magic = handle.read(2)
    except OSError:
        return False
    return magic != b"#!" and len(magic) >= 2


def _adhoc_allowed(env: Mapping[str, str] | None = None) -> bool:
    environment = os.environ if env is None else env
    return environment.get("DEX_HELPER_DEV") == "1" or environment.get("DEX_HELPER_ALLOW_ADHOC") == "1"


def app_is_quarantined(app_path: Path) -> bool:
    if sys.platform != "darwin" or not shutil.which("xattr"):
        return False
    try:
        result = subprocess.run(
            ["xattr", "-p", "com.apple.quarantine", str(app_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def helper_usability(
    app: Path,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Return ``(kind, message)``. ``kind == "ok"`` means Dex can use this app."""
    if not app.is_dir():
        return "missing", HELPER_MISSING_MESSAGE
    executable = helper_executable_from_app(app)
    if not executable.is_file():
        return "missing", HELPER_MISSING_MESSAGE
    if not executable_is_native(executable):
        return "script_executable", HELPER_SCRIPT_MESSAGE
    version = read_installed_version(app) or "0"
    if compare_versions(version, MIN_HELPER_VERSION) < 0:
        return "too_old", HELPER_TOO_OLD_MESSAGE
    identity = read_signing_identity(app)
    kind = identity.get("kind") or "unsigned"
    team = identity.get("team_id")
    if kind in {"unsigned", "adhoc"} and not _adhoc_allowed(env):
        return "unsigned", HELPER_UNSIGNED_MESSAGE
    if kind == "developer_id" and team and team != HELPER_TEAM_ID:
        return "wrong_team", (
            "Dex Helper is already installed with a different identity "
            f"(bundle {identity.get('bundle_id')}, Team ID {team}). "
            "Replace it only after you are ready to grant Calendar and "
            "Reminders again."
        )
    return "ok", ""


def helper_is_available(env: Mapping[str, str] | None = None, vault_root: Path | None = None) -> bool:
    app = helper_app_bundle(env=env, vault_root=vault_root)
    if app is None:
        return False
    kind, _message = helper_usability(app, env=env)
    return kind == "ok"


def darwin_helper_failure(
    env: Mapping[str, str] | None = None,
    vault_root: Path | None = None,
) -> tuple[bool, str] | None:
    """On a Mac, return a structured failure when the helper cannot be used."""
    if sys.platform != "darwin":
        return None
    app = helper_app_bundle(env=env, vault_root=vault_root)
    if app is None:
        return False, helper_unusable_payload(HELPER_MISSING_MESSAGE)
    kind, message = helper_usability(app, env=env)
    if kind == "ok":
        return None
    return False, helper_unusable_payload(message)


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


def _looks_like_gatekeeper(text: str) -> bool:
    lowered = text.lower()
    return "gatekeeper" in lowered or "quarantine" in lowered or "cannot be opened" in lowered


def _result_from_helper_output(op: str, output: str) -> tuple[bool, str]:
    stripped = (output or "").strip()
    if not stripped:
        return False, "Dex Helper produced no result"
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict) and parsed.get("error"):
        return False, stripped
    if op == "request-access" and isinstance(parsed, dict):
        if parsed.get("calendar") != "granted" or parsed.get("reminders") != "granted":
            return False, stripped
    return True, stripped


def run_helper_op(
    op: str,
    payload: Mapping[str, Any] | None = None,
    *,
    timeout: int = HELPER_TIMEOUT_SECONDS,
    vault_root: Path | None = None,
) -> tuple[bool, str] | None:
    """Launch the helper through LaunchServices.

    Returns None only when the helper cannot start off a Mac, so callers can
    skip. On a Mac a missing or unusable helper is a real failure, not a
    fallback signal. Judge success from the out-file JSON, not from ``open``.
    """
    darwin_failure = darwin_helper_failure(vault_root=vault_root)
    if darwin_failure is not None and helper_app_bundle(vault_root=vault_root) is None:
        return darwin_failure
    app = helper_app_bundle(vault_root=vault_root)
    if app is None:
        return None
    if sys.platform == "darwin":
        kind, message = helper_usability(app)
        if kind != "ok":
            return False, helper_unusable_payload(message)
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
            if sys.platform == "darwin":
                return False, helper_unusable_payload(HELPER_MISSING_MESSAGE)
            return None
        except subprocess.TimeoutExpired:
            return False, f"Dex Helper timed out after {timeout} seconds"
        except OSError:
            if sys.platform == "darwin":
                return False, helper_unusable_payload(HELPER_MISSING_MESSAGE)
            return None
        combined = f"{result.stderr or ''} {result.stdout or ''}"
        if _looks_like_gatekeeper(combined):
            return False, helper_unusable_payload(HELPER_GATEKEEPER_MESSAGE)
        try:
            output = out_path.read_text(encoding="utf-8").strip()
        except OSError:
            output = ""
        return _result_from_helper_output(op, output)
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

    On a Mac, a missing or unusable helper is a structured failure — never
    ``None``. Off a Mac, ``None`` still means the caller can skip.
    A helper that starts and then reports a Calendar/Reminders error is a
    real result — do not fall back after that.
    """
    mapped = helper_op_for_script(script_name, args)
    if mapped is None:
        return None
    if sys.platform == "darwin":
        failure = darwin_helper_failure(vault_root=vault_root)
        if failure is not None:
            return failure
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
                "The Dex Helper app is not built yet. On a Mac, people building "
                "Dex can run core/macos/dex-helper/build.sh with DEX_HELPER_DEV=1. "
                "Everyone else installs the signed copy from the Dex release."
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

    _replace_installed_app(source, destination, resolve_support_dir(vault_root))

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


def _replace_installed_app(source: Path, destination: Path, support_dir: Path) -> None:
    """Whole-tree replace. Never write files inside the new app after copy."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    previous_dir = support_dir / "previous"
    previous_app = previous_dir / HELPER_APP_NAME
    if destination.exists():
        if previous_dir.exists():
            shutil.rmtree(previous_dir)
        previous_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(previous_app))
    shutil.copytree(source, destination, symlinks=True)


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
    env.setdefault("DEX_HELPER_REQUIRE_UNIVERSAL", "0")
    try:
        result = subprocess.run(
            ["/bin/bash", str(script)],
            capture_output=True,
            text=True,
            timeout=300,
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _download_helper_zip(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(HELPER_DOWNLOAD_LIMIT_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f"Could not download Dex Helper: {exc}") from exc
    if len(data) > HELPER_DOWNLOAD_LIMIT_BYTES:
        raise RuntimeError("Dex Helper download was larger than expected.")
    dest.write_bytes(data)


def _extract_helper_app(zip_path: Path, extract_dir: Path) -> Path:
    extract_dir.mkdir(parents=True, exist_ok=True)
    if shutil.which("ditto"):
        subprocess.run(
            ["ditto", "-x", "-k", str(zip_path), str(extract_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extract_dir)
    app = extract_dir / HELPER_APP_NAME
    if app.is_dir():
        return app
    matches = [path for path in extract_dir.rglob(HELPER_APP_NAME) if path.is_dir()]
    if matches:
        return matches[0]
    raise RuntimeError("The Dex Helper download did not contain Dex Helper.app.")


def _verify_release_app(app: Path, manifest: Mapping[str, Any]) -> None:
    executable = helper_executable_from_app(app)
    if not executable.is_file() or not executable_is_native(executable):
        raise RuntimeError(HELPER_SCRIPT_MESSAGE)
    expected_bundle = str(manifest.get("bundle_id") or HELPER_BUNDLE_ID)
    if read_bundle_id(app) != expected_bundle:
        raise RuntimeError("The downloaded Dex Helper is not the Dex Helper app.")
    expected_team = str(manifest.get("team_id") or HELPER_TEAM_ID)
    if sys.platform == "darwin" and shutil.which("codesign"):
        identity = read_signing_identity(app)
        if identity.get("team_id") != expected_team:
            raise RuntimeError(
                "Dex Helper is already installed with a different identity "
                f"(bundle {identity.get('bundle_id')}, Team ID {identity.get('team_id')}). "
                "Replace it only after you are ready to grant Calendar and Reminders again."
            )
        verify = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(app)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if verify.returncode != 0:
            raise RuntimeError("The downloaded Dex Helper did not pass its signature check.")


def helper_download_url(manifest: Mapping[str, Any]) -> str:
    tag = str(manifest.get("download_tag") or "").strip()
    asset = str(manifest.get("asset_name") or "").strip()
    return f"https://github.com/davekilleen/Dex/releases/download/{tag}/{asset}"


def install_or_update_helper_from_release(
    vault_root: Path | None = None,
    *,
    manifest: Mapping[str, Any] | None = None,
    zip_path: Path | None = None,
    download_url: str | None = None,
    destination_app: Path | None = None,
    support_dir: Path | None = None,
) -> dict[str, object]:
    """Download the pinned signed helper, verify it, and replace the installed app."""
    if sys.platform != "darwin" and zip_path is None:
        return {
            "ok": True,
            "skipped": True,
            "reason": "not_macos",
            "message": "The Calendar and Reminders helper is Mac-only.",
        }
    loaded = dict(manifest) if manifest is not None else load_release_manifest()
    sha256 = str(loaded.get("sha256") or "").strip()
    if not _valid_sha256(sha256):
        return {
            "ok": False,
            "skipped": True,
            "reason": "not_in_release",
            "message": HELPER_NOT_IN_RELEASE_MESSAGE,
        }

    destination = destination_app if destination_app is not None else default_install_app_path()
    support = resolve_support_dir(vault_root, support_dir)
    installed_version = read_installed_version(destination) if destination.is_dir() else None
    pin_version = str(loaded.get("helper_version") or helper_source_version())
    if (
        destination.is_dir()
        and installed_version
        and compare_versions(installed_version, pin_version) >= 0
        and helper_usability(destination)[0] == "ok"
        and read_signing_identity(destination).get("team_id") == str(loaded.get("team_id") or HELPER_TEAM_ID)
    ):
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_current",
            "version": installed_version,
            "path": str(destination),
        }
    if destination.is_dir():
        expected_source = {
            "kind": "developer_id",
            "team_id": str(loaded.get("team_id") or HELPER_TEAM_ID),
            "bundle_id": str(loaded.get("bundle_id") or HELPER_BUNDLE_ID),
        }
        dest_identity = read_signing_identity(destination)
        if dest_identity.get("bundle_id") and (
            dest_identity.get("bundle_id") != expected_source["bundle_id"]
            or (
                dest_identity.get("team_id")
                and dest_identity.get("team_id") != expected_source["team_id"]
                and dest_identity.get("kind") == "developer_id"
            )
        ):
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

    downloads = support / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    asset_name = str(loaded.get("asset_name") or f"DexHelper-v{pin_version}.zip")
    cached = zip_path if zip_path is not None else downloads / asset_name
    if zip_path is None:
        url = download_url or helper_download_url(loaded)
        try:
            _download_helper_zip(url, cached)
        except Exception as exc:
            return {
                "ok": False,
                "skipped": False,
                "reason": "download_failed",
                "message": str(exc) or HELPER_MISSING_MESSAGE,
            }
    digest = _sha256_file(cached)
    if digest.lower() != sha256.lower():
        try:
            cached.unlink()
        except OSError:
            pass
        return {
            "ok": False,
            "skipped": False,
            "reason": "checksum_mismatch",
            "message": "The Dex Helper download did not match the signed copy Dex expected.",
        }

    extract_root = Path(tempfile.mkdtemp(prefix="dex-helper-", dir=str(downloads)))
    try:
        try:
            extracted = _extract_helper_app(cached, extract_root)
            _verify_release_app(extracted, loaded)
        except Exception as exc:
            return {
                "ok": False,
                "skipped": False,
                "reason": "verify_failed",
                "message": str(exc),
            }
        _replace_installed_app(extracted, destination, support)
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)

    identity = read_signing_identity(destination)
    record = {
        "ok": True,
        "skipped": False,
        "reason": "installed" if installed_version is None else "updated",
        "version": read_installed_version(destination) or pin_version,
        "path": str(destination),
        "signed": True,
        "signing": identity.get("kind") or "developer_id",
        "team_id": identity.get("team_id") or loaded.get("team_id"),
        "bundle_id": HELPER_BUNDLE_ID,
    }
    _write_install_record(record, vault_root)
    return record


def rollback_helper(
    *,
    destination_app: Path | None = None,
    support_dir: Path | None = None,
    vault_root: Path | None = None,
) -> dict[str, object]:
    destination = destination_app if destination_app is not None else default_install_app_path()
    support = resolve_support_dir(vault_root, support_dir)
    previous = support / "previous" / HELPER_APP_NAME
    if not previous.is_dir():
        return {
            "ok": False,
            "skipped": True,
            "reason": "no_previous",
            "message": "There is no previous Dex Helper to restore.",
        }
    if destination.is_dir() and not identities_match(previous, destination):
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
    staged = support / "rollback-current"
    if staged.exists():
        shutil.rmtree(staged)
    if destination.exists():
        shutil.move(str(destination), str(staged))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(previous), str(destination))
    if staged.exists():
        previous.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(previous))
    record = {
        "ok": True,
        "skipped": False,
        "reason": "rolled_back",
        "version": read_installed_version(destination),
        "path": str(destination),
        "signing": read_signing_identity(destination).get("kind"),
        "team_id": read_signing_identity(destination).get("team_id"),
        "bundle_id": HELPER_BUNDLE_ID,
    }
    _write_install_record(record, vault_root)
    return record


def doctor_status_line(vault_root: Path | None = None) -> str:
    """One Doctor line: installed or not, signing identity, auth status."""
    app = helper_app_bundle(vault_root=vault_root)
    if app is None:
        return "Dex Helper: not installed"
    executable = helper_executable_from_app(app)
    if executable.is_file() and not executable_is_native(executable):
        return "Dex Helper: installed, unusable script copy"
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


def _dev_install_requested(args: Sequence[str]) -> bool:
    if "--dev" in args:
        return True
    return os.environ.get("DEX_HELPER_DEV") == "1"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "status"
    if command == "install":
        if _dev_install_requested(args):
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
        result = install_or_update_helper_from_release()
        print(result.get("message") or result.get("reason"))
        return 0 if result.get("ok") or result.get("skipped") else 1
    if command == "rollback":
        result = rollback_helper()
        print(result.get("message") or result.get("reason"))
        return 0 if result.get("ok") else 1
    if command == "status":
        print(doctor_status_line())
        return 0
    print("Usage: python -m core.utils.macos_privacy_helper [status|install|rollback]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
