"""Windows-install helpers for Git Bash/Cygwin, Python fallback, and logging.

Joe's 2026-09-26 report: Windows 11, Git Bash with OSTYPE=cygwin, Python 3.12
from python.org, Dex 1.97.15. The installer treated that shell as Unix, looked
for python3 only, hid venv errors, and never checked a Windows Granola path.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from core.utils import platform_support as support

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_PS1 = REPO_ROOT / "install.ps1"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _source_helpers(script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged["DEX_INSTALL_LIB_ONLY"] = "1"
    merged.pop("DEX_INSTALL_PYTHON", None)
    if env:
        merged.update(env)
    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\n{script}',
        ],
        capture_output=True,
        text=True,
        timeout=20,
        env=merged,
    )


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


def test_cygwin_ostype_is_windows() -> None:
    result = _source_helpers(
        'if dex_is_windows; then echo windows; else echo unix; fi',
        env={"OSTYPE": "cygwin", "WINDIR": ""},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "windows"


def test_msys_and_win32_and_mingw_are_windows() -> None:
    for ostype in ("msys", "win32", "mingw64"):
        result = _source_helpers(
            'if dex_is_windows; then echo windows; else echo unix; fi',
            env={"OSTYPE": ostype, "WINDIR": ""},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "windows", ostype


def test_windir_marks_windows_even_when_ostype_is_unhelpful() -> None:
    result = _source_helpers(
        'if dex_is_windows; then echo windows; else echo unix; fi',
        env={"OSTYPE": "linux-gnu", "WINDIR": r"C:\Windows"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "windows"


def test_linux_without_windir_is_not_windows() -> None:
    result = _source_helpers(
        'if dex_is_windows; then echo windows; else echo unix; fi',
        env={"OSTYPE": "linux-gnu", "WINDIR": ""},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "unix"


def test_macos_is_not_windows() -> None:
    result = _source_helpers(
        'if dex_is_windows; then echo windows; else echo unix; fi',
        env={"OSTYPE": "darwin24", "WINDIR": ""},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "unix"


def test_existing_windows_venv_layout_wins_over_ostype(tmp_path: Path) -> None:
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "pip.exe").write_text("", encoding="utf-8")
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\ndex_resolve_venv_paths\nprintf "%s\\n" "$VENV_PIP"',
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "DEX_INSTALL_LIB_ONLY": "1", "OSTYPE": "linux-gnu", "WINDIR": ""},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ".venv/Scripts/pip.exe"


def test_cygwin_without_venv_uses_windows_scripts_paths() -> None:
    result = _source_helpers(
        'dex_resolve_venv_paths\nprintf "%s %s\\n" "$VENV_PYTHON" "$VENV_PIP"',
        env={"OSTYPE": "cygwin", "WINDIR": r"C:\Windows"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ".venv/Scripts/python.exe .venv/Scripts/pip.exe"


def test_windowsapps_match_requires_a_path_segment() -> None:
    nearby = _source_helpers(
        'if dex_is_windows_apps_stub "/tmp/test_windowsapps_name/python"; then echo stub; else echo real; fi'
    )
    assert nearby.returncode == 0, nearby.stderr
    assert nearby.stdout.strip() == "real"
    store = _source_helpers(
        'if dex_is_windows_apps_stub "/c/AppData/Local/Microsoft/WindowsApps/python3.exe"; then echo stub; else echo real; fi'
    )
    assert store.returncode == 0, store.stderr
    assert store.stdout.strip() == "stub"
    store_win = _source_helpers(
        r'if dex_is_windows_apps_stub "C:\AppData\Local\Microsoft\WindowsApps\python3.exe"; then echo stub; else echo real; fi'
    )
    assert store_win.returncode == 0, store_win.stderr
    assert store_win.stdout.strip() == "stub"


def test_store_alias_exit_9009_is_skipped_even_outside_windowsapps(tmp_path: Path) -> None:
    """The #752 journey puts a Store-style python3 first on PATH (exit 9009)."""
    stub_dir = tmp_path / "windowsapps-stub"
    real = tmp_path / "Python312"
    stub_dir.mkdir()
    real.mkdir()
    _write_executable(
        stub_dir / "python3",
        """#!/bin/sh
echo "Python was not found; run without arguments to install from the Microsoft Store, or disable this shortcut from Settings > Apps > Advanced app settings > App execution aliases." >&2
exit 9009
""",
    )
    _write_executable(
        real / "python",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.12.1"; exit 0; fi
if [ "$1" = "-c" ]; then echo "$0"; exit 0; fi
exit 0
""",
    )
    env = os.environ.copy()
    env.pop("DEX_INSTALL_PYTHON", None)
    env.update(
        {
            "PATH": f"{stub_dir}:{real}",
            "DEX_INSTALL_LIB_ONLY": "1",
            "OSTYPE": "cygwin",
            "WINDIR": r"C:\Windows",
        }
    )
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\ndex_resolve_python\nprintf "%s %s\\n" "$PYTHON_CMD" "$PYTHON_VERSION"',
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip().endswith("3.12.1")
    assert str(real / "python") in result.stdout
    assert "windowsapps-stub" not in result.stdout


def test_windowsapps_python3_stub_is_skipped_even_when_version_looks_fine(tmp_path: Path) -> None:
    apps = tmp_path / "Local" / "Microsoft" / "WindowsApps"
    real = tmp_path / "Python312"
    apps.mkdir(parents=True)
    real.mkdir()
    _write_executable(
        apps / "python3",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.12.0"; exit 0; fi
if [ "$1" = "-c" ]; then echo "$0"; exit 0; fi
exit 0
""",
    )
    _write_executable(
        real / "python",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.12.1"; exit 0; fi
if [ "$1" = "-c" ]; then echo "$0"; exit 0; fi
exit 0
""",
    )
    env = os.environ.copy()
    env.pop("DEX_INSTALL_PYTHON", None)
    env.update(
        {
            "PATH": f"{apps}:{real}",
            "DEX_INSTALL_LIB_ONLY": "1",
            "OSTYPE": "cygwin",
            "WINDIR": r"C:\Windows",
        }
    )
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\ndex_resolve_python\nprintf "%s %s\\n" "$PYTHON_CMD" "$PYTHON_VERSION"',
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip().endswith("3.12.1")
    assert "WindowsApps" not in result.stdout
    assert str(real / "python") in result.stdout


def test_dex_install_python_is_used_before_path_python3(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    preferred_dir = tmp_path / "preferred"
    bin_dir.mkdir()
    preferred_dir.mkdir()
    preferred = preferred_dir / "python"
    _write_executable(
        bin_dir / "python3",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.11.0"; exit 0; fi
if [ "$1" = "-c" ]; then echo "$0"; exit 0; fi
exit 0
""",
    )
    _write_executable(
        preferred,
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.12.8"; exit 0; fi
if [ "$1" = "-c" ]; then echo "$0"; exit 0; fi
exit 0
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(bin_dir),
            "DEX_INSTALL_LIB_ONLY": "1",
            "DEX_INSTALL_PYTHON": str(preferred),
        }
    )
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\ndex_resolve_python\nprintf "%s %s\\n" "$PYTHON_CMD" "$PYTHON_VERSION"',
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip().endswith("3.12.8")
    assert str(preferred) in result.stdout


