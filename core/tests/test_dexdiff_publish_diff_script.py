"""Tests for the standalone skill script .claude/skills/diff-generate/scripts/publish_diff.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".claude" / "skills" / "diff-generate" / "scripts" / "publish_diff.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("publish_diff", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_metadata_extraction_reads_scalars_and_simple_lists(tmp_path):
    publish_diff = _load_script()
    workflow = tmp_path / "ignored-name.yaml"
    workflow.write_text(
        "\n".join(
            [
                'id: "meeting-prep"',
                "name: Meeting Prep",
                "description: Prepare sharper customer meetings.",
                "tags:",
                "  - meetings",
                "  - customers",
                "roles: [founder, product leader]",
                "integrations:",
                "  - Google Calendar",
                "  - Granola",
                "methodology:",
                "  problem: |",
                "    Meetings were scattered.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    metadata = publish_diff.extract_metadata(workflow, workflow.read_text(encoding="utf-8"))

    assert metadata == {
        "diffId": "meeting-prep",
        "name": "Meeting Prep",
        "description": "Prepare sharper customer meetings.",
        "tags": ["meetings", "customers"],
        "roles": ["founder", "product leader"],
        "integrations": ["Google Calendar", "Granola"],
    }


def test_metadata_extraction_uses_fallbacks(tmp_path):
    publish_diff = _load_script()
    workflow = tmp_path / "weekly-review.yaml"
    workflow.write_text(
        "\n".join(
            [
                "",
                "# Weekly review keeps Friday calm.",
                "dexdiff_schema: \"2.0\"",
                "methodology:",
                "  solution: Ship the right work.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    metadata = publish_diff.extract_metadata(workflow, workflow.read_text(encoding="utf-8"))

    assert metadata["diffId"] == "weekly-review"
    assert metadata["name"] == "Weekly Review"
    assert metadata["description"] == "Weekly review keeps Friday calm."
    assert metadata["tags"] == []
    assert metadata["roles"] == []
    assert metadata["integrations"] == []


def test_load_auth_rejects_missing_and_stale_credentials(tmp_path, monkeypatch):
    publish_diff = _load_script()
    monkeypatch.setenv("HOME", str(tmp_path))
    now_ms = 1_800_000_000_000

    with pytest.raises(publish_diff.AuthError) as missing:
        publish_diff.load_auth(now_ms=now_ms)

    assert missing.value.exit_code == 2
    assert "https://heydex.ai/connect/?cli=true" in missing.value.user_message
    assert "link --code" in missing.value.user_message

    auth_dir = tmp_path / ".dex"
    auth_dir.mkdir()
    stale_timestamp = now_ms - publish_diff.AUTH_MAX_AGE_MS - 1
    (auth_dir / "heydex-auth.json").write_text(
        json.dumps({"email": "tester@example.com", "sessionToken": "secret", "timestamp": stale_timestamp}),
        encoding="utf-8",
    )

    with pytest.raises(publish_diff.AuthError) as stale:
        publish_diff.load_auth(now_ms=now_ms)

    assert stale.value.exit_code == 2
    assert "connection has expired" in stale.value.user_message
    assert "link --code" in stale.value.user_message


def test_review_payload_uses_exact_methodology_text(tmp_path):
    publish_diff = _load_script()
    workflow = tmp_path / "customer-health.yaml"
    original_text = (
        'id: customer-health\n'
        'name: Customer Health\n'
        'description: "Find customer risk earlier."\n'
        "tags: [success, risk]\n"
        "methodology:\n"
        "  problem: |\n"
        "    First line.\n"
        "    Second line with trailing spaces.  \n"
        "# final comment is part of the methodology file\n"
        "\n"
    )
    workflow.write_text(original_text, encoding="utf-8")

    payload = publish_diff.build_review_payload("token-123", [workflow])

    assert payload["sessionToken"] == "token-123"
    assert len(payload["diffs"]) == 1
    diff = payload["diffs"][0]
    assert diff["diffId"] == "customer-health"
    assert diff["name"] == "Customer Health"
    assert diff["description"] == "Find customer risk earlier."
    assert diff["tags"] == ["success", "risk"]
    assert diff["methodology"] == original_text


def test_wait_for_publish_prints_canonical_profile_url(monkeypatch, capsys):
    publish_diff = _load_script()

    def fake_get_json(api_base, path):
        assert api_base == "https://api.example.test"
        assert path == "/api/review/status?session=SESSION123"
        return {"published": True, "handle": "@davekilleen"}

    monkeypatch.setattr(publish_diff, "get_json", fake_get_json)

    result = publish_diff.wait_for_publish(
        "https://api.example.test",
        "https://heydex.ai",
        "SESSION123",
        poll_seconds=0,
        timeout_seconds=1,
    )

    assert result == 0
    assert capsys.readouterr().out == "Published: https://heydex.ai/diff/davekilleen/\n"
