"""Behavioral poison pills for trust, channel, and credential safety probes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.utils import doctor, smoke


def _known_bad_doctor_results(tmp_path: Path) -> dict[str, doctor.ProbeResult]:
    vault = tmp_path / "vault"
    (vault / "System/integrations").mkdir(parents=True)
    (vault / "core").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (vault / "System/user-profile.yaml").write_text(
        "updates:\n  channel: nightly\n",
        encoding="utf-8",
    )
    (vault / "System/integrations/config.yaml").write_text(
        "teams:\n  enabled: true\n",
        encoding="utf-8",
    )
    external = tmp_path / "external-mcp.json"
    external.write_text('{"mcpServers": {}}\n', encoding="utf-8")
    (vault / ".mcp.json").symlink_to(external)
    context = doctor.DoctorContext(
        vault_root=vault,
        repo_root=vault,
        home=home,
        now=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )
    return {
        "channel": doctor._probe_core_drift(context),
        "trust": doctor._probe_customization_mcp(context),
        "credential": doctor._probe_integrations_enabled(context),
    }


def _assert_known_bad_doctor_probes_fail_closed(tmp_path: Path) -> None:
    results = _known_bad_doctor_results(tmp_path)
    assert results["channel"].verdict in {"BROKEN", "UNKNOWN"}
    assert results["trust"].verdict in {"BROKEN", "UNKNOWN"}
    assert results["credential"].verdict in {"BROKEN", "UNKNOWN"}


def test_doctor_split_safety_probes_fail_closed_on_known_bad_fixtures(
    tmp_path: Path,
) -> None:
    _assert_known_bad_doctor_probes_fail_closed(tmp_path)


def test_doctor_behavior_guard_turns_red_when_core_drift_is_gutted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        doctor,
        "_probe_core_drift",
        lambda _context: doctor.ProbeResult("OK", "gutted probe"),
    )

    with pytest.raises(AssertionError):
        _assert_known_bad_doctor_probes_fail_closed(tmp_path)


def test_smoke_trust_and_credentials_fail_closed_on_known_bad_mcp(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    (source / "System").mkdir(parents=True)
    (source / "System/.onboarding-complete").write_text("{}\n", encoding="utf-8")
    secret = "scanner-positive-fixture-value"
    (source / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "custom-untrusted": {
                        "command": "python3",
                        "args": ["custom-mcp/server.py"],
                        "env": {"API_TOKEN": secret},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    isolated = tmp_path / "isolated"
    isolated.mkdir()

    smoke._prepare_mcp_vault(source, source, isolated, None, None)
    result = smoke._journey_mcp_startup(isolated, tmp_path)

    assert result["verdict"] in {"BROKEN", "UNKNOWN"}
    assert secret not in result["detail"]
    assert secret.encode() not in (isolated / smoke.MCP_PLAN).read_bytes()
