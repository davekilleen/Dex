"""Tests for the signed significant-capability registry boundary.

The fixture is deliberately loaded from the repository-owned registry and then
mutated in memory.  This keeps the tests focused on the validator while the
canonical discovery code remains the only source of candidate identities.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from core import lens_significant_capabilities as significant_capabilities
from core.lens_significant_capabilities import (
    REGISTRY_PATH,
    SignificantCapabilityRegistryError,
    iter_significant_registry_errors,
    load_significant_capability_registry,
    validate_significant_capability_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_FAMILIES = {
    "meeting-follow-through",
    "living-people-company-context",
    "durable-task-continuity",
    "external-task-interoperability",
    "connected-work-context",
    "pipedrive-pipeline-continuity",
    "daily-weekly-operating-rhythm",
    "durable-work-memory",
    "proactive-health-and-recovery",
    "backup-and-restore-confidence",
    "safe-change-and-rewind",
    "capability-discovery-and-adoption",
    "privacy-safe-feedback-loop",
    "career-growth-evidence",
}


def _provider_resolver(provider_id: str) -> dict[str, bool]:
    """Inject authoritative connection-manager truth in test-only fixtures."""

    return {
        "exists": provider_id in {"google", "linear"},
        "supported": provider_id in {"google", "linear"},
        "security_vetted": provider_id in {"google", "linear"},
    }


def _raw_registry() -> dict[str, object]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _valid_registry() -> dict[str, object]:
    payload = _raw_registry()
    validate_significant_capability_registry(
        payload,
        release_root=REPO_ROOT,
        provider_resolver=_provider_resolver,
    )
    return payload


def _assert_invalid(payload: dict[str, object], message: str, *, resolver=_provider_resolver) -> None:
    with pytest.raises(SignificantCapabilityRegistryError, match=message):
        validate_significant_capability_registry(
            payload,
            release_root=REPO_ROOT,
            provider_resolver=resolver,
        )


def test_canonical_registry_has_the_fourteen_reviewed_families() -> None:
    payload = load_significant_capability_registry(
        release_root=REPO_ROOT,
        provider_resolver=_provider_resolver,
    )

    assert payload["registry_version"] == 1
    assert set(payload) == {
        "registry_version",
        "capability_aliases",
        "families",
        "coverage_exceptions",
    }
    assert {family["family_id"] for family in payload["families"]} == EXPECTED_FAMILIES


def test_registry_maps_every_discovered_mcp_server_and_required_tool_sets() -> None:
    payload = load_significant_capability_registry(
        release_root=REPO_ROOT,
        provider_resolver=_provider_resolver,
    )
    families = payload["families"]
    members = {member for family in families for member in family["member_capability_ids"]}
    assert {
        "dex-analytics",
        "dex-calendar-mcp",
        "dex-career-mcp",
        "dex-customization-migration-mcp",
        "dex-granola-mcp",
        "dex-improvements-mcp",
        "dex-onboarding-mcp",
        "dex-pipedrive-mcp",
        "dex-resume-mcp",
        "dex-session-memory",
        "dex-work-mcp",
    } <= members

    components = [component for family in families for component in family["components"]]
    work_tools = {
        component["tool_name"]
        for component in components
        if component["component_type"] == "mcp-tool" and component["server_id"] == "dex-work-mcp"
    }
    assert {"create_task", "lookup_person", "get_meeting_context", "sync_external_tasks"} <= work_tools
    career_tools = {
        component["tool_name"]
        for component in components
        if component["component_type"] == "mcp-tool" and component["server_id"] == "dex-career-mcp"
    }
    resume_tools = {
        component["tool_name"]
        for component in components
        if component["component_type"] == "mcp-tool" and component["server_id"] == "dex-resume-mcp"
    }
    assert {
        "analyze_coverage",
        "generate_evidence_from_work",
        "scan_evidence",
        "skills_gap_analysis",
    } <= career_tools
    assert {"compile_resume", "pull_career_evidence", "validate_metrics"} <= resume_tools


def test_session_memory_is_explicitly_in_durable_work_memory() -> None:
    payload = load_significant_capability_registry(
        release_root=REPO_ROOT,
        provider_resolver=_provider_resolver,
    )
    family = next(item for item in payload["families"] if item["family_id"] == "durable-work-memory")
    assert "dex-session-memory" in family["member_capability_ids"]


def test_connected_work_family_explains_connector_breadth_without_overclaiming_support() -> None:
    payload = load_significant_capability_registry(
        release_root=REPO_ROOT,
        provider_resolver=_provider_resolver,
    )
    family = next(
        item for item in payload["families"] if item["family_id"] == "connected-work-context"
    )

    assert "hundreds of connector definitions" in family["outcome"]
    assert "explicitly supported and security-vetted" in family["outcome"]


def test_career_family_contains_both_servers_and_exact_tool_components() -> None:
    payload = load_significant_capability_registry(
        release_root=REPO_ROOT,
        provider_resolver=_provider_resolver,
    )
    family = next(item for item in payload["families"] if item["family_id"] == "career-growth-evidence")
    assert {"dex-career-mcp", "dex-resume-mcp"} <= set(family["member_capability_ids"])
    components = {
        (item["server_id"], item["tool_name"]) for item in family["components"] if item["component_type"] == "mcp-tool"
    }
    assert ("dex-career-mcp", "promotion_readiness_score") in components
    assert ("dex-resume-mcp", "compile_resume") in components


def test_aliases_are_closed_and_do_not_collide_with_canonical_ids() -> None:
    payload = _valid_registry()
    aliases = payload["capability_aliases"]
    assert all(set(alias) == {"alias", "capability_id"} for alias in aliases)
    alias_map = {item["alias"]: item["capability_id"] for item in aliases}
    assert {
        "calendar": "dex-calendar-mcp",
        "career": "dex-career-mcp",
        "granola": "dex-granola-mcp",
        "resume": "dex-resume-mcp",
        "work": "dex-work-mcp",
    }.items() <= alias_map.items()

    duplicate = copy.deepcopy(payload)
    duplicate["capability_aliases"].append(copy.deepcopy(aliases[0]))
    _assert_invalid(duplicate, "duplicate or colliding alias")

    colliding = copy.deepcopy(payload)
    colliding["capability_aliases"][0]["alias"] = colliding["families"][0]["family_id"]
    _assert_invalid(colliding, "duplicate or colliding alias")


def test_closed_fields_unknown_member_jobs_and_tools_fail_closed() -> None:
    payload = _valid_registry()

    unknown_field = copy.deepcopy(payload)
    unknown_field["families"][0]["unexpected"] = True
    _assert_invalid(unknown_field, "fields are not closed")

    unknown_member = copy.deepcopy(payload)
    unknown_member["families"][0]["member_capability_ids"].append("missing-capability")
    _assert_invalid(unknown_member, "unknown member capability")

    unknown_job = copy.deepcopy(payload)
    unknown_job["families"][0]["jobs"].append("unknown-job")
    _assert_invalid(unknown_job, "unknown job")

    unknown_tool = copy.deepcopy(payload)
    unknown_tool["families"][0]["components"].append(
        {
            "component_type": "mcp-tool",
            "server_id": "dex-work-mcp",
            "tool_name": "not_a_work_tool",
        }
    )
    _assert_invalid(unknown_tool, "unknown MCP tool")


def test_components_assessments_and_stored_status_are_closed() -> None:
    payload = _valid_registry()

    duplicate_component = copy.deepcopy(payload)
    component = copy.deepcopy(duplicate_component["families"][0]["components"][0])
    duplicate_component["families"][0]["components"].append(component)
    _assert_invalid(duplicate_component, "duplicate component")

    illegal_status = copy.deepcopy(payload)
    illegal_status["families"][0]["availability"] = "active"
    _assert_invalid(illegal_status, "fields are not closed")

    malformed_assessment = copy.deepcopy(payload)
    malformed_assessment["families"][0]["assessment"] = {"mode": "automatic"}
    _assert_invalid(malformed_assessment, "assessment")

    unsafe_text = copy.deepcopy(payload)
    unsafe_text["families"][0]["outcome"] = "unsafe\ntext"
    _assert_invalid(unsafe_text, "control characters")


def test_provider_identity_and_missing_dependency_fail_honestly(tmp_path: Path) -> None:
    payload = _valid_registry()
    unknown_provider = copy.deepcopy(payload)
    provider = next(
        component
        for family in unknown_provider["families"]
        for component in family["components"]
        if component["component_type"] == "nango-provider"
    )
    provider["provider_id"] = "not-a-real-provider"
    _assert_invalid(unknown_provider, "unknown provider")

    with pytest.raises(SignificantCapabilityRegistryError, match="pinned provider source"):
        significant_capabilities._default_provider_resolver(
            "google",
            release_root=tmp_path,
        )


def test_provider_claims_must_match_connection_manager_support_and_vetting() -> None:
    payload = _valid_registry()
    provider = next(
        component
        for family in payload["families"]
        for component in family["components"]
        if component["component_type"] == "nango-provider"
    )
    provider["provider_id"] = "github"

    _assert_invalid(
        payload,
        "security_vetted does not match authoritative provider truth",
        resolver=lambda provider_id: {
            "exists": provider_id in {"github", "google", "linear"},
            "supported": provider_id in {"github", "google", "linear"},
            "security_vetted": provider_id in {"google", "linear"},
        },
    )


def test_provider_support_claim_must_match_connection_manager_truth() -> None:
    payload = _valid_registry()
    provider = next(
        component
        for family in payload["families"]
        for component in family["components"]
        if component["component_type"] == "nango-provider"
    )
    provider["dex_support"] = "unsupported"

    _assert_invalid(payload, "dex_support does not match authoritative provider truth")


def test_canonical_provider_rows_are_exactly_the_reviewed_google_and_linear_set() -> None:
    payload = _valid_registry()
    providers = {
        component["provider_id"]: component
        for family in payload["families"]
        for component in family["components"]
        if component["component_type"] == "nango-provider"
    }

    assert set(providers) == {"google", "linear"}
    assert all(provider["dex_support"] == "supported" for provider in providers.values())
    assert all(provider["security_vetted"] is True for provider in providers.values())


def test_provider_duplicate_identity_ignores_mutable_claim_fields() -> None:
    payload = _valid_registry()
    family = next(
        item
        for item in payload["families"]
        if any(component["component_type"] == "nango-provider" for component in item["components"])
    )
    provider = next(
        component for component in family["components"] if component["component_type"] == "nango-provider"
    )
    duplicate = copy.deepcopy(provider)
    duplicate["dex_support"] = "unsupported"
    duplicate["security_vetted"] = False
    family["components"].append(duplicate)

    _assert_invalid(payload, "duplicate component")

    assert significant_capabilities._component_identity(provider) == (
        "nango-provider",
        provider["provider_id"],
    )
    assert significant_capabilities._component_identity(provider) == (
        significant_capabilities._component_identity(duplicate)
    )


@pytest.mark.parametrize(
    ("component", "identity"),
    [
        (
            {"component_type": "capability", "capability_id": "daily-plan"},
            ("capability", "daily-plan"),
        ),
        (
            {
                "component_type": "mcp-tool",
                "server_id": "dex-work-mcp",
                "tool_name": "create_task",
            },
            ("mcp-tool", "dex-work-mcp", "create_task"),
        ),
        (
            {"component_type": "source-component", "component_id": "work-task-continuity"},
            ("source-component", "work-task-continuity"),
        ),
    ],
)
def test_component_identity_matches_the_lens_contract(
    component: dict[str, str],
    identity: tuple[str, ...],
) -> None:
    assert significant_capabilities._component_identity(component) == identity


def test_mcp_component_sets_must_match_every_discovered_server_exactly() -> None:
    payload = _valid_registry()
    work_family = next(
        family for family in payload["families"] if family["family_id"] == "proactive-health-and-recovery"
    )
    work_family["components"] = [
        component
        for component in work_family["components"]
        if not (
            component["component_type"] == "mcp-tool"
            and component["server_id"] == "dex-work-mcp"
            and component["tool_name"] == "check_safety_gate"
        )
    ]
    _assert_invalid(payload, "MCP tool coverage mismatch.*dex-work-mcp")


def test_safe_change_family_does_not_claim_held_customization_activation() -> None:
    payload = _valid_registry()
    safe_change = next(family for family in payload["families"] if family["family_id"] == "safe-change-and-rewind")
    text = safe_change["outcome"].lower()
    assert "custom" not in text
    assert "dex-customization-migration-mcp" not in safe_change["member_capability_ids"]
    assert all(
        not (component["component_type"] == "mcp-tool" and component["server_id"] == "dex-customization-migration-mcp")
        for component in safe_change["components"]
    )
    adoption = next(
        family for family in payload["families"] if family["family_id"] == "capability-discovery-and-adoption"
    )
    assert "assessment and capsule evidence" in adoption["outcome"]
    assert "activation and rewind remain held" in adoption["outcome"]


def test_source_components_resolve_against_the_closed_reviewed_set() -> None:
    payload = _valid_registry()
    source = next(
        component
        for family in payload["families"]
        for component in family["components"]
        if component["component_type"] == "source-component"
    )
    source["component_id"] = "fabricated-source-component"
    _assert_invalid(payload, "unknown source component")


@pytest.mark.parametrize(
    "value",
    [
        False,
        "false",
        "true",
        {"exists": "true", "supported": True, "security_vetted": True},
        {"exists": True, "supported": "true", "security_vetted": True},
        {"exists": True, "supported": True, "security_vetted": "true"},
        {"exists": True, "supported": True},
    ],
)
def test_provider_resolvers_require_three_literal_boolean_truth_fields(value: object) -> None:
    _assert_invalid(
        _raw_registry(),
        "unknown provider",
        resolver=lambda _provider_id: value,
    )


def test_mapping_provider_resolver_requires_each_value_to_be_true() -> None:
    _assert_invalid(
        _raw_registry(),
        "unknown provider",
        resolver={
            "google": {"exists": False, "supported": True, "security_vetted": True},
            "linear": {"exists": True, "supported": True, "security_vetted": True},
        },
    )


def test_active_core_and_high_leaves_must_be_covered_or_excepted() -> None:
    payload = _valid_registry()
    uncovered = copy.deepcopy(payload)
    meeting = next(family for family in uncovered["families"] if family["family_id"] == "meeting-follow-through")
    meeting["member_capability_ids"] = []
    _assert_invalid(uncovered, "active core/high capability")


def test_iter_errors_is_a_non_throwing_lint_surface() -> None:
    payload = _raw_registry()
    payload["families"][0]["member_capability_ids"].append("stale-id")
    errors = tuple(
        iter_significant_registry_errors(
            payload,
            release_root=REPO_ROOT,
            provider_resolver=_provider_resolver,
        )
    )
    assert errors
    assert any("unknown member capability" in error for error in errors)
