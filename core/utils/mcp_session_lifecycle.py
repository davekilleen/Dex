"""Reap google-workspace-mcp process pairs when a Claude Code session ends.

Claude Code starts ``npx -y google-workspace-mcp serve`` once per session.
That command is a process pair (the npx wrapper plus the node server). Closing
a tab or session has historically left the pair running. After enough
sessions the machine is unusable until someone runs ``pkill``.

This module is the lifecycle owner:

- ``serve`` is the MCP command. It starts the connector in its own process
  group, records a session lease under a machine temp directory (never the
  vault), forwards stdio, and always tears the group down on stdin close,
  signal, or parent death.
- SessionEnd reaps this session's lease and any leftover orphan pairs.
- SessionStart sweeps orphans from sessions that never got a clean close.

Leases live under ``$TMPDIR/dex-mcp-lifecycle-<uid>/``. That is local
machine state, not a vault write.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

SERVER_NAME = "google-workspace-mcp"
SERVER_TOKEN = "google-workspace-mcp"
WRAPPER_TOKEN = "mcp_session_lifecycle.py"
ONESHOT_TOKENS = (" accounts ", " test-permissions", " setup", " status")
DEFAULT_CHILD = ("npx", "-y", "google-workspace-mcp", "serve")
LEASE_DIRNAME = "leases"
SESSIONS_DIRNAME = "sessions"
LATEST_SESSION_NAME = "latest-session"
ORPHAN_PARENTS = frozenset({0, 1})
TERM_WAIT_SECONDS = 1.0
KILL_WAIT_SECONDS = 1.0
PARENT_POLL_SECONDS = 0.25


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    ppid: int
    pgid: int
    cmdline: str


@dataclass(frozen=True)
class ReapResult:
    reaped_pids: tuple[int, ...]
    skipped_pids: tuple[int, ...]


def runtime_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Return the per-user lease directory (temp, never the vault)."""

    if explicit is not None:
        path = Path(explicit)
    elif os.environ.get("DEX_MCP_LIFECYCLE_DIR"):
        path = Path(os.environ["DEX_MCP_LIFECYCLE_DIR"])
    else:
        path = Path(tempfile.gettempdir()) / f"dex-mcp-lifecycle-{_user_token()}"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def resolve_vault(explicit: str | os.PathLike[str] | None = None) -> Path:
    raw = explicit or os.environ.get("VAULT_PATH") or os.environ.get("CLAUDE_PROJECT_DIR")
    if not raw:
        return Path.cwd()
    return Path(raw)


