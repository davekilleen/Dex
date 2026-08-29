"""Keep the shipped Google Workspace setup journey aligned with its MCP package."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / ".claude" / "skills" / "google-workspace-setup" / "SKILL.md"


def test_google_workspace_setup_matches_the_connector_it_installs() -> None:
    instructions = SKILL.read_text(encoding="utf-8")

    assert "pm990320/google-workspace-mcp" in instructions
    assert "taylorwilsdon/google_workspace_mcp" not in instructions
    assert "15-20 minutes" in instructions

    for required_step in (
        "Create or select a Google Cloud project",
        "Enable the required Google APIs",
        "Configure the OAuth consent screen",
        "Add the Google account as a test user",
        "Create a **Desktop app** OAuth client",
        "`~/.google-mcp/credentials.json`",
    ):
        assert required_step in instructions

    assert '["-y", "google-workspace-mcp", "serve"]' in instructions
    assert "`npx -y google-workspace-mcp accounts add main`" in instructions
    assert "`~/.google-mcp/tokens/`" in instructions
    assert "fixed set of nine OAuth scopes" in instructions
    assert "does not narrow the permissions the connector requests" in instructions

    assert "About 3 minutes" not in instructions
    assert "Run `npx google-workspace-mcp` -- this starts the OAuth flow" not in instructions
    assert "`System/.gmail-oauth-token.json`" not in instructions
