"""Reachable structured CLI for credential scan, migration, status, and rewind."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

import yaml

from core.utils.credential_remediation import (
    CredentialEvidence,
    MigrationResult,
    inspect_credential_migration,
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


def _ordered_union(first: tuple[str, ...], second: tuple[str, ...]) -> list[str]:
    merged = list(first)
    for item in second:
        if item not in merged:
            merged.append(item)
    return merged


def _scan(vault_root: Path) -> dict[str, object]:
    needles: set[bytes] = set()
    inspection = inspect_credential_migration(vault_root)
    if inspection.config_raw is not None and len(inspection.config_raw) > DEFAULT_MAX_YAML_BYTES:
        raise ValueError("integration config exceeds scan bound")
    if inspection.config_raw is not None and inspection.values is None:
        raise ValueError("integration config could not be inspected safely")
    # Worktree scopes the shared inspection could not classify (e.g. an unparseable
    # .mcp.json) must surface in scan too, so a needle-clean scan is never read as a clean
    # verdict when a scope was actually uninspected.
    config_uninspected_scopes = tuple(inspection.result.uninspected_scopes)
    config_uninspected_reasons = tuple(inspection.result.uninspected_reasons)
    needles.update(value.encode("utf-8") for value in (inspection.values or {}).values())
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
            "uninspected_scopes": list(config_uninspected_scopes),
            "uninspected_reasons": list(config_uninspected_reasons),
            "env_authority": authority_json,
        }
    report = scan_credentials(vault_root, tuple(sorted(needles)))
    return {
        "findings": len(report.findings),
        "finding_ids": [finding.opaque_id for finding in report.findings],
        "finding_scopes": [finding.scope for finding in report.findings],
        "inspected_scopes": list(report.inspected_scopes),
        "uninspected_scopes": _ordered_union(report.uninspected_scopes, config_uninspected_scopes),
        "uninspected_reasons": _ordered_union(report.uninspected_reasons, config_uninspected_reasons),
        "env_authority": authority_json,
    }


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
    migration = inspect_credential_migration(vault_root).result
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
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as error:
        # yaml.YAMLError (broken config.yaml) is not a ValueError; catch it so the CLI
        # emits the structured {"status": "refused"} instead of crashing with a traceback.
        print(json.dumps({"action": args.action, "error": type(error).__name__, "status": "refused"}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 2 if result.get("migration_state") == "refused" else 0


if __name__ == "__main__":
    raise SystemExit(main())