def resolve_session_id(payload: Mapping[str, object] | None = None) -> str:
    if payload:
        for key in ("session_id", "sessionId"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("DEX_MCP_SESSION_ID", "CLAUDE_SESSION_ID"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    latest = runtime_dir() / LATEST_SESSION_NAME
    try:
        stored = latest.read_text(encoding="utf-8").strip()
    except OSError:
        stored = ""
    if stored:
        return stored
    return f"wrapper-{os.getpid()}"


def is_managed_cmdline(cmdline: str) -> bool:
    """True for the long-running connector, never one-shot CLI commands."""

    if not cmdline:
        return False
    compact = f" {cmdline} "
    if SERVER_TOKEN not in cmdline and WRAPPER_TOKEN not in cmdline:
        return False
    lowered = compact.replace("\x00", " ")
    if any(token in lowered for token in ONESHOT_TOKENS):
        return False
    if WRAPPER_TOKEN in cmdline:
        return "serve" in cmdline.split() or "serve" in cmdline
    return SERVER_TOKEN in cmdline


def list_processes() -> list[ProcessRecord]:
    proc = Path("/proc")
    if proc.is_dir():
        records = _list_procfs(proc)
        if records is not None:
            return records
    return _list_ps()


def list_managed_processes() -> list[ProcessRecord]:
    return [record for record in list_processes() if is_managed_cmdline(record.cmdline)]


def write_lease(
    session_id: str,
    *,
    wrapper_pid: int,
    child_pid: int,
    pgid: int,
) -> Path:
    directory = runtime_dir() / LEASE_DIRNAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"{_safe_token(session_id)}--{pgid}.json"
    payload = {
        "server": SERVER_NAME,
        "session_id": session_id,
        "wrapper_pid": wrapper_pid,
        "child_pid": child_pid,
        "pgid": pgid,
        "created_at": time.time(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_leases() -> list[dict[str, object]]:
    directory = runtime_dir() / LEASE_DIRNAME
    if not directory.is_dir():
        return []
    leases: list[dict[str, object]] = []
    for path in directory.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        payload["_path"] = str(path)
        leases.append(payload)
    return leases


def mark_session_alive(session_id: str) -> None:
    sessions = runtime_dir() / SESSIONS_DIRNAME
    sessions.mkdir(mode=0o700, parents=True, exist_ok=True)
    (sessions / _safe_token(session_id)).write_text(str(time.time()), encoding="utf-8")
    (runtime_dir() / LATEST_SESSION_NAME).write_text(session_id, encoding="utf-8")


def mark_session_closed(session_id: str) -> None:
    path = runtime_dir() / SESSIONS_DIRNAME / _safe_token(session_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def reap_session(session_id: str) -> ReapResult:
    """Kill the process group recorded for ``session_id``."""

    reaped: list[int] = []
    skipped: list[int] = []
    for lease in load_leases():
        if lease.get("session_id") != session_id:
            continue
        result = _reap_lease(lease)
        reaped.extend(result.reaped_pids)
        skipped.extend(result.skipped_pids)
    return ReapResult(tuple(dict.fromkeys(reaped)), tuple(dict.fromkeys(skipped)))


def reap_orphans(*, living_session_ids: Iterable[str] | None = None) -> ReapResult:
    """Reap leftover connector pairs whose session is gone or parent is init."""

    living = set(living_session_ids or _living_session_ids())
    reaped: list[int] = []
    skipped: list[int] = []

    for lease in load_leases():
        session_id = lease.get("session_id")
        wrapper_pid = _as_int(lease.get("wrapper_pid"))
        session_gone = not isinstance(session_id, str) or session_id not in living
        wrapper_dead = wrapper_pid is None or not _pid_is_alive(wrapper_pid)
        if session_gone or wrapper_dead:
            result = _reap_lease(lease)
            reaped.extend(result.reaped_pids)
            skipped.extend(result.skipped_pids)

    leased_pgids = {
        _as_int(lease.get("pgid"))
        for lease in load_leases()
        if _as_int(lease.get("pgid")) is not None
    }
    for record in list_managed_processes():
        if record.pid == os.getpid() or record.pid == os.getppid():
            skipped.append(record.pid)
            continue
        if record.pgid in leased_pgids:
            continue
        if record.ppid not in ORPHAN_PARENTS:
            continue
        if _reap_record(record):
            reaped.append(record.pid)
        else:
            skipped.append(record.pid)

    return ReapResult(tuple(dict.fromkeys(reaped)), tuple(dict.fromkeys(skipped)))


def handle_hook(payload: object, *, mode: str = "auto") -> ReapResult:
    """SessionEnd reaps this session; SessionStart records it and sweeps orphans."""

    data = payload if isinstance(payload, dict) else {}
    event = ""
    if isinstance(data, dict):
        raw_event = data.get("hook_event_name") or data.get("hookEventName") or ""
        event = raw_event if isinstance(raw_event, str) else ""
    session_id = resolve_session_id(data if isinstance(data, dict) else None)

    reaped: list[int] = []
    skipped: list[int] = []
    if mode == "sweep" or event == "SessionStart" or (mode == "auto" and event == "SessionStart"):
        mark_session_alive(session_id)
        result = reap_orphans(living_session_ids=_living_session_ids() | {session_id})
        reaped.extend(result.reaped_pids)
        skipped.extend(result.skipped_pids)
    if mode == "hook" or event == "SessionEnd" or (mode == "auto" and event in {"", "SessionEnd"}):
        if mode == "hook" or event == "SessionEnd" or mode == "auto":
            result = reap_session(session_id)
            reaped.extend(result.reaped_pids)
            skipped.extend(result.skipped_pids)
            mark_session_closed(session_id)
            orphans = reap_orphans()
            reaped.extend(orphans.reaped_pids)
            skipped.extend(orphans.skipped_pids)
    return ReapResult(tuple(dict.fromkeys(reaped)), tuple(dict.fromkeys(skipped)))


def serve(
    *,
    session_id: str | None = None,
    child_command: Sequence[str] | None = None,
) -> int:
    """Run google-workspace-mcp in a process group and reap it on host close."""

    resolved_session = session_id or resolve_session_id()
    command = _child_command(child_command)
    stop = threading.Event()
    child: subprocess.Popen[bytes] | None = None
    lease_path: Path | None = None

    def shutdown(_signum: int | None = None, _frame: object | None = None) -> None:
        stop.set()

    previous = {
        signal.SIGTERM: signal.signal(signal.SIGTERM, shutdown),
        signal.SIGINT: signal.signal(signal.SIGINT, shutdown),
    }
    if hasattr(signal, "SIGHUP"):
        previous[signal.SIGHUP] = signal.signal(signal.SIGHUP, shutdown)
    _install_parent_death_signal(shutdown)

    try:
        child = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            start_new_session=True,
        )
        if child.stdin is None or child.stdout is None:
            return 1
        lease_path = write_lease(
            resolved_session,
            wrapper_pid=os.getpid(),
            child_pid=child.pid,
            pgid=_process_group_id(child.pid),
        )
        stdin_thread = threading.Thread(
            target=_forward_bytes,
            args=(sys.stdin.buffer, child.stdin, stop),
            daemon=True,
        )
        stdout_thread = threading.Thread(
            target=_forward_bytes,
            args=(child.stdout, sys.stdout.buffer, None),
            daemon=True,
        )
        stdin_thread.start()
        stdout_thread.start()
        parent_thread = threading.Thread(
            target=_watch_parent,
            args=(os.getppid(), stop),
            daemon=True,
        )
        parent_thread.start()

        while not stop.is_set():
            if child.poll() is not None:
                break
            if not stdin_thread.is_alive():
                break
            time.sleep(0.05)
        return 0
    except OSError:
        return 1
    finally:
        if child is not None:
            _terminate_group(child)
        if lease_path is not None:
            try:
                lease_path.unlink()
            except FileNotFoundError:
                pass
        for signum, handler in previous.items():
            try:
                signal.signal(signum, handler)
            except (ValueError, OSError):
                pass


def default_serve_command() -> tuple[str, ...]:
    return DEFAULT_CHILD


def _child_command(override: Sequence[str] | None) -> list[str]:
    if override:
        return [os.fspath(part) for part in override]
    raw = os.environ.get("DEX_MCP_LIFECYCLE_CHILD")
    if raw:
        return [part for part in raw.split("\n") if part]
    return list(DEFAULT_CHILD)


def _user_token() -> str:
    getuid = getattr(os, "getuid", None)
    if callable(getuid):
        return str(getuid())
    return "user"


def _safe_token(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    return cleaned or "session"


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _living_session_ids() -> set[str]:
    directory = runtime_dir() / SESSIONS_DIRNAME
    if not directory.is_dir():
        return set()
    living: set[str] = set()
    for path in directory.iterdir():
        if path.is_file():
            living.add(path.name)
    return living


def _list_procfs(proc: Path) -> list[ProcessRecord] | None:
    records: list[ProcessRecord] = []
    try:
        pid_dirs = list(proc.iterdir())
    except OSError:
        return None
    for pid_dir in pid_dirs:
        if not pid_dir.name.isdigit():
            continue
        record = _read_procfs_record(pid_dir)
        if record is not None:
            records.append(record)
    return records


def _read_procfs_record(pid_dir: Path) -> ProcessRecord | None:
    try:
        pid = int(pid_dir.name)
        stat_text = (pid_dir / "stat").read_text(encoding="utf-8", errors="replace")
        cmdline_raw = (pid_dir / "cmdline").read_bytes()
    except (OSError, ValueError):
        return None
    close = stat_text.rfind(")")
    if close == -1:
        return None
    fields = stat_text[close + 2 :].split()
    if len(fields) < 5:
        return None
    try:
        ppid = int(fields[1])
        pgid = int(fields[2])
    except ValueError:
        return None
    cmdline = cmdline_raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
    if not cmdline:
        return None
    return ProcessRecord(pid=pid, ppid=ppid, pgid=pgid, cmdline=cmdline)


def _list_ps() -> list[ProcessRecord]:
    try:
        result = subprocess.run(
            ["ps", "-axww", "-o", "pid=,ppid=,pgid=,command="],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    records: list[ProcessRecord] = []
    stdout = result.stdout.decode("utf-8", "replace") if isinstance(result.stdout, bytes) else result.stdout
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            records.append(
                ProcessRecord(
                    pid=int(parts[0]),
                    ppid=int(parts[1]),
                    pgid=int(parts[2]),
                    cmdline=parts[3],
                )
            )
        except ValueError:
            continue
    return records


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _process_group_id(pid: int) -> int:
    getpgid = getattr(os, "getpgid", None)
    if callable(getpgid):
        try:
            return int(getpgid(pid))
        except OSError:
            pass
    record = next((item for item in list_processes() if item.pid == pid), None)
    return record.pgid if record is not None else pid


def _refresh_record(pid: int) -> ProcessRecord | None:
    return next((item for item in list_processes() if item.pid == pid), None)


def _reap_lease(lease: Mapping[str, object]) -> ReapResult:
    reaped: list[int] = []
    skipped: list[int] = []
    pgid = _as_int(lease.get("pgid"))
    wrapper_pid = _as_int(lease.get("wrapper_pid"))
    child_pid = _as_int(lease.get("child_pid"))
    targets = [pid for pid in (wrapper_pid, child_pid) if pid is not None]
    if pgid is not None:
        for record in list_managed_processes():
            if record.pgid == pgid:
                targets.append(record.pid)
    for pid in dict.fromkeys(targets):
        record = _refresh_record(pid)
        if record is None:
            continue
        if not is_managed_cmdline(record.cmdline):
            skipped.append(pid)
            continue
        if _reap_record(record, pgid=pgid):
            reaped.append(pid)
        else:
            skipped.append(pid)
    path = lease.get("_path")
    if isinstance(path, str):
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
    return ReapResult(tuple(reaped), tuple(skipped))


def _reap_record(record: ProcessRecord, *, pgid: int | None = None) -> bool:
    current = _refresh_record(record.pid)
    if current is None:
        return False
    if current.pid in {os.getpid(), os.getppid()}:
        return False
    if not is_managed_cmdline(current.cmdline):
        return False
    group = pgid if pgid is not None else current.pgid
    _signal_group(group, signal.SIGTERM)
    deadline = time.time() + TERM_WAIT_SECONDS
    while time.time() < deadline:
        if _refresh_record(current.pid) is None:
            return True
        time.sleep(0.05)
    _signal_group(group, signal.SIGKILL)
    deadline = time.time() + KILL_WAIT_SECONDS
    while time.time() < deadline:
        if _refresh_record(current.pid) is None:
            return True
        time.sleep(0.05)
    return _refresh_record(current.pid) is None


def _signal_group(pgid: int, signum: int) -> None:
    if os.name != "posix":
        try:
            os.kill(pgid, signum)
        except OSError:
            return
        return
    try:
        os.killpg(pgid, signum)
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            os.kill(pgid, signum)
        except OSError:
            return
    except OSError:
        return


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass
    if process.poll() is not None:
        _wait_briefly(process)
        _signal_group(_process_group_id(process.pid), signal.SIGKILL)
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            process.kill()
        except OSError:
            return
    try:
        process.wait(timeout=TERM_WAIT_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except OSError:
            pass
    _wait_briefly(process)


def _wait_briefly(process: subprocess.Popen[bytes]) -> None:
    try:
        process.wait(timeout=KILL_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def _forward_bytes(source: object, dest: object, stop: threading.Event | None) -> None:
    read = getattr(source, "read", None)
    write = getattr(dest, "write", None)
    flush = getattr(dest, "flush", None)
    if not callable(read) or not callable(write):
        return
    try:
        while stop is None or not stop.is_set():
            chunk = read(4096)
            if not chunk:
                break
            write(chunk)
            if callable(flush):
                flush()
    except (BrokenPipeError, ValueError, OSError):
        return
    finally:
        if stop is not None:
            stop.set()
        close = getattr(dest, "close", None)
        if callable(close):
            try:
                close()
            except OSError:
                pass


def _watch_parent(original_ppid: int, stop: threading.Event) -> None:
    while not stop.is_set():
        if os.getppid() != original_ppid:
            stop.set()
            return
        time.sleep(PARENT_POLL_SECONDS)


def _install_parent_death_signal(shutdown) -> None:
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        if libc.prctl(1, signal.SIGTERM) != 0:
            return
        if os.getppid() == 1:
            shutdown()
    except (AttributeError, OSError):
        return


def _read_hook_payload(raw: str) -> object:
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Google Workspace MCP session lifecycle")
    parser.add_argument("command", nargs="?", default="", help="serve | (empty with --hook/--sweep)")
    parser.add_argument("--vault", default=None)
    parser.add_argument("--hook", action="store_true")
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--session-id", default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.vault:
        os.environ["VAULT_PATH"] = str(Path(args.vault))
    if args.session_id:
        os.environ["DEX_MCP_SESSION_ID"] = args.session_id

    try:
        if args.hook or args.sweep or args.command in {"hook", "sweep"}:
            mode = "sweep" if args.sweep or args.command == "sweep" else "hook"
            payload = _read_hook_payload(sys.stdin.read())
            if args.command == "sweep":
                mode = "sweep"
            if isinstance(payload, dict) and not payload.get("hook_event_name") and not payload.get("hookEventName"):
                payload = {
                    **payload,
                    "hook_event_name": "SessionStart" if mode == "sweep" else "SessionEnd",
                }
            handle_hook(payload, mode=mode)
            return 0
        if args.command == "serve":
            return serve(session_id=args.session_id)
    except Exception:
        if args.hook or args.sweep or args.command in {"hook", "sweep"}:
            return 0
        raise
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
