"""Behavior tests for the background learning LaunchAgent installer."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / ".scripts" / "install-learning-automation.sh"
CHANGELOG_PLIST = REPO_ROOT / ".scripts" / "com.dex.changelog-checker.plist"
LEARNING_PLIST = REPO_ROOT / ".scripts" / "com.dex.learning-review.plist"


def test_documents_vault_does_not_claim_blocked_learning_review_is_active(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    scripts = home / "Documents" / "Dex" / ".scripts"
    scripts.mkdir(parents=True)
    for source in (INSTALLER, CHANGELOG_PLIST, LEARNING_PLIST):
        shutil.copy2(source, scripts / source.name)

    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    installed_learning_plist = agents / LEARNING_PLIST.name
    installed_learning_plist.write_text("previous broken job", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "launchctl-calls"
    launchctl = bin_dir / "launchctl"
    launchctl.write_text(
        "#!/bin/bash\n"
        "case \"${1:-}\" in\n"
        "  list) printf '%s\\n' '- 126 com.dex.learning-review' ;;\n"
        "  load|unload) printf '%s %s\\n' \"$1\" \"$2\" >> \"$LAUNCHCTL_CALLS\" ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    node = bin_dir / "node"
    node.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    node.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "LAUNCHCTL_CALLS": str(calls),
    }

    result = subprocess.run(
        ["bash", str(scripts / INSTALLER.name)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    launchctl_calls = calls.read_text(encoding="utf-8") if calls.exists() else ""

    assert {
        "returncode": result.returncode,
        "learning_plist_exists": installed_learning_plist.exists(),
        "learning_load_requested": any(
            line.startswith("load ") and line.endswith(LEARNING_PLIST.name)
            for line in launchctl_calls.splitlines()
        ),
        "changelog_load_requested": any(
            line.startswith("load ") and line.endswith(CHANGELOG_PLIST.name)
            for line in launchctl_calls.splitlines()
        ),
        "explains_privacy_block": "macOS privacy blocks background shell jobs" in result.stdout,
        "reports_not_installed": "Learning Review: Not installed" in result.stdout,
    } == {
        "returncode": 0,
        "learning_plist_exists": False,
        "learning_load_requested": False,
        "changelog_load_requested": True,
        "explains_privacy_block": True,
        "reports_not_installed": True,
    }
