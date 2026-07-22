"""Contracts for the explicit-consent MCP and skill creation instructions."""

from __future__ import annotations

from pathlib import Path

from core import portable_contract

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


def test_one_off_consent_claims_are_honest_about_same_user_programs() -> None:
    skill = (ROOT / ".claude/skills/create-mcp/SKILL.md").read_text(encoding="utf-8")
    governance = (ROOT / "docs/testing-governance.md").read_text(encoding="utf-8")

    for text in (skill, governance):
        normalized = " ".join(text.split())
        assert "prevents the automatic/recurring health checks" in normalized
        assert "each explicit approval single-use" in normalized
        assert "not protection against another program running as you" in normalized


def test_dex_update_unconditionally_rejects_an_upstream_trust_registry() -> None:
    trust_registry = "System/trusted-mcps.yaml"
    resolution = portable_contract.resolve(trust_registry)

    assert resolution.ownership == "vault"
    assert resolution.rule_id == "vault-trusted-mcps"
    for exists in (False, True):
        verdict = portable_contract.update_write_verdict(
            trust_registry, exists=exists
        )
        assert verdict.allowed is False
        assert verdict.action == "never"

    text = (ROOT / ".claude/skills/dex-update/SKILL.md").read_text(encoding="utf-8")

    assert "Every lifecycle operation goes through `core.lifecycle.service`" in text
    assert "an unsafe path" in text
    assert "refreshed by the authorized lifecycle plan" in text
    assert "The lifecycle service owns every mutation." in text


def test_create_skill_runs_frontmatter_validator_before_confirmation() -> None:
    text = (ROOT / ".claude/skills/create-skill/SKILL.md").read_text(encoding="utf-8")
    validation = text.index("### Step 2.5: Validate Frontmatter")
    confirmation = text.index("### Step 3: Confirm")

    assert validation < confirmation
    assert "validators.validate_skill_frontmatter" in text
    assert "show the validation result" in text
