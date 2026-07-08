"""Validation coverage for the onboarding MCP server.

The docs promise "bulletproof validation — cannot skip Step 4 (email_domain)".
These tests pin that guarantee: per-step field validation, session resume,
and finalize refusing to run with missing steps or an empty email domain.

Run with: pytest core/mcp/tests/test_onboarding_validation.py -v
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "core" / "mcp"))

import onboarding_server  # noqa: E402


def _call(name, arguments=None):
    result = asyncio.run(onboarding_server.handle_call_tool(name, arguments or {}))
    return json.loads(result[0].text)


@pytest.fixture(autouse=True)
def isolated_session(tmp_path, monkeypatch):
    """Point the session file at a throwaway path for every test."""
    monkeypatch.setattr(onboarding_server, "SESSION_FILE", tmp_path / "session.json")


def _complete_steps(through: int) -> None:
    """Drive the wizard through the given step with valid data."""
    _call("start_onboarding_session")
    steps = {
        1: {"name": "Test User"},
        2: {"role_number": 2},
        3: {"company": "Acme", "company_size": "scaling"},
        4: {"email_domain": "acme.com"},
        5: {"pillars": ["Pipeline", "Accounts"]},
        6: {"communication": {"formality": "casual", "directness": "balanced", "career_level": "mid"}},
    }
    for step in range(1, through + 1):
        payload = _call("validate_and_save_step", {"step_number": step, "step_data": steps[step]})
        assert payload["success"] is True, f"step {step} failed: {payload}"


# ---------------------------------------------------------------------------
# Field validators
# ---------------------------------------------------------------------------


class TestValidateEmailDomain:
    def test_accepts_plain_and_multiple_domains(self):
        assert onboarding_server.validate_email_domain("acme.com") == (True, None)
        assert onboarding_server.validate_email_domain("acme.com, acme.io")[0] is True

    @pytest.mark.parametrize(
        "bad,fragment",
        [
            ("", "cannot be empty"),
            ("   ", "cannot be empty"),
            ("@acme.com", "should not include @"),
            ("acme", "at least one dot"),
            ("ac me.com", "invalid characters"),
        ],
    )
    def test_rejects_invalid_domains(self, bad, fragment):
        valid, error = onboarding_server.validate_email_domain(bad)
        assert valid is False
        assert fragment in error


class TestValidatePillars:
    def test_requires_at_least_two_pillars(self):
        assert onboarding_server.validate_pillars([])[0] is False
        assert onboarding_server.validate_pillars(["Only one"])[0] is False
        assert onboarding_server.validate_pillars(["", "  ", "Real"])[0] is False

    def test_accepts_two_and_warns_over_three(self):
        assert onboarding_server.validate_pillars(["A", "B"]) == (True, None)
        valid, warning = onboarding_server.validate_pillars(["A", "B", "C", "D"])
        assert valid is True
        assert "recommended" in warning


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    def test_start_creates_then_resumes_session(self):
        first = _call("start_onboarding_session")
        assert first["success"] is True
        assert "New onboarding session" in first["message"]

        second = _call("start_onboarding_session")
        assert "Resuming" in second["message"]

    def test_force_new_discards_progress(self):
        _complete_steps(through=2)
        payload = _call("start_onboarding_session", {"force_new": True})
        assert payload["data"]["completed_steps"] == []
        assert payload["data"]["current_step"] == 1

    def test_step_requires_active_session(self):
        payload = _call("validate_and_save_step", {"step_number": 1, "step_data": {"name": "X"}})
        assert payload["success"] is False
        assert "No active session" in payload["error"]

    def test_resume_preserves_saved_data(self):
        _complete_steps(through=4)
        resumed = _call("start_onboarding_session")
        assert resumed["data"]["data"]["email_domain"] == "acme.com"
        assert resumed["data"]["current_step"] == 5


# ---------------------------------------------------------------------------
# Step validation
# ---------------------------------------------------------------------------


class TestStepValidation:
    def test_step1_rejects_empty_name(self):
        _call("start_onboarding_session")
        payload = _call("validate_and_save_step", {"step_number": 1, "step_data": {"name": "  "}})
        assert payload["success"] is False
        assert payload["field"] == "name"

    def test_step2_maps_role_number_to_role_group(self):
        _complete_steps(through=1)
        payload = _call("validate_and_save_step", {"step_number": 2, "step_data": {"role_number": 2}})
        assert payload["success"] is True
        session = json.loads(onboarding_server.SESSION_FILE.read_text())
        assert session["data"]["role"] == "Sales / Account Executive"
        assert session["data"]["role_group"] == "sales"

    def test_step3_rejects_unknown_company_size(self):
        _complete_steps(through=2)
        payload = _call(
            "validate_and_save_step",
            {"step_number": 3, "step_data": {"company_size": "gigantic"}},
        )
        assert payload["success"] is False
        assert payload["field"] == "company_size"

    def test_step4_rejects_domain_with_at_sign(self):
        _complete_steps(through=3)
        payload = _call(
            "validate_and_save_step",
            {"step_number": 4, "step_data": {"email_domain": "@acme.com"}},
        )
        assert payload["success"] is False
        assert payload["field"] == "email_domain"
        # And the step is not marked complete
        status = _call("get_onboarding_status")
        assert 4 in status["data"]["missing_steps"]

    def test_step6_rejects_invalid_enums(self):
        _complete_steps(through=5)
        payload = _call(
            "validate_and_save_step",
            {"step_number": 6, "step_data": {"communication": {"formality": "sassy"}}},
        )
        assert payload["success"] is False
        assert payload["field"] == "formality"

    def test_invalid_step_number_is_rejected(self):
        _call("start_onboarding_session")
        payload = _call("validate_and_save_step", {"step_number": 9, "step_data": {}})
        assert payload["success"] is False


# ---------------------------------------------------------------------------
# Status + finalize gate
# ---------------------------------------------------------------------------


class TestFinalizeGate:
    def test_status_tracks_missing_steps_and_progress(self):
        _complete_steps(through=3)
        status = _call("get_onboarding_status")["data"]
        assert status["completed_steps"] == [1, 2, 3]
        assert status["missing_steps"] == [4, 5, 6]
        assert "Email Domain (CRITICAL)" in status["missing_step_names"]
        assert status["ready_to_finalize"] is False
        assert status["progress_percent"] == 50.0

    def test_finalize_refuses_when_steps_missing(self):
        _complete_steps(through=3)
        payload = _call("finalize_onboarding")
        assert payload["success"] is False
        assert "missing steps" in payload["error"]

    def test_finalize_refuses_when_email_domain_emptied(self):
        _complete_steps(through=6)
        # Simulate a corrupted/hand-edited session: step 4 marked done, value gone
        session = json.loads(onboarding_server.SESSION_FILE.read_text())
        session["data"]["email_domain"] = ""
        onboarding_server.SESSION_FILE.write_text(json.dumps(session))

        payload = _call("finalize_onboarding")
        assert payload["success"] is False
        assert "email_domain is required" in payload["error"]

    def test_status_ready_after_all_steps(self):
        _complete_steps(through=6)
        status = _call("get_onboarding_status")["data"]
        assert status["ready_to_finalize"] is True
        assert status["progress_percent"] == 100.0
