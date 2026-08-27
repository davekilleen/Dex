"""Start every shipped Dex MCP server and perform a real stdio initialize."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from core.utils import mcp_handshake
from core.utils.mcp_handshake import mcp_stdio_handshake

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_TEMPLATE = REPO_ROOT / "System" / ".mcp.json.example"
VAULT_PLACEHOLDER = "{{VAULT_PATH}}"
CONFIGURED_PYTHON = f"{VAULT_PLACEHOLDER}/.venv/bin/python"
# Dex ships servers in two places: the core set every install registers, and
# opt-in integration servers a setup skill registers when the user connects
# one. Both are Dex-owned and both must survive a real stdio initialize.
DEX_SCRIPT_PREFIXES = (
    f"{VAULT_PLACEHOLDER}/core/mcp/",
    f"{VAULT_PLACEHOLDER}/core/integrations/",
)


def _dex_owned_servers(
    config: object | None = None,
) -> list[tuple[str, str, tuple[str, ...], dict[str, str]]]:
    if config is None:
        config = json.loads(MCP_TEMPLATE.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("mcpServers"), dict):
        raise AssertionError("System/.mcp.json.example must contain an mcpServers object")

    servers = []
    for name, entry in config["mcpServers"].items():
        if not isinstance(entry, dict):
            continue
        command = entry.get("command")
        args = entry.get("args", [])
        rendered_args = json.dumps(args)
        is_candidate = command == CONFIGURED_PYTHON or any(
            prefix.removeprefix(f"{VAULT_PLACEHOLDER}/") in rendered_args
            for prefix in DEX_SCRIPT_PREFIXES
        )
        if not is_candidate:
            continue
        if command != CONFIGURED_PYTHON:
            raise AssertionError(
                f"{name}: Dex-owned server command must be {CONFIGURED_PYTHON!r}"
            )
        if not isinstance(args, list) or not all(isinstance(argument, str) for argument in args):
            raise AssertionError(f"{name}: Dex-owned server args must be a list of strings")

        script_args = [
            argument
            for argument in args
            if argument.startswith(DEX_SCRIPT_PREFIXES)
        ]
        if len(script_args) != 1:
            raise AssertionError(
                f"{name}: Dex-owned server must have exactly one "
                f"{' or '.join(DEX_SCRIPT_PREFIXES)} argument"
            )
        script = REPO_ROOT / script_args[0].removeprefix(f"{VAULT_PLACEHOLDER}/")
        if not script.is_file():
            raise AssertionError(f"{name}: configured server script does not exist: {script}")

        configured_env = entry.get("env", {})
        if not isinstance(configured_env, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in configured_env.items()
        ):
            raise AssertionError(f"{name}: Dex-owned server env must contain string values")
        servers.append((name, command, tuple(args), configured_env))
    return servers


DEX_OWNED_SERVERS = _dex_owned_servers()
assert DEX_OWNED_SERVERS, "System/.mcp.json.example contains no Dex-owned Python servers"


@pytest.mark.parametrize(
    ("server_name", "configured_command", "configured_args", "configured_env"),
    DEX_OWNED_SERVERS,
    ids=[name for name, _command, _args, _env in DEX_OWNED_SERVERS],
)
def test_dex_owned_server_completes_stdio_initialize(
    server_name: str,
    configured_command: str,
    configured_args: tuple[str, ...],
    configured_env: dict[str, str],
    fixture_vault: Path,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    shutil.copytree(fixture_vault, vault)
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHONUNBUFFERED": "1",
        "VAULT_PATH": str(vault),
    }
    env.update(
        {
            key: value.replace("{{VAULT_PATH}}", str(vault))
            for key, value in configured_env.items()
            if isinstance(key, str) and isinstance(value, str)
        }
    )

    resolved_command = configured_command.replace(VAULT_PLACEHOLDER, str(REPO_ROOT))
    assert resolved_command == str(REPO_ROOT / ".venv/bin/python")
    resolved_args = [
        argument.replace(VAULT_PLACEHOLDER, str(REPO_ROOT))
        for argument in configured_args
    ]

    result = mcp_stdio_handshake(
        [sys.executable, *resolved_args],
        cwd=REPO_ROOT,
        env=env,
        timeout=10,
    )

    assert result.ok, f"{server_name}: {result.error}\nstderr:\n{result.stderr}"
    assert result.response is not None
    assert result.response["jsonrpc"] == "2.0"
    assert result.response["id"] == 1
    assert isinstance(result.response["result"]["capabilities"], dict)
    assert isinstance(result.response["result"]["serverInfo"], dict)


def test_handshake_cleanup_survives_killpg_permission_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Observed on macOS CI (PR 601 tests (1)): killpg raised
    # PermissionError(1, "Operation not permitted") after a blessed local
    # Python MCP had already answered initialize. The exception escaped
    # handshake cleanup and the smoke journey reported
    # "internal smoke journey refused: [Errno 1] Operation not permitted".
    def deny_killpg(_process_group_id: int, _requested_signal: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(mcp_handshake.os, "killpg", deny_killpg)
    script = tmp_path / "server.py"
    script.write_text(
        "import json, sys, time\n"
        "request = json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': "
        "{'capabilities': {}, 'serverInfo': {'name': 'test', 'version': '1'}}}), "
        "flush=True)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )

    result = mcp_stdio_handshake(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=os.environ,
        timeout=5,
    )

    assert result.ok, f"{result.error}\nstderr:\n{result.stderr}"
    assert result.error is None
    assert result.response is not None
    assert result.response["result"]["serverInfo"]["name"] == "test"


@pytest.mark.parametrize(
    ("entry", "expected_error"),
    [
        (
            {"command": "python", "args": [f"{DEX_SCRIPT_PREFIXES[0]}work_server.py"]},
            "command must be",
        ),
        (
            {"command": CONFIGURED_PYTHON, "args": f"{DEX_SCRIPT_PREFIXES[0]}work_server.py"},
            "args must be a list of strings",
        ),
        (
            {"command": CONFIGURED_PYTHON, "args": []},
            "must have exactly one",
        ),
    ],
)
def test_dex_owned_server_discovery_rejects_malformed_candidates(
    entry: dict[str, object], expected_error: str
) -> None:
    with pytest.raises(AssertionError, match=expected_error):
        _dex_owned_servers({"mcpServers": {"broken": entry}})
