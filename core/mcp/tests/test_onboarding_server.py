"""
Tests for the onboarding MCP server's .mcp.json setup.

Covers setup_mcp_config: {{VAULT_PATH}} substitution, JSON validation, and the
placeholder/comment-key server filtering adopted from community PR #38.

Run with: pytest core/mcp/tests/test_onboarding_server.py -v
"""

import asyncio
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# core/mcp/tests -> repo root (for `core.paths`) and core/mcp (for the module).
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "core" / "mcp"))

import onboarding_server  # noqa: E402

from core.utils import doctor, preflight  # noqa: E402


def _decode_tool_result(result) -> dict:
    return json.loads(result[0].text)


def _write_example(tmp_path: Path, servers: dict) -> Path:
    example = tmp_path / ".mcp.json.example"
    example.write_text(json.dumps({"mcpServers": servers}, indent=2))
    return example


def _redirect_config(monkeypatch, example: Path, target: Path) -> None:
    monkeypatch.setattr(onboarding_server, "MCP_CONFIG_EXAMPLE", example)
    monkeypatch.setattr(onboarding_server, "MCP_CONFIG_TARGET", target)


class TestSetupMcpConfig:
    """setup_mcp_config substitution, validation, and filtering."""

    def test_production_target_is_root_mcp_config(self):
        assert onboarding_server.MCP_CONFIG_TARGET == onboarding_server.BASE_DIR / ".mcp.json"

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

        ok, err = onboarding_server.setup_mcp_config(Path("/tmp/test-vault"))

        assert ok is True
        assert err is None

        servers = json.loads(target.read_text())["mcpServers"]
        # Clean server survives with the real path substituted in.
        assert "clean" in servers
        assert servers["clean"]["env"]["VAULT_PATH"] == "/tmp/test-vault"
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

        ok, err = onboarding_server.setup_mcp_config(Path("/tmp/test-vault"))

        assert ok is False
        assert ".mcp.json.example not found" in err

    def test_invalid_json_after_substitution_returns_error(
        self, tmp_path, monkeypatch
    ):
        example = tmp_path / ".mcp.json.example"
        example.write_text('{ "mcpServers": { not valid json }')
        target = tmp_path / ".mcp.json"
        _redirect_config(monkeypatch, example, target)

        ok, err = onboarding_server.setup_mcp_config(Path("/tmp/test-vault"))

        assert ok is False
        assert "Invalid JSON after substitution" in err
        assert not target.exists()

    def test_preserves_existing_servers_and_adds_only_missing_defaults(
        self, tmp_path, monkeypatch
    ):
        example = _write_example(
            tmp_path,
            {
                "work-mcp": {
                    "command": "{{VAULT_PATH}}/.venv/bin/python",
                    "args": ["{{VAULT_PATH}}/core/mcp/work_server.py"],
                },
                "calendar-mcp": {
                    "command": "{{VAULT_PATH}}/.venv/bin/python",
                    "args": ["{{VAULT_PATH}}/core/mcp/calendar_server.py"],
                },
            },
        )
        target = tmp_path / ".mcp.json"
        existing_work = {
            "command": "custom-python",
            "args": ["custom-work-server.py"],
            "env": {"CUSTOM": "preserve-me"},
        }
        custom_server = {
            "command": "npx",
            "args": ["-y", "custom-mcp"],
        }
        target.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "work-mcp": existing_work,
                        "custom-mcp": custom_server,
                    },
                    "customTopLevel": {"preserve": True},
                },
                indent=2,
            )
        )
        _redirect_config(monkeypatch, example, target)

        ok, err = onboarding_server.setup_mcp_config(tmp_path)

        assert ok is True
        assert err is None
        config = json.loads(target.read_text())
        assert config["mcpServers"]["work-mcp"] == existing_work
        assert config["mcpServers"]["custom-mcp"] == custom_server
        assert config["customTopLevel"] == {"preserve": True}
        assert config["mcpServers"]["calendar-mcp"]["command"] == str(tmp_path / ".venv/bin/python")

    def test_invalid_existing_config_returns_error_without_overwriting(
        self, tmp_path, monkeypatch
    ):
        example = _write_example(
            tmp_path,
            {"work-mcp": {"command": "python", "args": ["work_server.py"]}},
        )
        target = tmp_path / ".mcp.json"
        invalid_content = '{ "mcpServers": { not valid json }'
        target.write_text(invalid_content)
        _redirect_config(monkeypatch, example, target)

        ok, err = onboarding_server.setup_mcp_config(tmp_path)

        assert ok is False
        assert "Existing .mcp.json is invalid JSON" in err
        assert target.read_text() == invalid_content

    def test_onboarding_output_is_the_config_preflight_and_doctor_read(
        self, tmp_path, monkeypatch
    ):
        example = _write_example(
            tmp_path,
            {"work-mcp": {"command": "python", "args": ["{{VAULT_PATH}}/core/mcp/work_server.py"]}},
        )
        target = tmp_path / ".mcp.json"
        _redirect_config(monkeypatch, example, target)
        monkeypatch.setenv("VAULT_PATH", str(tmp_path))

        ok, err = onboarding_server.setup_mcp_config(tmp_path)

        assert ok is True
        assert err is None
        assert preflight.get_mcp_config_path() == target
        context = doctor.DoctorContext(
            vault_root=tmp_path,
            repo_root=tmp_path,
            home=tmp_path,
            now=datetime.now(timezone.utc),
        )
        assert doctor._mcp_config_path(context) == target
        assert doctor._load_mcp_config(context) == json.loads(target.read_text())


