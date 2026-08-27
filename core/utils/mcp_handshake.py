"""Minimal stdio JSON-RPC handshake for Dex MCP smoke checks."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from typing import Any, Mapping, Sequence

INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "dex-mcp-handshake", "version": "1.0"},
    },
}


@dataclass(frozen=True)
class MCPHandshakeResult:
    """Outcome from one initialize request."""

    ok: bool
    response: dict[str, Any] | None
    error: str | None
    stderr: str
    returncode: int | None


def _response_error(response: object) -> str | None:
    if not isinstance(response, dict):
        return "initialize response is not a JSON object"
    if response.get("jsonrpc") != "2.0":
        return "initialize response has an invalid jsonrpc version"
    if response.get("id") != INITIALIZE_REQUEST["id"]:
        return "initialize response id does not match the request"
    if "error" in response:
        return f"initialize returned a JSON-RPC error: {response['error']}"
    if not isinstance(response.get("result"), dict):
        return "initialize response has no result object"
    return None


def _kill_process_handle(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.kill()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    """Stop the server and any children, escalating when it ignores SIGTERM."""
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass
    if process.poll() is not None:
        return

    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return
    except PermissionError:
        # macOS CI can deny killpg with EPERM while the child is still
        # ours to kill, or while the group is already being reaped.
        # Fall back to the process handle so a finished handshake stays
        # finished instead of "internal smoke journey refused:
        # Operation not permitted".
        _kill_process_handle(process)
        return

    try:
        process.wait(timeout=1)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        return
    except PermissionError:
        _kill_process_handle(process)
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def mcp_stdio_handshake(
    command: Sequence[str | os.PathLike[str]],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 10.0,
) -> MCPHandshakeResult:
    """Launch ``command``, send initialize, and return its first JSON-RPC response.

    The child runs in a separate process group and is always terminated. The
    timeout covers waiting for the newline-delimited initialize response.
    """
    if not command:
        raise ValueError("command must not be empty")
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")

    process: subprocess.Popen[str] | None = None
    response: dict[str, Any] | None = None
    error: str | None = None
    stderr = ""
    returncode: int | None = None

    with tempfile.TemporaryFile(mode="w+b") as stderr_file:
        try:
            process = subprocess.Popen(
                [os.fspath(part) for part in command],
                cwd=Path(cwd) if cwd is not None else None,
                env=dict(env) if env is not None else None,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_file,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
            if process.stdin is None or process.stdout is None:
                error = "could not open server stdio pipes"
            else:
                request = json.dumps(INITIALIZE_REQUEST, separators=(",", ":")) + "\n"
                process.stdin.write(request)
                process.stdin.flush()

                lines: Queue[str] = Queue(maxsize=1)
                reader = Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
                reader.start()
                try:
                    line = lines.get(timeout=timeout)
                except Empty:
                    if process.poll() is None:
                        error = f"initialize response timed out after {timeout:g}s"
                    else:
                        error = f"server exited before initialize response (exit {process.returncode})"
                else:
                    if not line:
                        error = f"server closed stdout before initialize response (exit {process.poll()})"
                    else:
                        try:
                            decoded = json.loads(line)
                        except json.JSONDecodeError as exc:
                            error = f"initialize response is not valid JSON: {exc}"
                        else:
                            if isinstance(decoded, dict):
                                response = decoded
                            error = _response_error(decoded)
        except (BrokenPipeError, OSError) as exc:
            error = f"could not complete initialize handshake: {exc}"
        finally:
            if process is not None:
                try:
                    _terminate_process_group(process)
                except OSError:
                    _kill_process_handle(process)
                returncode = process.returncode
            stderr_file.flush()
            stderr_file.seek(0)
            stderr = stderr_file.read().decode("utf-8", errors="replace")

    return MCPHandshakeResult(
        ok=error is None,
        response=response,
        error=error,
        stderr=stderr,
        returncode=returncode,
    )
