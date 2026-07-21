"""Poison-pill guard: split probes must never replace shipped safety probes."""

from pathlib import Path

from core.utils import doctor, smoke

ROOT = Path(__file__).resolve().parents[2]


def test_doctor_split_registry_retains_trust_channel_and_credential_surfaces() -> None:
    ids = {definition.id for definition in (*doctor.QUICK_CHECKS, *doctor.DEEP_CHECKS)}
    source = (ROOT / "core/utils/doctor.py").read_text(encoding="utf-8")

    assert {
        "customizations.mcp",
        "core.drift",
        "integrations.enabled",
        "mcp.registered",
    } <= ids
    for symbol in (
        "release_channel.read_channel",
        "load_trusted_mcp_registry",
        "snapshot_trusted_mcp",
        "--credential-scan",
        "run_credential_workflow",
    ):
        assert symbol in source


def test_smoke_split_registry_retains_trust_channel_and_credential_surfaces() -> None:
    ids = {definition.id for definition in smoke.JOURNEYS}
    source = (ROOT / "core/utils/smoke.py").read_text(encoding="utf-8")

    assert {"configs", "task_lifecycle", "mcp_startup", "skills", "hooks"} <= ids
    for symbol in (
        "release_channel.read_channel",
        "load_trusted_mcp_registry",
        "snapshot_trusted_mcp",
        "credential_migration_exceptions.json",
        "integration_credentials.py",
    ):
        assert symbol in source
