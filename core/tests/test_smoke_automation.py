"""Contract tests for the nightly smoke Launch Agent surfaces."""

from __future__ import annotations

import json
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER = REPO_ROOT / ".scripts" / "nightly-smoke.sh"
INSTALLER = REPO_ROOT / ".scripts" / "install-smoke-automation.sh"
TEMPLATE = REPO_ROOT / ".scripts" / "com.dex.smoke-nightly.plist.template"
LAUNCHD_RUNNER = REPO_ROOT / "scripts" / "run-nightly-smoke-as-launchd.sh"
LAUNCHD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"


def _render_plist(vault: Path, home: Path) -> dict:
    text = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("__VAULT_PATH__", str(vault))
        .replace("__HOME__", str(home))
    )
    return plistlib.loads(text.encode("utf-8"))


def test_shell_scripts_parse() -> None:
    for script in (WORKER, INSTALLER, LAUNCHD_RUNNER):
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_rendered_plist_is_valid(tmp_path: Path) -> None:
    rendered = tmp_path / "com.dex.smoke-nightly.plist"
    home = tmp_path / "home"
    text = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("__VAULT_PATH__", str(REPO_ROOT))
        .replace("__HOME__", str(home))
    )
    rendered.write_text(text, encoding="utf-8")
    with rendered.open("rb") as handle:
        data = plistlib.load(handle)

    assert data["ProgramArguments"] == ["/bin/bash", str(WORKER)]
    assert data["WorkingDirectory"] == str(REPO_ROOT)
    assert data["StartCalendarInterval"] == {"Hour": 3, "Minute": 15}
    assert data["RunAtLoad"] is False
    assert data["EnvironmentVariables"]["HOME"] == str(home)
    assert data["EnvironmentVariables"]["VAULT_PATH"] == str(REPO_ROOT)
    assert data["StandardOutPath"] == str(home / "Library" / "Logs" / "Dex" / "smoke-nightly.stdout.log")
    assert data["StandardErrorPath"] == str(home / "Library" / "Logs" / "Dex" / "smoke-nightly.stderr.log")
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
    return vault, {**os.environ, "HOME": str(home), "VAULT_PATH": str(vault)}


def _install_venv_python(vault: Path) -> Path:
    """Point the vault venv at this suite's interpreter so launchd PATH is enough."""
    python = vault / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/bash\n"
        f"exec {shlex.quote(sys.executable)} \"$@\"\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return python


def test_nightly_worker_sends_latest_ledger_before_success_heartbeat(tmp_path: Path) -> None:
    vault, env = _nightly_worker_fixture(tmp_path, smoke_exit=0)

    subprocess.run(["bash", str(WORKER)], env=env, check=True)

    call = (vault / "telemetry-called").read_text()
    assert "--report System/.smoke-last-run.json" in call
    assert f"--vault {vault}" in call
    assert f"--repo {vault}" in call
    assert "--channel stable" in call
    assert "nightly smoke completed" in (vault / ".scripts" / "logs" / "smoke-nightly.log").read_text()
    success = json.loads(
        (vault / "System" / ".dex" / "session-health-success.json").read_text()
    )
    assert success["schema_version"] == 1
    assert success["local_date"]
    assert success["completed_at"]


def test_nightly_worker_records_broken_verdict_without_success_heartbeat(tmp_path: Path) -> None:
    vault, env = _nightly_worker_fixture(tmp_path, smoke_exit=1)

    result = subprocess.run(["bash", str(WORKER)], env=env, check=False)

    assert result.returncode == 1
    assert (vault / "telemetry-called").exists()
    assert not (vault / ".scripts" / "logs" / "smoke-nightly.log").exists()
    assert not (vault / "System" / ".dex" / "session-health-success.json").exists()


def test_rendered_plist_gives_the_job_a_path_that_can_reach_node(tmp_path: Path) -> None:
    """launchd supplies a minimal PATH, so the job has to bring its own.

    Without this, smoke.py cannot find node, every .cjs hook syntax check
    reports UNKNOWN, and nightly hook checking is dead without looking broken.
    """
    rendered = TEMPLATE.read_text(encoding="utf-8").replace("__VAULT_PATH__", str(tmp_path))
    plist = plistlib.loads(rendered.encode("utf-8"))

    path = plist["EnvironmentVariables"]["PATH"].split(":")

    # Both Homebrew prefixes: Apple Silicon and Intel.
    assert "/opt/homebrew/bin" in path
    assert "/usr/local/bin" in path
    # The system locations the other shipped agents also carry.
    assert "/usr/bin" in path