class TestCapabilityStep:
    def test_tool_schema_includes_the_seventh_capability_step(self):
        tools = asyncio.run(onboarding_server.handle_list_tools())
        validate = next(tool for tool in tools if tool.name == "validate_and_save_step")

        assert validate.inputSchema["properties"]["step_number"]["maximum"] == 7

    def test_saves_explicit_room_answers(self, tmp_path, monkeypatch):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 7,
                        "step_data": {
                            "capabilities": {
                                "career": True,
                                "companies": False,
                                "quarter_goals": True,
                            }
                        },
                    },
                )
            )
        )

        assert payload["success"] is True
        session = onboarding_server.load_session()
        assert session["data"]["capabilities"] == {
            "career": True,
            "companies": False,
            "quarter_goals": True,
        }
        assert 7 in session["completed_steps"]
        assert session["current_step"] == 8

    def test_rejects_non_boolean_room_answers(self, tmp_path, monkeypatch):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 7,
                        "step_data": {
                            "capabilities": {
                                "career": "yes",
                                "companies": False,
                                "quarter_goals": False,
                            }
                        },
                    },
                )
            )
        )

        assert payload["success"] is False
        assert payload["field"] == "capabilities.career"

    def test_rejects_unknown_room_answers(self, tmp_path, monkeypatch):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 7,
                        "step_data": {"capabilities": {"careeer": True}},
                    },
                )
            )
        )

        assert payload["success"] is False
        assert payload["field"] == "capabilities.careeer"

    def test_profile_write_persists_rooms_and_syncs_legacy_quarter_switch(
        self, tmp_path, monkeypatch
    ):
        template = tmp_path / "System/user-profile-template.yaml"
        target = tmp_path / "System/user-profile.yaml"
        template.parent.mkdir(parents=True)
        template.write_text(
            "quarterly_planning:\n  enabled: false\n  q1_start_month: 1\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(onboarding_server, "USER_PROFILE_TEMPLATE", template)
        monkeypatch.setattr(onboarding_server, "USER_PROFILE_FILE", target)
        session = {
            "data": {
                "name": "Test User",
                "capabilities": {
                    "career": False,
                    "companies": True,
                    "quarter_goals": True,
                },
            }
        }

        assert onboarding_server.create_user_profile(session) is True

        import yaml

        profile = yaml.safe_load(target.read_text(encoding="utf-8"))
        assert profile["capabilities"] == {
            "career": {"enabled": False},
            "companies": {"enabled": True},
            "quarter_goals": {"enabled": True},
        }
        assert profile["quarterly_planning"] == {
            "enabled": True,
            "q1_start_month": 1,
        }

    def test_dry_run_includes_only_selected_room_folders(self, tmp_path, monkeypatch):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
        session = onboarding_server.create_new_session()
        session["completed_steps"] = [1, 2, 3, 4, 5, 6, 7]
        session["current_step"] = 8
        session["data"] = {
            "name": "Test User",
            "role": "Founder",
            "company_size": "startup",
            "email_domain": "example.test",
            "pillars": ["Build", "Learn"],
            "communication": {},
            "capabilities": {
                "career": True,
                "companies": False,
                "quarter_goals": False,
            },
        }
        onboarding_server.save_session(session)

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "finalize_onboarding", {"dry_run": True}
                )
            )
        )

        preview = payload["data"]
        assert "05-Areas/Career" in preview["would_create_folders"]
        assert "05-Areas/Companies" not in preview["would_create_folders"]
        assert "01-Quarter_Goals" not in preview["would_create_folders"]
        assert preview["preview_user_profile"]["capabilities"] == {
            "career": {"enabled": True},
            "companies": {"enabled": False},
            "quarter_goals": {"enabled": False},
        }

    def test_finalize_provisions_only_selected_room_assets(self, tmp_path, monkeypatch):
        system = tmp_path / "System"
        system.mkdir()
        template = system / "user-profile-template.yaml"
        shutil.copy(REPO_ROOT / "System/user-profile-template.yaml", template)
        shutil.copytree(
            REPO_ROOT / ".claude/skills/_available/capabilities",
            tmp_path / ".claude/skills/_available/capabilities",
        )
        mcp_example = system / ".mcp.json.example"
        mcp_example.write_text('{"mcpServers": {}}\n', encoding="utf-8")
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("## User Profile\n\n---\n", encoding="utf-8")

        paths = {
            "BASE_DIR": tmp_path,
            "SESSION_FILE": system / ".onboarding-session.json",
            "USER_PROFILE_TEMPLATE": template,
            "USER_PROFILE_FILE": system / "user-profile.yaml",
            "PILLARS_FILE": system / "pillars.yaml",
            "CLAUDE_MD": claude_md,
            "MCP_CONFIG_EXAMPLE": mcp_example,
            "MCP_CONFIG_TARGET": tmp_path / ".mcp.json",
            "MARKER_FILE": system / ".onboarding-complete",
        }
        for name, value in paths.items():
            monkeypatch.setattr(onboarding_server, name, value)

        session = onboarding_server.create_new_session()
        session["completed_steps"] = [1, 2, 3, 4, 5, 6, 7]
        session["current_step"] = 8
        session["data"] = {
            "name": "Test User",
            "role": "Founder",
            "role_group": "leadership",
            "company_size": "startup",
            "email_domain": "example.test",
            "pillars": ["Build", "Learn"],
            "communication": {},
            "capabilities": {
                "career": True,
                "companies": False,
                "quarter_goals": False,
            },
        }
        onboarding_server.save_session(session)

        payload = _decode_tool_result(
            asyncio.run(onboarding_server.handle_call_tool("finalize_onboarding", {}))
        )

        assert payload["success"] is True, payload
        assert (tmp_path / "05-Areas/Career/Evidence/README.md").is_file()
        assert (tmp_path / ".claude/skills/career-setup/SKILL.md").is_file()
        assert not (tmp_path / "05-Areas/Companies").exists()
        assert not (tmp_path / "01-Quarter_Goals").exists()
        assert (tmp_path / "03-Tasks/Tasks.md").is_file()
        assert (tmp_path / "05-Areas/People/Internal").is_dir()
        assert not paths["SESSION_FILE"].exists()
