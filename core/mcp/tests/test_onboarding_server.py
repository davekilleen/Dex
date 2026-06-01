"""
Tests for the onboarding MCP server's .mcp.json setup.

Covers setup_mcp_config: {{VAULT_PATH}} substitution, JSON validation, and the
placeholder/comment-key server filtering adopted from community PR #38.

Run with: pytest core/mcp/tests/test_onboarding_server.py -v
"""

import json
import sys
from pathlib import Path

# core/mcp/tests -> repo root (for `core.paths`) and core/mcp (for the module).
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "core" / "mcp"))

import onboarding_server  # noqa: E402


def _write_example(tmp_path: Path, servers: dict) -> Path:
    example = tmp_path / ".mcp.json.example"
    example.write_text(json.dumps({"mcpServers": servers}, indent=2))
    return example


def _redirect_config(monkeypatch, example: Path, target: Path) -> None:
    monkeypatch.setattr(onboarding_server, "MCP_CONFIG_EXAMPLE", example)
    monkeypatch.setattr(onboarding_server, "MCP_CONFIG_TARGET", target)


class TestSetupMcpConfig:
    """setup_mcp_config substitution, validation, and filtering."""

    def test_resolves_vault_path_and_strips_placeholder_and_comment_servers(
        self, tmp_path, monkeypatch
    ):
        example = _write_example(
            tmp_path,
            {
                "clean": {
                    "command": "{{VAULT_PATH}}/.venv/bin/python",
                    "args": ["{{VAULT_PATH}}/core/mcp/work_server.py"],
                    "env": {"VAULT_PATH": "{{VAULT_PATH}}"},
                },
                "needs_api_key": {
                    "command": "npx",
                    "args": ["-y", "some-mcp"],
                    "env": {"API_KEY": "{{API_KEY}}"},
                },
                "_comment_integrations": {
                    "note": "optional integrations a user can enable later"
                },
            },
        )
        target = tmp_path / ".mcp.json"
        _redirect_config(monkeypatch, example, target)

        ok, err = onboarding_server.setup_mcp_config(Path("/Users/me/Vault"))

        assert ok is True
        assert err is None

        servers = json.loads(target.read_text())["mcpServers"]
        # Clean server survives with the real path substituted in.
        assert "clean" in servers
        assert servers["clean"]["env"]["VAULT_PATH"] == "/Users/me/Vault"
        assert "{{VAULT_PATH}}" not in json.dumps(servers["clean"])
        # Server with an unresolved credential placeholder is dropped.
        assert "needs_api_key" not in servers
        # Comment-key block is dropped.
        assert "_comment_integrations" not in servers

    def test_missing_example_returns_error(self, tmp_path, monkeypatch):
        _redirect_config(
            monkeypatch,
            tmp_path / "does-not-exist.json",
            tmp_path / ".mcp.json",
        )

        ok, err = onboarding_server.setup_mcp_config(Path("/Users/me/Vault"))

        assert ok is False
        assert ".mcp.json.example not found" in err

    def test_invalid_json_after_substitution_returns_error(
        self, tmp_path, monkeypatch
    ):
        example = tmp_path / ".mcp.json.example"
        example.write_text('{ "mcpServers": { not valid json }')
        target = tmp_path / ".mcp.json"
        _redirect_config(monkeypatch, example, target)

        ok, err = onboarding_server.setup_mcp_config(Path("/Users/me/Vault"))

        assert ok is False
        assert "Invalid JSON after substitution" in err
        assert not target.exists()
