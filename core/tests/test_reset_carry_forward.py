"""Reset over a populated vault must carry forward every non-re-answered setting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from core.tests.test_provision_parity import (
    _invoke_provision,
    _prepare_provision_vault,
    _run_provision,
)

pytestmark = pytest.mark.skipif(
    __import__("shutil").which("node") is None, reason="node is not installed"
)

ORIGINAL_COMPLETED_AT = "2026-01-15T10:00:00.000Z"

# A profile shaped by months of real use: connected calendar, journaling on,
# local git snapshots on, a fiscal-year quarter start, an explicit auto
# entity-creation choice, a deliberately disabled room, analytics identity.
POPULATED_PROFILE = {
    "name": "Dana",
    "role": "Fractional CPO",
    "role_group": "product",
    "company": "OldCo",
    "company_size": "startup",
    "email_domain": "example.org",
    "work_email": "dana@example.org",
    "timezone": "Europe/Dublin",
    "working_style": "focused",
    "working_context": {
        "role_focus": "Product strategy for early customers",
        "key_people": ["Sam"],
    },
    "calendar": {"provider": "apple", "work_calendar": "Work"},
    "working_week": {"days": ["monday", "tuesday", "wednesday"]},
    "communication": {"formality": "formal", "directness": "very_direct"},
    "pillars": ["Product Strategy", "Customers"],
    "meeting_sources": {"primary": "granola", "notes_folder": ""},
    "meeting_processing": {"mode": "manual", "api_provider": "anthropic"},
    "journaling": {"morning": True, "evening": True, "weekly": False},
    "vault": {"auto_commit": True},
    "feedback": {"review_mode": "auto-send"},
    "quarterly_planning": {"enabled": True, "q1_start_month": 4},
    "entity_creation": {"mode": "auto"},
    "capabilities": {
        "career": {"enabled": False},
        "companies": {"enabled": True},
        "quarter_goals": {"enabled": True},
    },
    "analytics": {"enabled": True, "visitor_id": "v-123", "account_id": "a-456"},
}

POPULATED_PILLARS = {
    "pillars": [
        {
            "id": "product-strategy",
            "name": "Product Strategy",
            "description": "Own the roadmap",
            "keywords": ["roadmap", "strategy", "positioning"],
        },
        {
            "id": "customers",
            "name": "Customers",
            "description": "",
            "keywords": ["churn", "nps"],
        },
    ],
    "priority_limits": {"P0": 2, "P1": 4, "P2": 8},
}

COMPLETED_MARKER = {
    "completed": True,
    "completed_at": ORIGINAL_COMPLETED_AT,
    "provisioned_by": "core/provision.cjs",
    "adopted": False,
    "version": "1.90.0",
    "user_name": "Dana",
    "role": "Fractional CPO",
    "email_domain": "example.org",
    "has_pillars": True,
    "phase2_completed": True,
    "pre_analysis_deferred": True,
}

# The answers a reset re-collects. The disabled career room is deliberately
# not re-answered so the merge must keep it off.
RESET_OVERLAY = {
    "name": "Dana",
    "role": "Chief Product Officer",
    "role_group": "product",
    "company": "NewCo",
    "company_size": "scaling",
    "email_domain": "example.com",
    "pillars": [
        {"name": "Product Strategy", "description": ""},
        {"name": "Team", "description": "Grow the org"},
    ],
    "communication": {"formality": "casual"},
    "working_week": {"days": ["monday", "tuesday", "wednesday", "thursday", "friday"]},
    "capabilities": {
        "companies": {"enabled": True},
        "quarter_goals": {"enabled": True},
    },
}


def _prepare_completed_vault(tmp_path: Path) -> tuple[Path, Path]:
    vault = _prepare_provision_vault(
        tmp_path,
        profile_text=yaml.safe_dump(POPULATED_PROFILE, sort_keys=False),
    )
    (vault / "System/pillars.yaml").write_text(
        yaml.safe_dump(POPULATED_PILLARS, sort_keys=False),
        encoding="utf-8",
    )
    (vault / "System/.onboarding-complete").write_text(
        json.dumps(COMPLETED_MARKER, indent=2) + "\n",
        encoding="utf-8",
    )
    overlay = tmp_path / "reset-profile.json"
    overlay.write_text(json.dumps(RESET_OVERLAY), encoding="utf-8")
    return vault, overlay


def test_reset_over_completed_vault_merges_instead_of_replacing(
    tmp_path: Path,
) -> None:
    vault, overlay = _prepare_completed_vault(tmp_path)

    summary = _run_provision(vault, "--onboard", "--profile", str(overlay))

    assert summary["profile_plan"]["mode"] == "merge"
    profile = yaml.safe_load(
        (vault / "System/user-profile.yaml").read_text(encoding="utf-8")
    )

    # Re-answered keys win.
    assert profile["role"] == "Chief Product Officer"
    assert profile["role_group"] == "product"
    assert profile["company"] == "NewCo"
    assert profile["company_size"] == "scaling"
    assert profile["email_domain"] == "example.com"
    assert profile["communication"]["formality"] == "casual"
    assert profile["working_week"] == {
        "days": ["monday", "tuesday", "wednesday", "thursday", "friday"]
    }

    # Every key the user did not re-answer carries forward — including keys
    # the template never mentions.
    assert profile["work_email"] == "dana@example.org"
    assert profile["calendar"] == {"provider": "apple", "work_calendar": "Work"}
    assert profile["working_context"] == {
        "role_focus": "Product strategy for early customers",
        "key_people": ["Sam"],
    }
    assert profile["timezone"] == "Europe/Dublin"
    assert profile["working_style"] == "focused"
    assert profile["meeting_sources"]["primary"] == "granola"
    assert profile["meeting_processing"] == {
        "mode": "manual",
        "api_provider": "anthropic",
    }
    assert profile["journaling"]["morning"] is True
    assert profile["journaling"]["evening"] is True
    assert profile["vault"]["auto_commit"] is True
    assert profile["feedback"]["review_mode"] == "auto-send"
    assert profile["quarterly_planning"]["q1_start_month"] == 4
    assert profile["analytics"]["visitor_id"] == "v-123"
    assert profile["analytics"]["account_id"] == "a-456"

    # An explicit entity_creation choice is never forced back to suggest.
    assert profile["entity_creation"] == {"mode": "auto"}

    # A room the user disabled and did not re-answer stays disabled.
    assert profile["capabilities"]["career"] == {"enabled": False}
    assert profile["capabilities"]["companies"]["enabled"] is True

    # The communication answer merges over, not through, the untouched keys.
    assert profile["communication"]["directness"] == "very_direct"


def test_reset_over_completed_vault_preserves_pillar_metadata(
    tmp_path: Path,
) -> None:
    vault, overlay = _prepare_completed_vault(tmp_path)

    summary = _run_provision(vault, "--onboard", "--profile", str(overlay))

    pillars = yaml.safe_load(
        (vault / "System/pillars.yaml").read_text(encoding="utf-8")
    )
    assert pillars["priority_limits"] == {"P0": 2, "P1": 4, "P2": 8}
    by_name = {pillar["name"]: pillar for pillar in pillars["pillars"]}
    kept = by_name["Product Strategy"]
    assert kept["keywords"] == ["roadmap", "strategy", "positioning"]
    assert kept["description"] == "Own the roadmap"
    new = by_name["Team"]
    assert new["description"] == "Grow the org"
    assert "keywords" not in new
    assert "Customers" not in by_name
    assert summary["pillars_plan"] == pillars


def test_reset_over_completed_vault_updates_marker_but_keeps_original_date(
    tmp_path: Path,
) -> None:
    vault, overlay = _prepare_completed_vault(tmp_path)

    _run_provision(vault, "--onboard", "--profile", str(overlay))

    marker = json.loads(
        (vault / "System/.onboarding-complete").read_text(encoding="utf-8")
    )
    assert marker["completed"] is True
    assert marker["completed_at"] == ORIGINAL_COMPLETED_AT
    assert marker["role"] == "Chief Product Officer"
    assert marker["email_domain"] == "example.com"
    assert marker["has_pillars"] is True
    assert marker["phase2_completed"] is True
    assert marker["last_reconfigured_at"] > ORIGINAL_COMPLETED_AT


def test_repeated_reset_converges_without_further_writes(tmp_path: Path) -> None:
    vault, overlay = _prepare_completed_vault(tmp_path)

    _run_provision(vault, "--onboard", "--profile", str(overlay))
    profile_before = (vault / "System/user-profile.yaml").read_bytes()
    pillars_before = (vault / "System/pillars.yaml").read_bytes()
    marker_before = (vault / "System/.onboarding-complete").read_bytes()

    repeated = _run_provision(vault, "--onboard", "--profile", str(overlay))

    assert repeated["created"] == []
    assert (vault / "System/user-profile.yaml").read_bytes() == profile_before
    assert (vault / "System/pillars.yaml").read_bytes() == pillars_before
    assert (vault / "System/.onboarding-complete").read_bytes() == marker_before


def test_reset_dry_run_reports_the_merge_plan_without_writing(
    tmp_path: Path,
) -> None:
    vault, overlay = _prepare_completed_vault(tmp_path)
    profile_before = (vault / "System/user-profile.yaml").read_bytes()

    preview = _invoke_provision(
        vault, "--onboard", "--profile", str(overlay), "--dry-run"
    )

    assert preview.returncode == 0, preview.stderr
    summary = json.loads(preview.stdout)
    assert summary["profile_plan"]["mode"] == "merge"
    planned = summary["profile_plan"]["profile"]
    assert planned["role"] == "Chief Product Officer"
    assert planned["work_email"] == "dana@example.org"
    assert planned["entity_creation"] == {"mode": "auto"}
    assert (vault / "System/user-profile.yaml").read_bytes() == profile_before


def test_crashed_onboarding_without_marker_keeps_replace_behavior(
    tmp_path: Path,
) -> None:
    vault, overlay = _prepare_completed_vault(tmp_path)
    (vault / "System/.onboarding-complete").unlink()

    summary = _run_provision(vault, "--onboard", "--profile", str(overlay))

    assert summary["profile_plan"]["mode"] == "replace"
    profile = yaml.safe_load(
        (vault / "System/user-profile.yaml").read_text(encoding="utf-8")
    )
    # Replace-from-answers: nothing outside the answers survives, so a broken
    # first run cannot fossilize junk into the profile.
    assert "work_email" not in profile
    assert "working_context" not in profile
    assert profile["entity_creation"] == {"mode": "suggest"}
    assert profile["journaling"] == {"morning": False, "evening": False, "weekly": False}
    marker = json.loads(
        (vault / "System/.onboarding-complete").read_text(encoding="utf-8")
    )
    assert marker["completed_at"] != ORIGINAL_COMPLETED_AT
    assert "last_reconfigured_at" not in marker
    pillars = yaml.safe_load(
        (vault / "System/pillars.yaml").read_text(encoding="utf-8")
    )
    assert "priority_limits" not in pillars