def test_dex_install_python_windowsapps_is_rejected_then_fallback(tmp_path: Path) -> None:
    apps = tmp_path / "Microsoft" / "WindowsApps"
    real = tmp_path / "bin"
    apps.mkdir(parents=True)
    real.mkdir()
    stub = apps / "python3"
    _write_executable(
        stub,
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.12.0"; exit 0; fi
if [ "$1" = "-c" ]; then echo "$0"; exit 0; fi
exit 0
""",
    )
    _write_executable(
        real / "python",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.12.4"; exit 0; fi
if [ "$1" = "-c" ]; then echo "$0"; exit 0; fi
exit 0
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(real),
            "DEX_INSTALL_LIB_ONLY": "1",
            "DEX_INSTALL_PYTHON": str(stub),
        }
    )
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\ndex_resolve_python\nprintf "%s %s\\n" "$PYTHON_CMD" "$PYTHON_VERSION"',
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip().endswith("3.12.4")
    assert "WindowsApps" not in result.stdout


def test_python_fallback_uses_py_dash_three_when_python3_is_missing(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "py",
        """#!/bin/sh
if [ "$1" = "-3" ] && [ "$2" = "--version" ]; then echo "Python 3.12.4"; exit 0; fi
if [ "$1" = "-3" ] && [ "$2" = "-c" ]; then echo "$0"; exit 0; fi
exit 1
""",
    )
    _write_executable(
        bin_dir / "python",
        """#!/bin/sh
echo "Python 3.9.0"
exit 0
""",
    )
    env = os.environ.copy()
    env.pop("DEX_INSTALL_PYTHON", None)
    env.update(
        {
            "PATH": str(bin_dir),
            "DEX_INSTALL_LIB_ONLY": "1",
            "OSTYPE": "cygwin",
            "WINDIR": r"C:\Windows",
        }
    )
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\ndex_resolve_python\nprintf "%s %s\\n" "$PYTHON_CMD" "$PYTHON_VERSION"',
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip().endswith("3.12.4")
    assert str(bin_dir / "py") in result.stdout


def test_python_fallback_skips_old_python3_and_uses_python(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "python3",
        """#!/bin/sh
echo "Python 3.9.18"
exit 0
""",
    )
    _write_executable(
        bin_dir / "python",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.12.0"; exit 0; fi
if [ "$1" = "-c" ]; then echo "$0"; exit 0; fi
exit 0
""",
    )
    env = os.environ.copy()
    env.pop("DEX_INSTALL_PYTHON", None)
    env.update({"PATH": str(bin_dir), "DEX_INSTALL_LIB_ONLY": "1"})
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\ndex_resolve_python\nprintf "%s\\n" "$PYTHON_VERSION"',
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip() == "3.12.0"


