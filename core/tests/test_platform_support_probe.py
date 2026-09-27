"""Phase 3 acceptance: each Windows support tier yields the specified verdict.

All OS. Platform facts are injected so Linux CI can cover Store Python, Cygwin,
WSL /mnt, and untested 3.14 without a Windows runner.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from core.utils import platform_support as support

pytestmark = pytest.mark.windows_supported

REPO_ROOT = Path(__file__).resolve().parents[2]


def _probe(**kwargs):
    return support.probe(**kwargs)


def test_supported_windows_python_org_312() -> None:
    report = _probe(
        sys_platform="win32",
        version_info=(3, 12, 8),
        base_prefix=r"C:\Users\Joe\AppData\Local\Programs\Python\Python312",
        machine="AMD64",
        vault_root=r"C:\Users\Joe\Documents\Dex",
        environ={},
        uname_s="Windows",
        volume=support.VaultVolume(filesystem="NTFS", acls=True, remote=False),
    )
    assert report.family == "windows"
    assert report.python_source == "python.org"
    assert report.python_ok is True
    assert report.verdict == "supported"
    assert report.message_ids() == []


def test_store_python_detected_from_windowsapps_prefix() -> None:
    report = _probe(
        sys_platform="win32",
        version_info=(3, 12, 0),
        base_prefix=r"C:\Users\Joe\AppData\Local\Microsoft\WindowsApps",
        vault_root=r"C:\Users\Joe\Documents\Dex",
        environ={},
        volume=support.VaultVolume(filesystem="NTFS", acls=True, remote=False),
    )
    assert report.python_source == "microsoft-store"
    assert report.python_ok is False
    assert report.verdict == "unsupported"
    assert report.message_ids() == ["W2"]
    assert report.messages[0].text == support.MESSAGE_W2


def test_store_python_detected_from_pythonsoftwarefoundation_prefix() -> None:
    report = _probe(
        sys_platform="win32",
        version_info=(3, 13, 1),
        base_prefix=r"C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13",
        vault_root=r"C:\Users\Joe\Documents\Dex",
        environ={},
        volume=support.VaultVolume(filesystem="NTFS", acls=True, remote=False),
    )
    assert report.python_source == "microsoft-store"
    assert report.verdict == "unsupported"
    assert report.message_ids() == ["W2"]


def test_python_314_is_warning_not_refusal() -> None:
    report = _probe(
        sys_platform="win32",
        version_info=(3, 14, 0),
        base_prefix=r"C:\Python314",
        vault_root=r"C:\Users\Joe\Documents\Dex",
        environ={},
        volume=support.VaultVolume(filesystem="NTFS", acls=True, remote=False),
    )
    assert report.python_ok is True
    assert report.verdict == "supported-with-warnings"
    assert report.message_ids() == ["W8"]
    assert "3.14" in report.messages[0].text
    assert "3.12 or 3.13 is recommended" in report.messages[0].text


def test_python_311_on_windows_is_unsupported_w1() -> None:
    report = _probe(
        sys_platform="win32",
        version_info=(3, 11, 9),
        base_prefix=r"C:\Python311",
        vault_root=r"C:\Users\Joe\Documents\Dex",
        environ={},
        volume=support.VaultVolume(filesystem="NTFS", acls=True, remote=False),
    )
    assert report.python_ok is False
    assert report.verdict == "unsupported"
    assert report.message_ids() == ["W1"]
    assert "You have 3.11.9" in report.messages[0].text


def test_cygwin_python_is_unsupported_w3() -> None:
    report = _probe(
        sys_platform="cygwin",
        version_info=(3, 12, 0),
        base_prefix="/usr",
        vault_root="/home/joe/Dex",
        environ={"OSTYPE": "cygwin"},
        uname_s="CYGWIN_NT-10.0",
    )
    assert report.family == "cygwin-or-msys"
    assert report.python_ok is False
    assert report.verdict == "unsupported"
    assert report.message_ids() == ["W3"]
    assert report.messages[0].text == support.MESSAGE_W3


def test_msys_python_is_unsupported_w3() -> None:
    report = _probe(
        sys_platform="msys",
        version_info=(3, 12, 0),
        base_prefix="/usr",
        vault_root="/home/joe/Dex",
        uname_s="MSYS_NT-10.0",
    )
    assert report.family == "cygwin-or-msys"
    assert report.verdict == "unsupported"
    assert report.message_ids() == ["W3"]


def test_wsl_mnt_vault_is_unsupported_w4() -> None:
    report = _probe(
        sys_platform="linux",
        version_info=(3, 12, 3),
        base_prefix="/usr",
        vault_root="/mnt/c/Users/Joe/Documents/Dex",
        proc_version="Linux version 5.15.0-microsoft-standard-WSL2",
        wsl_interop=True,
    )
    assert report.family == "wsl"
    assert report.verdict == "unsupported"
    assert report.message_ids() == ["W4"]
    assert report.messages[0].text == support.MESSAGE_W4


def test_wsl_linux_home_vault_is_not_a_windows_setup() -> None:
    report = _probe(
        sys_platform="linux",
        version_info=(3, 12, 3),
        base_prefix="/usr",
        vault_root="/home/joe/Dex",
        proc_version="Linux version 5.15.0-microsoft-standard-WSL2",
        wsl_interop=True,
    )
    assert report.family == "wsl"
    assert report.verdict == "supported"
    assert report.message_ids() == []


def test_sync_roots_detected_from_onedrive_env_and_path() -> None:
    from_env = _probe(
        sys_platform="win32",
        version_info=(3, 12, 0),
        base_prefix=r"C:\Python312",
        vault_root=r"C:\Users\Joe\OneDrive\Documents\Dex",
        environ={"OneDrive": r"C:\Users\Joe\OneDrive"},
        volume=support.VaultVolume(filesystem="NTFS", acls=True, remote=False),
    )
    assert from_env.vault_volume["sync_client"] == "onedrive"
    assert from_env.verdict == "supported-with-warnings"
    assert from_env.message_ids() == ["W7"]
    assert "OneDrive" in from_env.messages[0].text

    from_path = _probe(
        sys_platform="win32",
        version_info=(3, 12, 0),
        base_prefix=r"C:\Python312",
        vault_root=r"C:\Users\Joe\Dropbox\Dex",
        environ={},
        volume=support.VaultVolume(filesystem="NTFS", acls=True, remote=False),
    )
    assert from_path.vault_volume["sync_client"] == "dropbox"
    assert from_path.message_ids() == ["W7"]
    assert "Dropbox" in from_path.messages[0].text


def test_fat_and_network_drives_are_unsupported_w6() -> None:
    fat = _probe(
        sys_platform="win32",
        version_info=(3, 12, 0),
        base_prefix=r"C:\Python312",
        vault_root=r"E:\Dex",
        environ={},
        volume=support.VaultVolume(filesystem="exFAT", acls=False, remote=False),
    )
    assert fat.verdict == "unsupported"
    assert fat.message_ids() == ["W6"]
    assert "exFAT" in fat.messages[0].text

    remote = _probe(
        sys_platform="win32",
        version_info=(3, 12, 0),
        base_prefix=r"C:\Python312",
        vault_root=r"\\server\share\Dex",
        environ={},
        volume=support.VaultVolume(filesystem="NTFS", acls=True, remote=True),
    )
    assert remote.verdict == "unsupported"
    assert remote.message_ids() == ["W6"]
    assert "network drive" in remote.messages[0].text


def test_arm64_is_informational_warning() -> None:
    report = _probe(
        sys_platform="win32",
        version_info=(3, 13, 0),
        base_prefix=r"C:\Python313",
        machine="ARM64",
        vault_root=r"C:\Users\Joe\Documents\Dex",
        environ={},
        volume=support.VaultVolume(filesystem="NTFS", acls=True, remote=False),
    )
    assert report.verdict == "supported-with-warnings"
    assert report.message_ids() == ["W9"]
    assert report.messages[0].text == support.MESSAGE_W9


def test_macos_and_linux_stay_supported() -> None:
    mac = _probe(
        sys_platform="darwin",
        version_info=(3, 12, 0),
        base_prefix="/usr/local",
        vault_root="/Users/joe/Dex",
        uname_s="Darwin",
    )
    assert mac.family == "macos"
    assert mac.verdict == "supported"
    linux = _probe(
        sys_platform="linux",
        version_info=(3, 10, 12),
        base_prefix="/usr",
        vault_root="/home/joe/Dex",
        proc_version="Linux version 6.8.0",
        wsl_interop=False,
        uname_s="Linux",
    )
    assert linux.family == "linux"
    assert linux.python_ok is True
    assert linux.verdict == "supported"


def test_git_bash_uname_is_launcher_not_cygwin_refuse() -> None:
    check = support.evaluate_shell(
        uname_s="MINGW64_NT-10.0-26200",
        vault_path=r"C:\Users\Joe\Documents\Dex",
        proc_version="",
    )
    assert check.refused is False
    assert check.launcher is True
    assert check.message is None


def test_cygwin_uname_is_refused_before_python() -> None:
    check = support.evaluate_shell(
        uname_s="CYGWIN_NT-10.0",
        vault_path="/home/joe/Dex",
        proc_version="",
    )
    assert check.refused is True
    assert check.message is not None
    assert check.message.id == "W3"


def test_msys_uname_is_launcher() -> None:
    check = support.evaluate_shell(uname_s="MSYS_NT-10.0", vault_path="/c/Dex")
    assert check.launcher is True
    assert check.refused is False


def test_wsl_mnt_shell_precheck_refuses() -> None:
    check = support.evaluate_shell(
        uname_s="Linux",
        vault_path="/mnt/c/Users/Joe/Dex",
        proc_version="Linux version 5.15.0-microsoft-standard-WSL2",
    )
    assert check.refused is True
    assert check.message is not None
    assert check.message.id == "W4"


def test_venv_python_must_be_win32() -> None:
    assert support.verify_windows_venv_platform("win32") is None
    refusal = support.verify_windows_venv_platform("cygwin")
    assert refusal is not None
    assert refusal.id == "W3"


def test_cli_json_exits_one_when_unsupported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        support,
        "probe",
        lambda **_kwargs: support.SupportReport(
            family="cygwin-or-msys",
            shell_hint="uname=CYGWIN_NT-10.0",
            python_source="other",
            python_ok=False,
            vault_volume={},
            verdict="unsupported",
            messages=[support.SupportMessage(id="W3", text=support.MESSAGE_W3)],
        ),
    )
    assert support.main(["--json", "--vault", str(tmp_path)]) == 1


def test_cli_shell_precheck_json(tmp_path: Path) -> None:
    status = support.main(
        ["--shell-precheck", "--json", "--uname", "MINGW64_NT-10.0", "--vault", str(tmp_path)]
    )
    assert status == 0


def test_module_is_importable_before_venv() -> None:
    """The installer imports this with the system Python, not the vault venv."""
    assert (REPO_ROOT / "core" / "utils" / "platform_support.py").is_file()
    assert support.WINDOWS_PYTHON_MIN == (3, 12)
    payload = json.loads(json.dumps(_probe(sys_platform="darwin").to_dict()))
    assert payload["verdict"] in {"supported", "supported-with-warnings", "unsupported"}


def test_readme_says_preview_and_lists_what_is_not_ready() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "**Windows — PowerShell (preview):**" in text
    assert "Windows support is a **preview**" in text
    assert "## Windows support status" in text
    assert "`/dex-update` and `/dex-rollback`" in text
    assert "Not yet" in text
    assert "Microsoft Store Python" in text
    assert "Calendar connection is Mac-only" in text
    spec = (REPO_ROOT / "docs" / "specs" / "windows-support-and-security.md").read_text(
        encoding="utf-8"
    )
    assert "## Windows support status" in spec
