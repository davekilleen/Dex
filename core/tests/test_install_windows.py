"""Phase 3 installer hook: Cygwin refuse, Git Bash launcher, non-win32 venv.

Full Windows installer mechanics (Python fallback, Store stub, install.log,
install.ps1) live in #755. These tests cover only the support-policy hook
added here, so the two PRs can merge without duplicating that work.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from core.utils import platform_support as support

pytestmark = pytest.mark.windows_supported

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _source_support(script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged["DEX_SUPPORT_LIB_ONLY"] = "1"
    if env:
        merged.update(env)
    return subprocess.run(
        ["/bin/bash", "-c", f'set -e\n. "{INSTALL_SH}"\n{script}'],
        capture_output=True,
        text=True,
        timeout=20,
        env=merged,
    )


def test_install_sh_wires_the_phase3_support_hook() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "dex_support_shell_precheck" in text
    assert "dex_support_python_probe" in text
    assert "dex_support_verify_venv_python" in text
    assert "core.utils.platform_support" in text
    assert "DEX_SUPPORT_LIB_ONLY" in text
    assert support.MESSAGE_W3 in text
    assert support.MESSAGE_W4 in text


def test_cygwin_nt_uname_prints_w3_and_exits_one() -> None:
    result = _source_support(
        "dex_support_shell_precheck",
        env={"DEX_TEST_UNAME": "CYGWIN_NT-10.0", "DEX_TEST_PROC_VERSION": ""},
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert support.MESSAGE_W3 in result.stdout
    assert "MINGW" not in result.stdout


def test_mingw64_nt_uname_is_launcher_mode() -> None:
    result = _source_support(
        "dex_support_shell_precheck\n"
        'if [ "${DEX_WINDOWS_LAUNCHER:-}" = "1" ]; then echo launcher; else echo other; fi',
        env={"DEX_TEST_UNAME": "MINGW64_NT-10.0-26200", "DEX_TEST_PROC_VERSION": ""},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip().splitlines()[-1] == "launcher"
    assert support.MESSAGE_W3 not in result.stdout


def test_msys_nt_uname_is_launcher_mode() -> None:
    result = _source_support(
        "dex_support_shell_precheck\n"
        'printf "%s\\n" "${DEX_WINDOWS_LAUNCHER:-}"',
        env={"DEX_TEST_UNAME": "MSYS_NT-10.0", "DEX_TEST_PROC_VERSION": ""},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "1"


def test_wsl_mnt_vault_prints_w4_and_exits_one(tmp_path: Path) -> None:
    result = _source_support(
        "dex_support_shell_precheck",
        env={
            "DEX_TEST_UNAME": "Linux",
            "DEX_TEST_PROC_VERSION": "Linux version 5.15.0-microsoft-standard-WSL2",
            "DEX_TEST_VAULT_PATH": "/mnt/c/Users/Joe/Documents/Dex",
        },
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert support.MESSAGE_W4 in result.stdout


def test_venv_python_not_win32_fails_and_names_the_log_path(tmp_path: Path) -> None:
    root = tmp_path / "dex"
    scripts = root / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    log_path = tmp_path / "install.log"
    _write_executable(
        scripts / "python.exe",
        """#!/bin/sh
if [ "$1" = "-c" ]; then echo cygwin; exit 0; fi
exit 0
""",
    )
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\ndex_support_verify_venv_python',
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
        env={
            **os.environ,
            "DEX_SUPPORT_LIB_ONLY": "1",
            "DEX_WINDOWS_LAUNCHER": "1",
            "DEX_INSTALL_LOG": str(log_path),
            "WINDIR": r"C:\Windows",
        },
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert support.MESSAGE_W3 in result.stdout or "win32" in result.stdout
    assert "See the install log for the exact error:" in result.stdout
    assert str(log_path) in result.stdout


def test_linux_precheck_is_a_no_op() -> None:
    result = _source_support(
        "dex_support_shell_precheck\necho ok",
        env={"DEX_TEST_UNAME": "Linux", "DEX_TEST_PROC_VERSION": "Linux version 6.8.0"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout
    assert support.MESSAGE_W3 not in result.stdout
    assert support.MESSAGE_W4 not in result.stdout
