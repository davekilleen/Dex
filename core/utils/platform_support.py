"""Which computer setups Dex supports, and the exact words it uses to say so.

Stdlib only. Safe to import before a virtual environment exists. Installers and
Doctor call :func:`probe`; tests inject platform facts so every tier can be
checked on macOS and Linux.
"""

from __future__ import annotations

import argparse
import json
import os
import platform as py_platform
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

WINDOWS_PYTHON_MIN = (3, 12)
WINDOWS_PYTHON_RECOMMENDED_MAX = (3, 13)
POSIX_PYTHON_MIN = (3, 10)

MESSAGE_W1 = (
    "Dex needs Python 3.12 or 3.13 on Windows. You have {version}. Install "
    "from python.org and tick 'Add python.exe to PATH', then run the installer "
    "again."
)
MESSAGE_W2 = (
    "This Python came from the Microsoft Store, which keeps its files in "
    "a sandbox that Dex's tools cannot rely on. Install Python 3.12 or 3.13 "
    "from python.org instead, then run the installer again. You can keep the "
    "Store version; Dex will use the one from python.org."
)
MESSAGE_W3 = (
    "Dex on Windows runs in PowerShell or Git Bash with a Python from "
    "python.org. Cygwin isn't supported. Open Git Bash (installed with Git for "
    "Windows) or PowerShell in your Dex folder and run the installer there."
)
MESSAGE_W4 = (
    "Your Dex folder is on the Windows side of WSL (/mnt/...). Dex can't "
    "keep its files safe there. Either keep the folder in Linux (for example "
    "~/Dex) and use Dex from WSL, or install Dex natively in Windows PowerShell."
)
MESSAGE_W5 = (
    "Dex needs Git installed for all users (the default 'Install for all users' "
    "option of Git for Windows, which places it under Program Files). Dex found "
    "a per-user Git but will not use it."
)
MESSAGE_W6 = (
    "Your Dex folder is on a drive that doesn't keep file permissions "
    "({name} is {kind}). Dex stores keys and trust settings only on an NTFS "
    "drive such as C:. Move the folder and run the installer again."
)
MESSAGE_W7 = (
    "Your Dex folder is inside {client}. That works, but if the sync client "
    "changes a file while Dex is updating, Dex stops and asks you to try again "
    "rather than guessing."
)
MESSAGE_W8 = (
    "Dex has not been tested with Python {version} yet; 3.12 or 3.13 is "
    "recommended."
)
MESSAGE_W9 = (
    "You're on Windows for ARM. Dex should work but isn't tested there yet."
)

REFUSE_IDS = frozenset({"W1", "W2", "W3", "W4", "W6"})
WARN_IDS = frozenset({"W7", "W8", "W9"})

_STORE_MARKERS = ("windowsapps", "pythonsoftwarefoundation.python")
_CONDA_MARKERS = ("conda", "miniconda", "anaconda")
_SYNC_ENV_KEYS = {
    "onedrive": ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"),
    "dropbox": ("DROPBOX_HOME", "Dropbox"),
}


@dataclass(frozen=True)
class SupportMessage:
    """One user-facing support message, identified as W1–W9."""

    id: str
    text: str


@dataclass(frozen=True)
class VaultVolume:
    """What Dex can tell about the folder's drive, without guessing."""

    filesystem: str | None = None
    acls: bool | None = None
    remote: bool | None = None
    sync_client: str | None = None
    case_sensitive_dir: bool | None = None


@dataclass(frozen=True)
class ShellPrecheck:
    """Bash-side decision made before a Python interpreter is chosen."""

    action: str
    launcher: bool = False
    message: SupportMessage | None = None

    @property
    def refused(self) -> bool:
        return self.action == "refuse"


@dataclass
class SupportReport:
    """Installer and Doctor share this report."""

    family: str
    shell_hint: str
    python_source: str
    python_ok: bool
    vault_volume: dict[str, Any]
    verdict: str
    messages: list[SupportMessage] = field(default_factory=list)

    def message_ids(self) -> list[str]:
        return [item.id for item in self.messages]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["messages"] = [asdict(item) for item in self.messages]
        return payload


def _norm(value: str) -> str:
    # Always lowercase. os.path.normcase only folds case on Windows, and the
    # probe tests (and Linux CI) inject Windows paths on POSIX.
    return os.path.normcase(value).replace("\\", "/").lower()


