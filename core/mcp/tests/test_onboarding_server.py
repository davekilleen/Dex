"""Tests for the onboarding MCP server."""

import asyncio
import json
import shutil
import sys
from pathlib import Path

# core/mcp/tests -> repo root (for `core.paths`) and core/mcp (for the module).
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "core" / "mcp"))

import onboarding_server  # noqa: E402


def _decode_tool_result(result) -> dict:
    return json.loads(result[0].text)


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
        (tmp_path / "core").mkdir()
        shutil.copy(REPO_ROOT / "core/paths.py", tmp_path / "core/paths.py")
        (tmp_path / ".scripts").mkdir()
        mcp_example = system / ".mcp.json.example"
        mcp_example.write_text('{"mcpServers": {}}\n', encoding="utf-8")
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("## User Profile\n\n---\n", encoding="utf-8")

        paths = {
            "BASE_DIR": tmp_path,
            "SESSION_FILE": system / ".onboarding-session.json",
            "MCP_CONFIG_EXAMPLE": mcp_example,
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
            "email_domain": "example.com",
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
