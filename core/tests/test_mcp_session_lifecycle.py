"""DEX-156: google-workspace-mcp must not outlive the Claude Code session."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.utils import mcp_session_lifecycle as lifecycle

REPO_ROOT = Path(__file__).resolve().parents[2]
PAIR_FIXTURE = REPO_ROOT / "core/tests/fixtures/google_workspace_mcp_pair.py"
MODULE = REPO_ROOT / "core/utils/mcp_session_lifecycle.py"
SETTINGS = REPO_ROOT / ".claude/settings.json"

pytestmark = pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX")


def _wait_until(predicate, *, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _read_pair(marker: Path) -> tuple[int, int]:
    assert _wait_until(lambda: marker.exists() and len(marker.read_text().split()) == 2)
    parent_text, child_text = marker.read_text(encoding="utf-8").split()
    return int(parent_text), int(child_text)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _child_command(marker: Path) -> str:
    return "\n".join([sys.executable, str(PAIR_FIXTURE), str(marker), "google-workspace-mcp", "serve"])


def _serve_env(tmp_path: Path, marker: Path, session_id: str) -> dict[str, str]:
    env = os.environ.copy()
    env["DEX_MCP_LIFECYCLE_DIR"] = str(tmp_path / "lifecycle")
    env["DEX_MCP_LIFECYCLE_CHILD"] = _child_command(marker)
    env["DEX_MCP_SESSION_ID"] = session_id
    env["VAULT_PATH"] = str(tmp_path)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return env


def _start_wrapper(tmp_path: Path, session_id: str) -> tuple[subprocess.Popen[bytes], Path, int, int]:
    marker = tmp_path / f"{session_id}.pair"
    process = subprocess.Popen(
        [sys.executable, str(MODULE), "serve", "--vault", str(tmp_path), "--session-id", session_id],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_serve_env(tmp_path, marker, session_id),
    )
    parent_pid, child_pid = _read_pair(marker)
    assert _alive(parent_pid), "connector parent never started"
    assert _alive(child_pid), "connector child never started"
    return process, marker, parent_pid, child_pid


def _stop_wrapper(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


@pytest.fixture
def isolated_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEX_MCP_LIFECYCLE_DIR", str(tmp_path / "lifecycle"))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    yield tmp_path
    for record in lifecycle.list_managed_processes():
        if str(tmp_path) in record.cmdline or str(PAIR_FIXTURE) in record.cmdline:
            try:
                os.killpg(record.pgid, signal.SIGKILL)
            except OSError:
                try:
                    os.kill(record.pid, signal.SIGKILL)
                except OSError:
                    pass


def test_stdin_close_reaps_the_process_pair(isolated_lifecycle: Path) -> None:
    wrapper, _marker, parent_pid, child_pid = _start_wrapper(isolated_lifecycle, "tab-one")
    assert wrapper.stdin is not None
    wrapper.stdin.close()
    wrapper.wait(timeout=5)
    assert _wait_until(lambda: not _alive(parent_pid) and not _alive(child_pid))
    assert not _alive(parent_pid)
    assert not _alive(child_pid)
    assert not _alive(wrapper.pid)


def test_sigterm_on_wrapper_reaps_the_process_pair(isolated_lifecycle: Path) -> None:
    wrapper, _marker, parent_pid, child_pid = _start_wrapper(isolated_lifecycle, "tab-term")
    wrapper.send_signal(signal.SIGTERM)
    wrapper.wait(timeout=5)
    assert _wait_until(lambda: not _alive(parent_pid) and not _alive(child_pid))
    assert not _alive(parent_pid)
    assert not _alive(child_pid)


def test_parent_death_reaps_the_process_pair(isolated_lifecycle: Path) -> None:
    marker = isolated_lifecycle / "dying.pair"
    env = _serve_env(isolated_lifecycle, marker, "dying-parent")
    grandparent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import os, subprocess, sys, time\n"
                "from pathlib import Path\n"
                "marker = Path(sys.argv[1])\n"
                "cmd = sys.argv[2:]\n"
                "subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)\n"
                "deadline = time.time() + 5\n"
                "while time.time() < deadline and not marker.exists():\n"
                "    time.sleep(0.05)\n"
                "time.sleep(0.2)\n"
                "os._exit(0)\n"
            ),
            str(marker),
            sys.executable,
            str(MODULE),
            "serve",
            "--vault",
            str(isolated_lifecycle),
            "--session-id",
            "dying-parent",
        ],
        env=env,
    )
    parent_pid, child_pid = _read_pair(marker)
    grandparent.wait(timeout=5)
    assert _wait_until(lambda: not _alive(parent_pid) and not _alive(child_pid), timeout=8)
    assert not _alive(parent_pid)
    assert not _alive(child_pid)


def test_session_end_reaps_only_that_session_pair(isolated_lifecycle: Path) -> None:
    first, _first_marker, first_parent, first_child = _start_wrapper(isolated_lifecycle, "session-a")
    second, _second_marker, second_parent, second_child = _start_wrapper(isolated_lifecycle, "session-b")
    try:
        result = lifecycle.handle_hook(
            {"hook_event_name": "SessionEnd", "session_id": "session-a"},
            mode="hook",
        )
        assert first_parent in result.reaped_pids or not _alive(first_parent)
        assert _wait_until(lambda: not _alive(first_parent) and not _alive(first_child))
        assert not _alive(first_parent)
        assert not _alive(first_child)
        assert _alive(second_parent)
        assert _alive(second_child)
    finally:
        _stop_wrapper(first)
        _stop_wrapper(second)
        lifecycle.reap_session("session-b")


def test_orphan_sweep_reaps_reparented_pair_and_leaves_live_session(
    isolated_lifecycle: Path,
) -> None:
    live, _live_marker, live_parent, live_child = _start_wrapper(isolated_lifecycle, "live-tab")
    leaked = subprocess.Popen(
        [sys.executable, str(PAIR_FIXTURE), str(isolated_lifecycle / "leaked.pair"), "google-workspace-mcp", "serve"],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    leaked_parent, leaked_child = _read_pair(isolated_lifecycle / "leaked.pair")
    os.kill(leaked.pid, signal.SIGKILL)
    leaked.wait(timeout=3)
    assert _wait_until(lambda: not _alive(leaked_parent) and _alive(leaked_child))
    try:
        lifecycle.mark_session_alive("live-tab")
        result = lifecycle.reap_orphans(living_session_ids={"live-tab"})
        assert _wait_until(lambda: not _alive(leaked_child))
        assert not _alive(leaked_child)
        assert _alive(live_parent)
        assert _alive(live_child)
        assert leaked_child in result.reaped_pids
    finally:
        _stop_wrapper(live)
        lifecycle.reap_session("live-tab")
        for pid in (leaked_parent, leaked_child, leaked.pid):
            if _alive(pid):
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except OSError:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass


def test_pid_reuse_does_not_kill_unrelated_process(isolated_lifecycle: Path) -> None:
    victim = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        lifecycle.write_lease(
            "stale",
            wrapper_pid=victim.pid,
            child_pid=victim.pid,
            pgid=os.getpgid(victim.pid),
        )
        result = lifecycle.reap_session("stale")
        assert _alive(victim.pid)
        assert victim.pid in result.skipped_pids or victim.pid not in result.reaped_pids
    finally:
        victim.terminate()
        victim.wait(timeout=3)


def test_oneshot_cli_is_not_managed() -> None:
    assert not lifecycle.is_managed_cmdline("npx -y google-workspace-mcp accounts add main")
    assert not lifecycle.is_managed_cmdline("npx -y google-workspace-mcp status")
    assert not lifecycle.is_managed_cmdline("npx -y google-workspace-mcp setup")
    assert lifecycle.is_managed_cmdline("npx -y google-workspace-mcp serve")
    assert lifecycle.is_managed_cmdline(f"{sys.executable} {MODULE} serve")


def test_hook_empty_payload_is_silent_success(isolated_lifecycle: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(MODULE), "--hook", "--vault", str(isolated_lifecycle)],
        input=b"",
        capture_output=True,
        env={**os.environ, "DEX_MCP_LIFECYCLE_DIR": str(isolated_lifecycle / "lifecycle")},
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout == b""


def test_settings_wire_lifecycle_on_session_start_and_end() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    start_commands = [hook["command"] for hook in settings["hooks"]["SessionStart"][0]["hooks"]]
    end_commands = [hook["command"] for hook in settings["hooks"]["SessionEnd"][0]["hooks"]]
    assert any("mcp_session_lifecycle.py" in command and "--sweep" in command for command in start_commands)
    assert any("mcp_session_lifecycle.py" in command and "--hook" in command for command in end_commands)
    assert end_commands[0].index("mcp_session_lifecycle.py") >= 0
