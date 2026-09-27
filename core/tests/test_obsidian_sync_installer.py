from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "core" / "obsidian" / "install_sync_daemon.sh"
LABEL = "com.dex.obsidian-sync"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def _run_installer(
    tmp_path: Path,
    *,
    launch_status: int = 0,
    supported_python: bool = True,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    fake_bin = tmp_path / "bin"
    calls = tmp_path / "calls.log"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    (vault / "System").mkdir(parents=True)
    fake_bin.mkdir()

    version_exit = 0 if supported_python else 1
    python = fake_bin / "python3"
    _write_executable(
        python,
        f"""#!/bin/bash
printf 'python3:%s\\n' "$*" >> "$CALL_LOG"
if [[ "$*" == *"sys.version_info"* ]]; then exit {version_exit}; fi
if [[ "$1" == "-c" && "$2" == "import watchdog" ]]; then exit 1; fi
if [[ "$1" == "-m" && "$2" == "pip" && "$3" == "install" && "$4" == "watchdog" ]]; then exit 0; fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "pip3",
        """#!/bin/bash
printf 'pip3:%s\n' "$*" >> "$CALL_LOG"
exit 0
""",
    )
    _write_executable(
        fake_bin / "launchctl",
        f"""#!/bin/bash
printf 'launchctl:%s\\n' "$*" >> "$CALL_LOG"
case "$1" in
  list) printf '%s\\n' $'-\\t{launch_status}\\t{LABEL}' ;;
  load|unload) exit 0 ;;
  *) exit 2 ;;
esac
""",
    )
    _write_executable(fake_bin / "sleep", "#!/bin/bash\nexit 0\n")

    env = os.environ.copy()
    env.update(
        {
            "CALL_LOG": str(calls),
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "VAULT_PATH": str(vault),
        }
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            'OSTYPE=darwin; source "$1"',
            "obsidian-installer-test",
            str(INSTALLER),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    plist = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    return result, plist, calls


def test_installer_pins_and_reuses_one_supported_python(tmp_path: Path) -> None:
    result, plist, calls = _run_installer(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    with plist.open("rb") as handle:
        payload = plistlib.load(handle)
    selected_python = str(tmp_path / "bin" / "python3")
    assert payload["ProgramArguments"][0] == selected_python
    assert "PATH" in payload["EnvironmentVariables"]
    assert "python3:-m pip install watchdog" in calls.read_text()
    assert "pip3:" not in calls.read_text()


def test_installer_rejects_python_older_than_runtime_requires(tmp_path: Path) -> None:
    result, plist, _calls = _run_installer(tmp_path, supported_python=False)

    assert result.returncode == 1
    assert "Python 3.11 or newer" in result.stdout
    assert not plist.exists()


def test_installer_does_not_report_success_for_crash_loop(tmp_path: Path) -> None:
    result, _plist, _calls = _run_installer(tmp_path, launch_status=1)

    assert result.returncode == 1
    assert "installed and started successfully" not in result.stdout
    assert "exit status 1" in result.stdout
