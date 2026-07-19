"""Reachable structured CLI for credential scan, migration, status, and rewind."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from core.utils.credential_remediation import (
    CredentialEvidence,
    MigrationResult,
    _active_mcp_raw_residual,
    _legacy_values,
    migrate_legacy_credentials,
    render_credential_status,
    rewind_credential_migration,
)
from core.utils.credential_scanner import scan_credentials
from core.utils.integration_credentials import inspect_vault_env_authority, read_vault_env
from core.utils.strict_yaml import DEFAULT_MAX_YAML_BYTES

WorkflowAction = Literal["scan", "migrate", "status", "rewind"]


def _migration_json(result: MigrationResult) -> dict[str, object]:
    return {
        "migration_state": result.state,
        "journal_id": result.journal_id,
        "failed_capabilities": list(result.failed_capabilities),
        "active_residual_state": result.active_residual_state,
        "uninspected_scopes": list(result.uninspected_scopes),
        "uninspected_reasons": list(result.uninspected_reasons),
    }


def _scan(vault_root: Path) -> dict[str, object]:
    needles: set[bytes] = set()
    config = vault_root / "System/integrations/config.yaml"
    if config.exists():
        raw = config.read_bytes()
        if len(raw) > DEFAULT_MAX_YAML_BYTES:
            raise ValueError("integration config exceeds scan bound")
        values, _, _ = _legacy_values(raw)
        needles.update(value.encode("utf-8") for value in values.values())
    try:
        needles.update(value.encode("utf-8") for value in read_vault_env(vault_root).values())
    except (OSError, UnicodeDecodeError, ValueError):
        pass
    env_authority = inspect_vault_env_authority(vault_root)
    authority_json = {
        "valid": env_authority.valid,
        "reason": env_authority.reason,
        "repair": env_authority.repair,
    }
    if not needles:
        return {
            "findings": 0,
            "inspected_scopes": [],
            "uninspected_scopes": [],
            "uninspected_reasons": [],
            "env_authority": authority_json,
        }
    report = scan_credentials(vault_root, tuple(sorted(needles)))
    return {
        "findings": len(report.findings),
        "finding_ids": [finding.opaque_id for finding in report.findings],
        "finding_scopes": [finding.scope for finding in report.findings],
        "inspected_scopes": list(report.inspected_scopes),
        "uninspected_scopes": list(report.uninspected_scopes),
        "uninspected_reasons": list(report.uninspected_reasons),
        "env_authority": authority_json,
    }


def _inspect_migration(vault_root: Path) -> MigrationResult:
    """Derive a conservative read-only migration state without writing."""
    config = vault_root / "System/integrations/config.yaml"
    if not config.exists():
        return MigrationResult("not-needed")
    raw = config.read_bytes()
    values, _, env_names = _legacy_values(raw)
    from core.utils.integration_credentials import inspect_active_mcp_config

    mcp = inspect_active_mcp_config(vault_root)
    if not mcp.inspected:
        return MigrationResult(
            "partial" if not values else "refused",
            active_residual_state="unrevoked-or-unclassified",
            uninspected_scopes=("worktree",),
            uninspected_reasons=(mcp.reason or "unsafe-active-config",),
        )
    residual = _active_mcp_raw_residual(mcp.data or b"", env_names, values)
    if values:
        return MigrationResult("refused", active_residual_state="unrevoked-or-unclassified" if residual else "none")
    return MigrationResult(
        "partial" if residual else "not-needed",
        active_residual_state="unrevoked-or-unclassified" if residual else "none",
    )


def run_credential_workflow(
    vault_root: Path,
    action: WorkflowAction,
    *,
    journal_id: str | None = None,
) -> dict[str, object]:
    """Run one bounded workflow action and return only redacted structured data."""
    if action == "scan":
        return {"action": action, **_scan(vault_root)}
    if action == "migrate":
        return {"action": action, **_migration_json(migrate_legacy_credentials(vault_root))}
    if action == "rewind":
        if journal_id is None:
            raise ValueError("rewind requires a journal id")
        return {"action": action, **_migration_json(rewind_credential_migration(vault_root, journal_id))}
    migration = _inspect_migration(vault_root)
    active = migration.active_residual_state
    security = "rotation-pending" if active == "unrevoked-or-unclassified" else "unknown"
    evidence = (
        CredentialEvidence()
        if security == "rotation-pending"
        else CredentialEvidence(unavailable=("provider-evidence",), unknown_causes=("unavailable",))
    )
    copy = render_credential_status(
        migration.state,
        security,
        active,
        "history-scope-unknown",
        evidence,
        ("primary-object-db",),
    )
    return {"action": action, **_migration_json(migration), "copy": copy.__dict__}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("scan", "migrate", "status", "rewind"))
    parser.add_argument("--vault", type=Path, default=Path.cwd())
    parser.add_argument("--journal-id")
    args = parser.parse_args(argv)
    try:
        result = run_credential_workflow(args.vault, args.action, journal_id=args.journal_id)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(json.dumps({"action": args.action, "error": type(error).__name__, "status": "refused"}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 2 if result.get("migration_state") == "refused" else 0


if __name__ == "__main__":
    raise SystemExit(main())
