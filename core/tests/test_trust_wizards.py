"""Contracts for the explicit-consent MCP and skill creation instructions."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_create_mcp_offers_one_off_snapshot_check_and_default_no_blessing() -> None:
    text = (ROOT / ".claude/skills/create-mcp/SKILL.md").read_text(encoding="utf-8")

    assert "Want me to prove it starts?" in text
    assert "--check-mcp-once" in text
    assert "--issue-mcp-once-consent" in text
    assert "--consent-token" in text
    assert "do not issue" in text
    assert "temporary vault" in " ".join(text.split())
    assert "runs it once" in text
    assert "with your user permissions" in text
    assert "trusts whatever it imports" in text
    assert "nightly and in deep scans" in text
    assert "**Default: No.**" in text
    assert "--bless-mcp" in text
    assert "vault-relative path" in text
    assert "sha256" in text
    assert "remote, HTTP, npm, npx, and binary entries cannot be blessed" in text


def test_dex_update_unconditionally_rejects_an_upstream_trust_registry() -> None:
    text = (ROOT / ".claude/skills/dex-update/SKILL.md").read_text(encoding="utf-8")

    capture = text.index("protect_trust_registry.py\" capture")
    merge = text.index("git merge upstream/release --no-edit")
    restore = text.index("protect_trust_registry.py\" restore")

    assert capture < merge < restore
    assert "whether the merge was clean or conflicted" in text
    assert "Upstream may **never** supply" in text
    assert "removes it from the Git index and warns" in text


def test_create_skill_runs_frontmatter_validator_before_confirmation() -> None:
    text = (ROOT / ".claude/skills/create-skill/SKILL.md").read_text(encoding="utf-8")
    validation = text.index("### Step 2.5: Validate Frontmatter")
    confirmation = text.index("### Step 3: Confirm")

    assert validation < confirmation
    assert "validators.validate_skill_frontmatter" in text
    assert "show the validation result" in text
