from pathlib import Path

import pytest


@pytest.mark.parametrize("skill", ["todoist-setup", "trello-setup"])
def test_task_setup_never_requests_chat_secrets_or_uses_unsafe_health_paths(skill):
    text = (Path(".claude/skills") / skill / "SKILL.md").read_text().lower()
    forbidden = (
        "paste it here",
        "paste your api key",
        "curl -",
        "bearer $",
        "via the trello mcp",
        "use the mcp server",
    )
    assert not any(phrase in text for phrase in forbidden)
    assert "do not paste" in text
    assert "check_service_health" in text
    assert "adapter-stdin" in text