def test_the_worker_widens_path_for_node_when_the_environment_hides_it(tmp_path: Path) -> None:
    """The worker must repair a minimal PATH itself, not rely on the plist.

    An install that already exists keeps its installed plist across updates,
    so a template-only fix would never reach it. The worker script does get
    updated, which is why the fallback lives here too.
    """
    fake_prefix = tmp_path / "opt" / "homebrew" / "bin"
    fake_prefix.mkdir(parents=True)
    node = fake_prefix / "node"
    node.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    node.chmod(0o755)

    # PATH must hide node for the fallback to be exercised at all, and
    # "/usr/bin:/bin" does not hide it everywhere: some hosts ship
    # /usr/bin/node, where the guard resolves node immediately and this test
    # silently asserts nothing. An empty directory hides it on every host.
    # The block below uses only bash builtins, and bash is invoked by absolute
    # path, so an otherwise-unusable PATH costs it nothing.
    empty = tmp_path / "empty-path"
    empty.mkdir()

    # Reproduce the worker's discovery block against a PATH with no node on it,
    # pointing it at the fake prefix instead of the real one.
    lines = WORKER.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("if ! command -v node"))
    # The block ends at the next unindented "fi", not the inner one.
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "fi")
    block = "\n".join(lines[start:end + 1]).replace("/opt/homebrew/bin", str(fake_prefix))

    result = subprocess.run(
        ["/bin/bash", "-c", f'PATH="{empty}"\n{block}\ncommand -v node'],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(node)


def test_the_worker_leaves_an_already_working_path_alone() -> None:
    """Anything already on PATH keeps priority; this only widens the search."""
    snippet = WORKER.read_text(encoding="utf-8")
    start = snippet.index("if ! command -v node")

    # The guard is a negative check, so a PATH that already resolves node is
    # never touched.
    assert snippet[start:].startswith("if ! command -v node >/dev/null 2>&1; then")
    assert 'PATH="$PATH:$NODE_DIR"' in snippet, "must append, never prepend or replace"


def test_rendered_plist_never_pins_a_machine_python_and_sets_home(tmp_path: Path) -> None:
    """A pinned interpreter path in the plist goes stale after a Python upgrade."""
    home = tmp_path / "home"
    plist = _render_plist(tmp_path, home)
    joined = " ".join(plist["ProgramArguments"])
    assert "python" not in joined.lower()
    assert plist["ProgramArguments"][0] == "/bin/bash"
    assert plist["EnvironmentVariables"]["HOME"] == str(home)
    assert plist["EnvironmentVariables"]["VAULT_PATH"] == str(tmp_path)


def test_worker_creates_log_directories_before_running_smoke(tmp_path: Path) -> None:
    vault, env = _nightly_worker_fixture(tmp_path, smoke_exit=1)
    logs = vault / ".scripts" / "logs"
    launchd_logs = Path(env["HOME"]) / "Library" / "Logs" / "Dex"
    assert not logs.exists()
    assert not launchd_logs.exists()

    result = subprocess.run(["bash", str(WORKER)], env=env, check=False)

    assert result.returncode == 1
    assert logs.is_dir()
    assert launchd_logs.is_dir()
    assert not (logs / "smoke-nightly.log").exists()


def test_worker_remaps_exit_78_so_launchd_does_not_call_it_a_config_error(
    tmp_path: Path,
) -> None:
    vault, env = _nightly_worker_fixture(tmp_path, smoke_exit=78)

    result = subprocess.run(
        ["bash", str(WORKER)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.returncode != 78
    assert "remapping to 1" in result.stderr
    assert (vault / "telemetry-called").exists()
    assert not (vault / ".scripts" / "logs" / "smoke-nightly.log").exists()


def test_worker_resolves_an_absolute_python_when_path_only_has_system_locations(
    tmp_path: Path,
) -> None:
    vault, env = _nightly_worker_fixture(tmp_path, smoke_exit=0)
    _install_venv_python(vault)

    env = {
        **env,
        "PATH": "/usr/bin:/bin",
        "VAULT_PATH": str(vault),
    }

    subprocess.run(["/bin/bash", str(WORKER)], env=env, check=True)
    assert "nightly smoke completed" in (vault / ".scripts" / "logs" / "smoke-nightly.log").read_text()


def test_worker_prefers_vault_path_from_the_environment_over_a_stale_breadcrumb(
    tmp_path: Path,
) -> None:
    vault, env = _nightly_worker_fixture(tmp_path, smoke_exit=0)
    stale = tmp_path / "stale-vault"
    stale.mkdir()
    Path(env["HOME"], ".config", "dex", "vault-path").write_text(str(stale), encoding="utf-8")
    env = {**env, "VAULT_PATH": str(vault)}

    subprocess.run(["bash", str(WORKER)], env=env, check=True)
    assert (vault / "telemetry-called").exists()
    assert not (stale / "telemetry-called").exists()


def test_worker_succeeds_when_home_is_missing_if_the_script_lives_in_the_vault(
    tmp_path: Path,
) -> None:
    vault, _env = _nightly_worker_fixture(tmp_path, smoke_exit=0)
    worker = vault / ".scripts" / "nightly-smoke.sh"
    shutil.copy2(WORKER, worker)
    worker.chmod(0o755)

    env = {key: value for key, value in os.environ.items() if key != "HOME"}
    env["VAULT_PATH"] = str(vault)
    env["LOGNAME"] = "dex-missing-home-user"
    env["USER"] = "dex-missing-home-user"

    subprocess.run(["bash", str(worker)], env=env, check=True)
    assert "nightly smoke completed" in (vault / ".scripts" / "logs" / "smoke-nightly.log").read_text()


def test_installer_creates_log_directories_and_substitutes_home(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    scripts = vault / ".scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(INSTALLER, scripts / "install-smoke-automation.sh")
    shutil.copy2(TEMPLATE, scripts / "com.dex.smoke-nightly.plist.template")
    shutil.copy2(WORKER, scripts / "nightly-smoke.sh")

    home = tmp_path / "home"
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launchctl = bin_dir / "launchctl"
    launchctl.write_text(
        "#!/bin/bash\n"
        "case \"$1\" in\n"
        "list) exit 1 ;;\n"
        "load) echo load \"$2\" >> \"$LAUNCHCTL_CALLS\" ;;\n"
        "unload) echo unload \"$2\" >> \"$LAUNCHCTL_CALLS\" ;;\n"
        "*) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    calls = tmp_path / "launchctl-calls"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "LAUNCHCTL_CALLS": str(calls),
    }

    subprocess.run(
        ["bash", str(scripts / "install-smoke-automation.sh")],
        env=env,
        check=True,
    )

    plist_path = agents / "com.dex.smoke-nightly.plist"
    with plist_path.open("rb") as handle:
        data = plistlib.load(handle)
    assert data["EnvironmentVariables"]["HOME"] == str(home)
    assert data["EnvironmentVariables"]["VAULT_PATH"] == str(vault)
    assert data["ProgramArguments"] == ["/bin/bash", str(scripts / "nightly-smoke.sh")]
    assert (home / "Library" / "Logs" / "Dex").is_dir()
    assert (vault / ".scripts" / "logs").is_dir()
    assert str(plist_path) in calls.read_text()


def test_launchd_runner_refuses_a_missing_working_directory(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    result = subprocess.run(
        ["bash", str(LAUNCHD_RUNNER), "--vault", str(missing), "--home", str(tmp_path / "home")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "missing" in result.stderr


def test_launchd_simulation_runs_the_worker_with_a_minimal_environment(
    tmp_path: Path,
) -> None:
    vault, _env = _nightly_worker_fixture(tmp_path, smoke_exit=0)
    shutil.copy2(WORKER, vault / ".scripts" / "nightly-smoke.sh")
    (vault / ".scripts" / "nightly-smoke.sh").chmod(0o755)
    _install_venv_python(vault)
    home = tmp_path / "launchd-home"

    result = subprocess.run(
        ["bash", str(LAUNCHD_RUNNER), "--vault", str(vault), "--home", str(home)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "nightly smoke completed" in (vault / ".scripts" / "logs" / "smoke-nightly.log").read_text()
    assert (home / "Library" / "Logs" / "Dex").is_dir()