def test_granola_skips_quietly_when_shared_module_is_missing(tmp_path: Path) -> None:
    roaming = tmp_path / "AppData" / "Roaming" / "Granola"
    roaming.mkdir(parents=True)
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\n'
            "if dex_granola_locator_present; then echo present; else echo missing; fi\n"
            "if dex_granola_via_shared_module; then echo detected; else echo skipped; fi",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        env={
            **os.environ,
            "DEX_INSTALL_LIB_ONLY": "1",
            "APPDATA": str(tmp_path / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(tmp_path / "AppData" / "Local"),
            "USERPROFILE": str(tmp_path),
        },
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.splitlines() == ["missing", "skipped"]


def test_granola_uses_shared_module_when_present(tmp_path: Path) -> None:
    integrations = tmp_path / "core" / "integrations"
    integrations.mkdir(parents=True)
    (tmp_path / "core" / "__init__.py").write_text("", encoding="utf-8")
    (integrations / "__init__.py").write_text("", encoding="utf-8")
    (integrations / "granola_paths.py").write_text(
        """import json, sys
json.dump({
    "installed": True,
    "app_path": r"C:\\\\AppData\\\\Local\\\\Programs\\\\@granolaelectron\\\\Granola.exe",
    "app_path_posix": "/c/AppData/Local/Programs/@granolaelectron/Granola.exe",
    "data_path": None,
    "data_path_posix": None,
}, sys.stdout)
sys.exit(0)
""",
        encoding="utf-8",
    )
    roaming = tmp_path / "AppData" / "Roaming" / "Granola"
    roaming.mkdir(parents=True)
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\nPYTHON_CMD="{sys.executable}"\ndex_granola_via_shared_module',
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        env={
            **os.environ,
            "DEX_INSTALL_LIB_ONLY": "1",
            "APPDATA": str(tmp_path / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(tmp_path / "AppData" / "Local"),
            "USERPROFILE": str(tmp_path),
        },
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip() == "/c/AppData/Local/Programs/@granolaelectron/Granola.exe"


def test_venv_failure_writes_stderr_to_install_log_and_names_the_path(tmp_path: Path) -> None:
    root, environment = _windows_like_install_fixture(tmp_path, venv_fails=True)
    result = subprocess.run(
        ["/bin/bash", "install.sh"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        input="\n",
    )
    log_path = Path(environment["DEX_INSTALL_LOG"])
    assert log_path.is_file(), result.stdout + result.stderr
    log_text = log_path.read_text(encoding="utf-8")
    assert "simulated venv failure" in log_text
    assert "See the install log for the exact error:" in result.stdout
    assert str(log_path) in result.stdout
    assert "2>/dev/null" not in (REPO_ROOT / "install.sh").read_text(encoding="utf-8").split(
        "Creating virtual environment"
    )[1].split("Work MCP dependencies")[0]


def test_spaces_in_install_log_path_are_quoted(tmp_path: Path) -> None:
    log_dir = tmp_path / "log dir with spaces"
    log_dir.mkdir()
    log_path = log_dir / "install.log"
    result = _source_helpers(
        f'DEX_INSTALL_LOG="{log_path}"\ndex_init_install_log\ndex_log "hello"\ntest -f "$INSTALL_LOG" && echo ok',
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
    assert "hello" in log_path.read_text(encoding="utf-8")


def test_install_sh_does_not_swallow_venv_or_pip_stderr() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "WindowsApps" in text
    assert "DEX_INSTALL_PYTHON" in text
    assert "DEX_INSTALL_NONINTERACTIVE" in text
    assert "core.integrations.granola_paths" in text
    assert "dex_run_logged \"python -m venv\"" in text
    assert "dex_run_logged \"pip install\"" in text
    assert "-m venv .venv 2>/dev/null" not in text
    assert "2>/dev/null" not in text.split("Setting up Python environment")[1].split("Verifying Work MCP")[0]
    assert "npm ci" in text
    assert "pnpm install --frozen-lockfile" in text
    assert "npm install\n" not in text
    assert "--require-hashes" in text
    assert "requirements.hash.txt" in text
    assert "dex_support_python_probe" in text
    assert "DEX_SUPPORT_LIB_ONLY" in text
    assert "dex_bootstrap_clone" in text
    assert "git clone --quiet --branch" in text
    assert "dex_should_bootstrap" in text


def test_readme_does_not_recommend_bypass_or_remote_iex() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "ExecutionPolicy Bypass" not in text
    assert "irm https://heydex.ai/install.ps1 | iex" not in text
    assert "clone --branch release --single-branch" in text
    assert "Git Bash" in text
    assert "bash ./install.sh" in text
    assert "--require-hashes" in text
    assert "PowerShell" not in text
    assert "```powershell" not in text


def test_installers_require_python_3_11() -> None:
    sh = INSTALL_SH.read_text(encoding="utf-8")
    ps1 = INSTALL_PS1.read_text(encoding="utf-8")
    assert 'minor" -lt 11' in sh
    assert "$minor -lt 11" in ps1
    assert "Python 3.11+" in sh
    assert "Python 3.11+" in ps1
    assert "Python 3.10+" not in sh
    assert "Python 3.10+" not in ps1


def test_python_3_10_is_rejected(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "python3",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.10.14"; exit 0; fi
if [ "$1" = "-c" ]; then echo "$0"; exit 0; fi
exit 0
""",
    )
    result = _source_helpers(
        'if dex_resolve_python; then echo accepted "$PYTHON_VERSION"; else echo rejected; fi',
        env={"PATH": str(bin_dir), "OSTYPE": "linux-gnu", "WINDIR": ""},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "rejected"


def test_hashed_requirements_are_uv_universal_with_win_and_mac() -> None:
    text = (REPO_ROOT / "core" / "mcp" / "requirements.hash.txt").read_text(encoding="utf-8")
    assert "autogenerated by uv" in text
    assert (
        "uv pip compile --python-version 3.11 --universal --generate-hashes "
        "--output-file=core/mcp/requirements.hash.txt core/mcp/requirements.txt"
    ) in text
    assert "f87b87" in text
    assert "f87f87" not in text
    assert "pywin32==" in text
    assert "sys_platform == 'win32'" in text
    assert "pyobjc-core==" in text
    assert "pyobjc-framework-eventkit==" in text
    assert "sys_platform == 'darwin'" in text
    assert "--hash=sha256:" in text
    assert "hand-copied" not in text
    assert "PyPI JSON API" not in text


def test_hashed_requirements_drift_check_compiles_into_an_empty_file() -> None:
    script = (
        REPO_ROOT / "scripts" / "check-hashed-python-requirements.sh"
    ).read_text(encoding="utf-8")
    assert ': > "$OUTPUT"' in script
    assert "--constraint" in script
    assert "UV_CUSTOM_COMPILE_COMMAND" in script
    assert "significant(committed)" in script
    assert "clean-empty-compile" in script
    assert "pypi.org/pypi" in script
    assert "--output-file=core/mcp/requirements.hash.txt" in script
    assert '--output-file="$OUTPUT"' in script


def test_hashed_requirements_workflow_is_separate_from_required_gates() -> None:
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "hashed-python-requirements.yml"
    ).read_text(encoding="utf-8")
    assert "name: Hashed Python requirements" in workflow
    assert "scripts/check-hashed-python-requirements.sh" in workflow
    assert "--output-file=core/mcp/requirements.hash.txt core/mcp/requirements.txt" not in workflow
    assert 'python-version: [\'3.11\', \'3.12\']' in workflow
    assert "3.13t" not in workflow
    assert 'checksum: "23bf5552d220e0842b65c862097b2ebaeba0064b74eda5e565e77fd25969d8c8"' in workflow
    assert "pip install --require-hashes" in workflow
    assert "windows-latest" in workflow
    assert "macos-latest" in workflow
    assert "jobs:\n  quality:" not in workflow
    assert "jobs:\n  tests:" not in workflow
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "hashed-python-requirements" not in ci


def test_windows_default_folder_and_onedrive_warning() -> None:
    result = _source_helpers(
        "dex_default_target",
        env={
            "HOME": "/c/Users/joe",
            "USERPROFILE": "C:\\Users\\joe",
            "DEX_INSTALL_REF": "release",
            "OSTYPE": "msys",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("/Dex")
    cloud = _source_helpers(
        'dex_cloud_provider "/c/Users/joe/OneDrive/Documents/Dex"',
        env={"OSTYPE": "msys"},
    )
    assert cloud.returncode == 0, cloud.stderr
    assert cloud.stdout.strip() == "OneDrive"


def test_install_ps1_interactive_refuses_with_git_bash_message() -> None:
    text = INSTALL_PS1.read_text(encoding="utf-8")
    assert "Dex on Windows installs from Git Bash, not from PowerShell." in text
    assert "Open Git Bash" in text
    assert "git-scm.com/download/win" in text


def test_install_ps1_prefers_git_bash_over_wsl() -> None:
    text = INSTALL_PS1.read_text(encoding="utf-8")
    assert "function Get-DexGitBash" in text
    assert "Git\\bin\\bash.exe" in text
    assert "System32[\\\\/]bash\\.exe" in text or r"System32[\\/]bash\.exe" in text


def test_install_ps1_covers_the_same_windows_install_contract() -> None:
    text = INSTALL_PS1.read_text(encoding="utf-8")
    assert "Resolve-DexPython" in text
    assert "Test-DexWindowsAppsStub" in text
    assert "DEX_INSTALL_PYTHON" in text
    assert "DEX_INSTALL_NONINTERACTIVE" in text
    assert "handing off to install.sh" in text
    assert '@("-3")' in text or '"-3"' in text
    assert "python3" in text
    assert "AppData\\Roaming\\Granola" in text or 'Join-Path $env:APPDATA "Granola"' in text
    assert "@granolaelectron" in text
    assert ".venv\\Scripts\\python.exe" in text
    assert "System\\.dex\\install.log" in text
    assert "core/provision.cjs" in text
    assert "--install-config-only" in text
    assert "--adopt" in text
    assert "v1-to-v2-brain-vault-split.cjs" in text
    assert "2>$null" not in text.split("Creating virtual environment")[1].split("Verifying Work MCP")[0]
    assert "LiteralPath" in text
    assert "clone --branch release --single-branch" in text
    assert "ExecutionPolicy Bypass" not in text
    assert "RemoteSigned" in text
    assert "-Scope Process" in text
    assert "Do not pipe a remote script into iex" in text
    assert '@("ci")' in text or '"ci"' in text
    assert "--frozen-lockfile" in text
    assert "--require-hashes" in text
    assert "requirements.hash.txt" in text
    assert "core.utils.platform_support" in text
    assert "winget" not in text.lower()
    assert "Get-DexGitBash" in text
    assert "Python 3.11+" in text
    assert "Dex on Windows installs from Git Bash, not from PowerShell." in text


def test_install_ps1_is_classified_as_brain() -> None:
    from core import portable_contract

    rule = portable_contract.resolve("install.ps1")
    assert rule.ownership == "brain"


def test_install_ps1_is_held_out_of_releases_until_installed_contracts_know_it() -> None:
    text = (REPO_ROOT / ".distignore").read_text(encoding="utf-8")
    assert "install.ps1" in text
    assert "unclassified" in text


def _windows_like_install_fixture(
    tmp_path: Path,
    *,
    venv_fails: bool,
) -> tuple[Path, dict[str, str]]:
    real_node = shutil.which("node")
    if real_node is None:
        raise RuntimeError("Node is required for the install fixture")
    root = tmp_path / "dex-install"
    root.mkdir()
    shutil.copy2(INSTALL_SH, root / "install.sh")
    (root / "System").mkdir()
    (root / "System" / ".mcp.json.example").write_text("{}\n", encoding="utf-8")
    (root / "core" / "migrations").mkdir(parents=True)
    (root / "core" / "migrations" / "v1-to-v2-brain-vault-split.cjs").write_text(
        "// shim\n", encoding="utf-8"
    )
    (root / "core" / "mcp").mkdir()
    (root / "core" / "mcp" / "requirements.txt").write_text("", encoding="utf-8")
    (root / "core" / "mcp" / "requirements.hash.txt").write_text("# fixture\n", encoding="utf-8")
    (root / "package-lock.json").write_text('{ "lockfileVersion": 3 }\n', encoding="utf-8")

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    venv_exit = "1" if venv_fails else "0"
    _write_executable(
        shim_dir / "git",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "git version 2.50.0"; fi
exit 0
""",
    )
    _write_executable(
        shim_dir / "node",
        f"""#!/bin/sh
if [ "$1" = "-v" ]; then echo "v22.0.0"; exit 0; fi
printf '%s\\n' "$*" >> "$DEX_TEST_NODE_LOG"
if [ "$1" = "-e" ]; then exec "{real_node}" "$@"; fi
exit 0
""",
    )
    _write_executable(
        shim_dir / "python3",
        f"""#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.12.0"; exit 0; fi
if [ "$1" = "-c" ]; then echo "$0"; exit 0; fi
if [ "$1" = "-m" ] && [ "$2" = "core.harnesses.registry" ]; then
  printf '%s\\n' "[]"
  exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  if [ "{venv_exit}" = "1" ]; then
    echo "simulated venv failure" >&2
    exit 1
  fi
  mkdir -p "$3/Scripts"
  printf '#!/bin/sh\\nexit 0\\n' > "$3/Scripts/pip.exe"
  printf '#!/bin/sh\\nif [ "$1" = "-c" ]; then echo win32; exit 0; fi\\nexit 0\\n' > "$3/Scripts/python.exe"
  chmod +x "$3/Scripts/pip.exe" "$3/Scripts/python.exe"
fi
exit 0
""",
    )
    for command in ("npm", "npx"):
        _write_executable(shim_dir / command, "#!/bin/sh\nexit 0\n")

    log_path = tmp_path / "install.log"
    environment = os.environ.copy()
    environment.pop("DEX_INSTALL_PYTHON", None)
    environment.update(
        {
            "PATH": f"{shim_dir}:/usr/bin:/bin",
            "OSTYPE": "cygwin",
            "WINDIR": r"C:\Windows",
            "DEX_INSTALL_LOG": str(log_path),
            "DEX_INSTALL_NONINTERACTIVE": "1",
            "DEX_TEST_NODE_LOG": str(tmp_path / "node.log"),
        }
    )
    return root, environment


def test_cygwin_install_uses_windows_venv_scripts_and_finishes(tmp_path: Path) -> None:
    root, environment = _windows_like_install_fixture(tmp_path, venv_fails=False)
    result = subprocess.run(
        ["/bin/bash", "install.sh"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / ".venv" / "Scripts" / "pip.exe").is_file()
    assert "Dex installation complete" in result.stdout
    assert "Python 3.12.0" in result.stdout
    assert "Granola app check skipped" in result.stdout
    assert "shared locator not in this checkout yet" in result.stdout


@pytest.mark.skipif(shutil.which("pwsh") is None and shutil.which("powershell") is None, reason="PowerShell is not installed")
def test_install_ps1_lib_only_can_be_dot_sourced() -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    result = subprocess.run(
        [shell, "-NoProfile", "-Command", f"$env:DEX_INSTALL_LIB_ONLY='1'; . '{INSTALL_PS1}'; Resolve-DexPython | Out-Null; 'ok'"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


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
            "DEX_TEST_VAULT_PATH": "/mnt/c/Documents/Dex",
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


def test_python_probe_returns_nonzero_when_module_refuses(tmp_path: Path) -> None:
    """A failed probe must not be turned into success by reading $? after `if !`."""
    root = tmp_path / "dex"
    (root / "core" / "utils").mkdir(parents=True)
    (root / "core" / "utils" / "platform_support.py").write_text("# stub presence\n", encoding="utf-8")
    log_path = tmp_path / "install.log"
    log_path.write_text("", encoding="utf-8")
    stub = tmp_path / "refuse-python"
    _write_executable(
        stub,
        """#!/bin/sh
echo '{"verdict":"unsupported"}'
exit 7
""",
    )
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\ndex_support_python_probe',
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
        env={
            **os.environ,
            "DEX_SUPPORT_LIB_ONLY": "1",
            "PYTHON_CMD": str(stub),
            "DEX_INSTALL_LOG": str(log_path),
        },
    )
    assert result.returncode == 7, result.stdout + result.stderr
    assert "See the install log for the exact error:" in result.stdout
    assert str(log_path) in result.stdout


def test_python_probe_returns_zero_when_module_accepts(tmp_path: Path) -> None:
    root = tmp_path / "dex"
    (root / "core" / "utils").mkdir(parents=True)
    (root / "core" / "utils" / "platform_support.py").write_text("# stub presence\n", encoding="utf-8")
    stub = tmp_path / "ok-python"
    _write_executable(
        stub,
        """#!/bin/sh
echo '{"verdict":"supported"}'
exit 0
""",
    )
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'set -e\n. "{INSTALL_SH}"\ndex_support_python_probe\necho accepted',
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
        env={
            **os.environ,
            "DEX_SUPPORT_LIB_ONLY": "1",
            "PYTHON_CMD": str(stub),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "accepted" in result.stdout
    assert "See the install log for the exact error:" not in result.stdout

