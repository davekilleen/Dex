"""End-to-end coverage for the reachable credential workflow."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.utils import credential_workflow
from core.utils.credential_remediation import CredentialMigrationInspection, MigrationResult
from core.utils.credential_workflow import run_credential_workflow
from core.utils.integration_credentials import resolve_service_credentials


def _legacy_vault(root: Path) -> Path:
    config = root / "System/integrations/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"todoist:\r\n  enabled: true\r\n  api_key: synthetic-workflow-value\r\n")
    return config


def test_real_workflow_migrates_legacy_yaml_preserves_mcp_and_exactly_rewinds(tmp_path):
    config = _legacy_vault(tmp_path)
    original = config.read_bytes()
    mcp = tmp_path / ".mcp.json"
    mcp.write_bytes(b'{"mcpServers":{"other":{"enabled":true}}}\r\n')
    mcp_before = mcp.read_bytes()

    migrated = run_credential_workflow(tmp_path, "migrate")

    assert migrated["migration_state"] == "migrated-local-config"
    assert mcp.read_bytes() == mcp_before
    env = tmp_path / ".env"
    assert env.stat().st_mode & 0o777 == 0o600
    assert b"synthetic-workflow-value" not in config.read_bytes()

    rewound = run_credential_workflow(tmp_path, "rewind", journal_id=str(migrated["journal_id"]))
    assert rewound["migration_state"] == "rewound"
    assert config.read_bytes() == original
    assert not env.exists()
    assert mcp.read_bytes() == mcp_before


def test_scan_output_is_redacted_and_uses_only_opaque_finding_ids(tmp_path):
    _legacy_vault(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    report = run_credential_workflow(tmp_path, "scan")
    rendered = repr(report)
    assert report["findings"]
    assert "synthetic-workflow-value" not in rendered
    assert "config.yaml" not in rendered


@pytest.mark.parametrize(
    "value",
    [" leading", "trailing ", '"matching quotes"', r"back\\slash", "hash#value", "equals=value"],
)
def test_full_crlf_migration_and_runtime_resolution_preserve_exact_scalar(tmp_path, value):
    config = tmp_path / "System/integrations/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_bytes(
        ("todoist:\r\n  enabled: true\r\n  api_key: " + json.dumps(value) + "\r\n").encode()
    )
    migrated = run_credential_workflow(tmp_path, "migrate")
    assert migrated["migration_state"] == "migrated-local-config"
    assert resolve_service_credentials(
        "todoist",
        {"api_key_env_var": "TODOIST_API_KEY"},
        tmp_path,
    ) == {"api_key": value}
    assert b"\r\n" in config.read_bytes()


def test_status_consumes_the_shared_remediation_inspection_authority(tmp_path, monkeypatch):
    calls = []
    inspection = CredentialMigrationInspection(MigrationResult("not-needed"))

    def inspect(root):
        calls.append(root)
        return inspection

    monkeypatch.setattr(credential_workflow, "inspect_credential_migration", inspect)

    result = run_credential_workflow(tmp_path, "status")

    assert calls == [tmp_path]
    assert result["migration_state"] == inspection.result.state


def test_scan_and_status_share_the_same_typed_snapshot_authority(tmp_path, monkeypatch):
    calls = []
    inspection = CredentialMigrationInspection(
        MigrationResult("partial", active_residual_state="unrevoked-or-unclassified"),
        values={"TODOIST_API_KEY": "synthetic-shared-snapshot"},
    )

    def inspect(root):
        calls.append(root)
        return inspection

    monkeypatch.setattr(credential_workflow, "inspect_credential_migration", inspect)
    monkeypatch.setattr(credential_workflow, "scan_credentials", lambda *_: type(
        "Report",
        (),
        {"findings": (), "inspected_scopes": (), "uninspected_scopes": (), "uninspected_reasons": ()},
    )())

    assert run_credential_workflow(tmp_path, "scan")["findings"] == 0
    assert run_credential_workflow(tmp_path, "status")["migration_state"] == "partial"
    assert calls == [tmp_path, tmp_path]


def _reference_vault(root: Path) -> None:
    config = root / "System/integrations/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"todoist:\n  enabled: true\n  api_key_env_var: TODOIST_API_KEY\n")


@pytest.mark.parametrize("action", ["status", "scan", "migrate"])
def test_cli_refuses_malformed_config_yaml_without_crashing(tmp_path, capsys, action):
    """A syntactically-broken config.yaml raises yaml.YAMLError (not a ValueError) deep in
    the parse. The reachable CLI must emit the structured {"status": "refused"} rather than
    crash with a traceback."""
    config = tmp_path / "System/integrations/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"todoist:\n  api_key_env_var: [unbalanced\n : : :\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    exit_code = credential_workflow.main([action, "--vault", str(tmp_path)])

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "refused"
    assert payload["action"] == action


@pytest.mark.parametrize("env_present", [False, True])
def test_scan_echoes_uninspected_worktree_for_unparseable_mcp(tmp_path, env_present):
    """Honesty symmetry with status/migrate: when the shared inspection could not classify
    a scope (an unparseable .mcp.json), scan must surface the same uninspected scope so a
    needle-clean scan is never read as a clean verdict. Covers both the empty-needle branch
    (no .env) and the report branch (a .env supplies needles)."""
    _reference_vault(tmp_path)
    (tmp_path / ".mcp.json").write_text('{ not valid json "TODOIST_API_KEY": rawsecret ')
    if env_present:
        (tmp_path / ".env").write_text('TODOIST_API_KEY="current-live-key"\n')
        (tmp_path / ".env").chmod(0o600)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    scan = run_credential_workflow(tmp_path, "scan")

    assert "worktree" in scan["uninspected_scopes"]
    assert "unparseable-active-config" in scan["uninspected_reasons"]