def _version_tuple(info: Sequence[int] | None) -> tuple[int, int]:
    if not info:
        return sys.version_info[0], sys.version_info[1]
    return int(info[0]), int(info[1])


def _format_version(info: Sequence[int] | None) -> str:
    major, minor = _version_tuple(info)
    if info is not None and len(info) >= 3:
        return f"{major}.{minor}.{int(info[2])}"
    return f"{major}.{minor}"


def classify_python_source(
    base_prefix: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Return python.org, microsoft-store, conda, or other from prefix heuristics."""
    prefix = _norm(base_prefix if base_prefix is not None else sys.base_prefix)
    env = environ if environ is not None else os.environ
    if any(marker in prefix for marker in _STORE_MARKERS):
        return "microsoft-store"
    conda_prefix = env.get("CONDA_PREFIX") or env.get("CONDA_DEFAULT_ENV")
    if conda_prefix or any(marker in prefix for marker in _CONDA_MARKERS):
        return "conda"
    if (
        "python.org" in prefix
        or "/programs/python" in prefix
        or "/program files/python" in prefix
        or "/program files (x86)/python" in prefix
    ):
        return "python.org"
    return "other"


def detect_family(
    *,
    sys_platform: str | None = None,
    proc_version: str | None = None,
    wsl_interop: bool | None = None,
) -> str:
    """Classify the running Python / kernel as a support family."""
    plat = sys_platform if sys_platform is not None else sys.platform
    if plat == "win32":
        return "windows"
    if plat in {"cygwin", "msys"}:
        return "cygwin-or-msys"
    if plat == "darwin":
        return "macos"
    text = proc_version
    if text is None:
        try:
            text = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    interop = wsl_interop
    if interop is None:
        interop = Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists()
    if "microsoft" in text.lower() or interop:
        return "wsl"
    if plat.startswith("linux"):
        return "linux"
    return "unknown"


def detect_shell_hint(
    *,
    environ: Mapping[str, str] | None = None,
    uname_s: str | None = None,
) -> str:
    """Informational only: OSTYPE, MSYSTEM, and uname -s when present."""
    env = environ if environ is not None else os.environ
    parts: list[str] = []
    for key in ("OSTYPE", "MSYSTEM"):
        value = env.get(key)
        if value:
            parts.append(f"{key}={value}")
    name = uname_s
    if name is None:
        name = py_platform.uname().system
    if name:
        parts.append(f"uname={name}")
    return " ".join(parts)


def _vault_under_wsl_mnt(vault_root: str | Path | None) -> bool:
    if vault_root is None:
        return False
    text = str(vault_root).replace("\\", "/")
    return bool(re.match(r"/mnt/[A-Za-z](/|$)", text))


def detect_sync_client(
    vault_root: str | Path | None,
    *,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """Return onedrive, dropbox, or None from env roots and path prefixes."""
    if vault_root is None:
        return None
    env = environ if environ is not None else os.environ
    vault = Path(str(vault_root))
    folded = _norm(str(vault))
    for client, keys in _SYNC_ENV_KEYS.items():
        for key in keys:
            raw = env.get(key)
            if not raw:
                continue
            try:
                root = Path(raw).expanduser()
            except (OSError, RuntimeError, ValueError):
                continue
            if folded.startswith(_norm(str(root))):
                return client
    if "/onedrive" in folded:
        return "onedrive"
    if "/dropbox" in folded:
        return "dropbox"
    return None


def detect_volume(
    vault_root: str | Path | None,
    *,
    environ: Mapping[str, str] | None = None,
    injected: VaultVolume | None = None,
) -> VaultVolume:
    """Describe the vault drive. ctypes Windows calls are used only when injected is absent on nt."""
    if injected is not None:
        sync = injected.sync_client
        if sync is None:
            sync = detect_sync_client(vault_root, environ=environ)
        return VaultVolume(
            filesystem=injected.filesystem,
            acls=injected.acls,
            remote=injected.remote,
            sync_client=sync,
            case_sensitive_dir=injected.case_sensitive_dir,
        )
    sync = detect_sync_client(vault_root, environ=environ)
    remote = False
    filesystem = None
    acls = None
    if vault_root is not None:
        text = str(vault_root)
        if text.startswith("\\\\") or text.startswith("//"):
            remote = True
    if sys.platform == "win32" and vault_root is not None:
        filesystem, acls, remote_flag = _windows_volume_facts(str(vault_root))
        if remote_flag is not None:
            remote = remote_flag
    return VaultVolume(
        filesystem=filesystem,
        acls=acls,
        remote=remote,
        sync_client=sync,
        case_sensitive_dir=None,
    )


def _windows_volume_facts(path: str) -> tuple[str | None, bool | None, bool | None]:
    """Best-effort NTFS / ACL / remote probe. Returns unknowns when ctypes is unavailable."""
    try:
        import ctypes
        from ctypes import wintypes
    except (ImportError, AttributeError):
        return None, None, None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError):
        return None, None, None
    GetDriveTypeW = kernel32.GetDriveTypeW
    GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    GetDriveTypeW.restype = wintypes.UINT
    drive = Path(path).anchor or path[:3]
    if not drive.endswith("\\"):
        drive = drive + "\\"
    drive_type = int(GetDriveTypeW(drive))
    remote = drive_type == 4  # DRIVE_REMOTE
    filesystem = None
    acls = None
    try:
        GetVolumeInformationW = kernel32.GetVolumeInformationW
        GetVolumeInformationW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR,
            wintypes.DWORD,
        ]
        GetVolumeInformationW.restype = wintypes.BOOL
        fs_name = ctypes.create_unicode_buffer(32)
        flags = wintypes.DWORD(0)
        if GetVolumeInformationW(
            drive, None, 0, None, None, ctypes.byref(flags), fs_name, 32
        ):
            filesystem = fs_name.value or None
            acls = bool(int(flags.value) & 0x8)  # FILE_PERSISTENT_ACLS
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    return filesystem, acls, remote


def evaluate_shell(
    *,
    uname_s: str = "",
    vault_path: str | Path | None = None,
    proc_version: str | None = None,
) -> ShellPrecheck:
    """Bash pre-checks from section 4.2: Cygwin refuse, Git Bash launcher, WSL /mnt refuse."""
    name = (uname_s or "").strip()
    upper = name.upper()
    if upper.startswith("CYGWIN"):
        return ShellPrecheck(
            action="refuse",
            message=SupportMessage(id="W3", text=MESSAGE_W3),
        )
    launcher = upper.startswith("MINGW") or upper.startswith("MSYS")
    text = proc_version
    if text is None:
        try:
            text = Path("/proc/version").read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    if "microsoft" in text.lower() and _vault_under_wsl_mnt(vault_path):
        return ShellPrecheck(
            action="refuse",
            message=SupportMessage(id="W4", text=MESSAGE_W4),
        )
    return ShellPrecheck(action="continue", launcher=launcher)


def _volume_unsupported(volume: VaultVolume) -> SupportMessage | None:
    if volume.remote:
        return SupportMessage(
            id="W6",
            text=MESSAGE_W6.format(name="the folder", kind="a network drive"),
        )
    filesystem = (volume.filesystem or "").upper()
    if filesystem in {"FAT", "FAT32", "EXFAT"}:
        kind = "exFAT" if filesystem == "EXFAT" else "FAT32"
        return SupportMessage(
            id="W6",
            text=MESSAGE_W6.format(name=volume.filesystem or "the drive", kind=kind),
        )
    if volume.acls is False and filesystem and filesystem != "NTFS":
        return SupportMessage(
            id="W6",
            text=MESSAGE_W6.format(
                name=volume.filesystem or "the drive",
                kind=volume.filesystem or "a drive without permissions",
            ),
        )
    if volume.case_sensitive_dir is True:
        return SupportMessage(
            id="W6",
            text=MESSAGE_W6.format(
                name="the folder",
                kind="a case-sensitive directory",
            ),
        )
    return None


def probe(
    *,
    sys_platform: str | None = None,
    version_info: Sequence[int] | None = None,
    base_prefix: str | None = None,
    machine: str | None = None,
    vault_root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    uname_s: str | None = None,
    proc_version: str | None = None,
    wsl_interop: bool | None = None,
    volume: VaultVolume | None = None,
) -> SupportReport:
    """Return the support verdict for this Python, shell, and folder."""
    env = environ if environ is not None else os.environ
    plat = sys_platform if sys_platform is not None else sys.platform
    info = version_info if version_info is not None else sys.version_info
    prefix = base_prefix if base_prefix is not None else sys.base_prefix
    cpu = machine if machine is not None else py_platform.machine()
    family = detect_family(
        sys_platform=plat, proc_version=proc_version, wsl_interop=wsl_interop
    )
    source = classify_python_source(prefix, environ=env)
    vol = detect_volume(vault_root, environ=env, injected=volume)
    messages: list[SupportMessage] = []

    python_ok = True
    if plat == "win32":
        python_ok = (
            _version_tuple(info) >= WINDOWS_PYTHON_MIN and source != "microsoft-store"
        )
    elif plat in {"cygwin", "msys"}:
        python_ok = False
    else:
        python_ok = _version_tuple(info) >= POSIX_PYTHON_MIN

    if family == "cygwin-or-msys":
        messages.append(SupportMessage(id="W3", text=MESSAGE_W3))
    if family == "wsl" and _vault_under_wsl_mnt(vault_root):
        messages.append(SupportMessage(id="W4", text=MESSAGE_W4))

    if family == "windows":
        if source == "microsoft-store":
            messages.append(SupportMessage(id="W2", text=MESSAGE_W2))
        elif _version_tuple(info) < WINDOWS_PYTHON_MIN:
            messages.append(
                SupportMessage(
                    id="W1",
                    text=MESSAGE_W1.format(version=_format_version(info)),
                )
            )
        elif _version_tuple(info) > WINDOWS_PYTHON_RECOMMENDED_MAX:
            messages.append(
                SupportMessage(
                    id="W8",
                    text=MESSAGE_W8.format(version=_format_version(info)),
                )
            )
        volume_message = _volume_unsupported(vol)
        if volume_message is not None:
            messages.append(volume_message)
        if vol.sync_client:
            label = "OneDrive" if vol.sync_client == "onedrive" else "Dropbox"
            messages.append(
                SupportMessage(id="W7", text=MESSAGE_W7.format(client=label))
            )
        if cpu.lower() in {"arm64", "aarch64"}:
            messages.append(SupportMessage(id="W9", text=MESSAGE_W9))

    seen: set[str] = set()
    unique: list[SupportMessage] = []
    for item in messages:
        if item.id in seen:
            continue
        seen.add(item.id)
        unique.append(item)

    refuse = [item for item in unique if item.id in REFUSE_IDS]
    warn = [item for item in unique if item.id in WARN_IDS]
    if refuse:
        verdict = "unsupported"
    elif warn:
        verdict = "supported-with-warnings"
    else:
        verdict = "supported"

    return SupportReport(
        family=family,
        shell_hint=detect_shell_hint(environ=env, uname_s=uname_s),
        python_source=source,
        python_ok=python_ok,
        vault_volume=asdict(vol),
        verdict=verdict,
        messages=unique,
    )


def verify_windows_venv_platform(platform_name: str) -> SupportMessage | None:
    """After venv creation, the Windows interpreter must be win32, not MSYS/Cygwin."""
    if platform_name == "win32":
        return None
    return SupportMessage(id="W3", text=MESSAGE_W3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print whether this computer is a supported Dex setup."
    )
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--vault",
        type=Path,
        default=None,
        help="Dex folder to judge (defaults to the current directory)",
    )
    parser.add_argument(
        "--shell-precheck",
        action="store_true",
        help="run the bash-side Cygwin / Git Bash / WSL /mnt checks only",
    )
    parser.add_argument("--uname", default=None, help="override uname -s (tests)")
    args = parser.parse_args(argv)
    vault = args.vault if args.vault is not None else Path.cwd()
    if args.shell_precheck:
        result = evaluate_shell(uname_s=args.uname or "", vault_path=vault)
        payload = {
            "action": result.action,
            "launcher": result.launcher,
            "message": asdict(result.message) if result.message else None,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        if result.message:
            print(result.message.text, file=sys.stderr)
        return 1 if result.refused else 0
    report = probe(vault_root=vault, uname_s=args.uname)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    for item in report.messages:
        print(item.text, file=sys.stderr)
    return 1 if report.verdict == "unsupported" else 0


if __name__ == "__main__":
    raise SystemExit(main())
