"""Contract tests for the nightly smoke Launch Agent surfaces."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER = REPO_ROOT / ".scripts" / "nightly-smoke.sh"
INSTALLER = REPO_ROOT / ".scripts" / "install-smoke-automation.sh"
TEMPLATE = REPO_ROOT / ".scripts" / "com.dex.smoke-nightly.plist.template"


def test_shell_scripts_parse() -> None:
    for script in (WORKER, INSTALLER):
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_rendered_plist_is_valid(tmp_path: Path) -> None:
    rendered = tmp_path / "com.dex.smoke-nightly.plist"
    rendered.write_text(TEMPLATE.read_text().replace("__VAULT_PATH__", str(REPO_ROOT)))
    with rendered.open("rb") as handle:
        data = plistlib.load(handle)

    assert data["ProgramArguments"] == ["/bin/bash", str(WORKER)]
    assert data["StartCalendarInterval"] == {"Hour": 3, "Minute": 15}
    assert data["RunAtLoad"] is False
    if shutil.which("plutil"):
        subprocess.run(["plutil", "-lint", str(rendered)], check=True)


def test_installer_status_and_uninstall_use_stubbed_launchctl(tmp_path: Path) -> None:
    home = tmp_path / "home"
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    plist = agents / "com.dex.smoke-nightly.plist"
    plist.write_text("installed")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launchctl = bin_dir / "launchctl"
    launchctl.write_text(
        "#!/bin/bash\n"
        "case \"$1\" in\n"
        "list) echo '1 0 com.dex.smoke-nightly' ;;\n"
        "unload) echo \"$2\" >> \"$LAUNCHCTL_CALLS\" ;;\n"
        "*) exit 2 ;;\n"
        "esac\n"
    )
    launchctl.chmod(0o755)
    calls = tmp_path / "launchctl-calls"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "LAUNCHCTL_CALLS": str(calls),
    }

    status = subprocess.run(
        ["bash", str(INSTALLER), "--status"],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "is installed" in status.stdout
    assert "is loaded" in status.stdout

    subprocess.run(["bash", str(INSTALLER), "--uninstall"], env=env, check=True)
    assert not plist.exists()
    assert str(plist) in calls.read_text()


def _nightly_worker_fixture(tmp_path: Path, *, smoke_exit: int) -> tuple[Path, dict[str, str]]:
    vault = tmp_path / "vault"
    (vault / "core" / "utils").mkdir(parents=True)
    (vault / ".scripts").mkdir()
    (vault / "core" / "utils" / "smoke.py").write_text(
        textwrap.dedent(
            f"""
            import json
            from pathlib import Path

            report = {{
                "schema_version": 1,
                "summary": {{"ok": 4, "broken": {smoke_exit}, "unknown": 0, "off": 0}},
                "journeys": [],
            }}
            target = Path("System/.smoke-last-run.json")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report))
            raise SystemExit({smoke_exit})
            """
        ),
        encoding="utf-8",
    )
    (vault / "core" / "utils" / "health_telemetry.py").write_text(
        textwrap.dedent(
            """
            import json
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            report_path = Path(args[args.index("--report") + 1])
            assert json.loads(report_path.read_text())["summary"]["ok"] == 4
            Path("telemetry-called").write_text(" ".join(args))
            """
        ),
        encoding="utf-8",
    )
    home = tmp_path / "home"
    breadcrumb = home / ".config" / "dex" / "vault-path"
    breadcrumb.parent.mkdir(parents=True)
    breadcrumb.write_text(str(vault), encoding="utf-8")
    return vault, {**os.environ, "HOME": str(home)}


def test_nightly_worker_sends_latest_ledger_before_success_heartbeat(tmp_path: Path) -> None:
    vault, env = _nightly_worker_fixture(tmp_path, smoke_exit=0)

    subprocess.run(["bash", str(WORKER)], env=env, check=True)

    call = (vault / "telemetry-called").read_text()
    assert "--report System/.smoke-last-run.json" in call
    assert f"--vault {vault}" in call
    assert f"--repo {vault}" in call
    assert "--channel stable" in call
    assert "nightly smoke completed" in (vault / ".scripts" / "logs" / "smoke-nightly.log").read_text()


def test_nightly_worker_records_broken_verdict_without_success_heartbeat(tmp_path: Path) -> None:
    vault, env = _nightly_worker_fixture(tmp_path, smoke_exit=1)

    result = subprocess.run(["bash", str(WORKER)], env=env, check=False)

    assert result.returncode == 1
    assert (vault / "telemetry-called").exists()
    assert not (vault / ".scripts" / "logs" / "smoke-nightly.log").exists()
