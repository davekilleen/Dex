#!/usr/bin/env python3
"""Collect an honest, machine-readable health report for Dex."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import plistlib
import py_compile
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core import paths, portable_contract
from core.lifecycle import engine as lifecycle_engine
from core.lifecycle import ledger as lifecycle_ledger
from core.lifecycle import service as lifecycle_service
from core.lifecycle.catalog import CatalogError, load_catalog
from core.lifecycle.inventory import build_inventory
from core.lifecycle.model import ITEM_ID, SEMVER, AdoptionState
from core.lifecycle.plan import PlannedAction, ReasonCode, build_adoption_plan
from core.transaction.engine import TX_ROOT_RELATIVE, PlanEntry, PlanRejected
from core.transaction.journal import Journal, JournalCorruptError
from core.utils import dex_logger, launch_agents, preflight, release_channel

VERDICTS = frozenset({"OK", "OFF", "BROKEN", "UNKNOWN"})
DOCTOR_GIT_CANDIDATES = (Path("/usr/bin/git"), Path("/bin/git"))
MISSING_PACKAGES_DETAIL = (
    "Python packages not installed — run /dex-update (or pip install -r requirements.txt) "
    "then re-run /dex-doctor"
)
RELEASE_CATALOG_PATH = "System/.release-catalog.json"
KNOWN_SKILL_CONTAINER_DIRECTORIES = frozenset({"_available", "integrations"})
ADOPTION_REPORT_VERSION = 1
ADOPTION_GROUP_IDS = (
    "new-and-safe",
    "needs-your-review",
    "preserved-for-now",
    "continue-or-recover",
    "receipts-and-rewind",
)
ADOPTION_ACTIONS = frozenset(action.value for action in PlannedAction)
ADOPTION_STATUSES = frozenset(state.value for state in AdoptionState)
ADOPTION_REASON_CODES = frozenset(reason.value for reason in ReasonCode)
INSTALLER_STRIPPED_PACKAGE_SCRIPTS = {
    "test:hooks": "node --test .claude/hooks/tests/*.test.cjs",
    "test:scripts": (
        "node --test .scripts/lib/tests/*.test.cjs "
        ".scripts/meeting-intel/__tests__/*.test.cjs"
    ),
    "test:integrations": (
        "node --test core/integrations/connection-manager/*.test.cjs"
    ),
    "check:connections-contract": (
        "node scripts/check-connections-contract.mjs && "
        "node scripts/build-connections-engine-manifest.mjs --check"
    ),
    "test:connections-consumer-smoke": (
        "node --test "
        "core/integrations/connection-manager/connections-contract.test.cjs"
    ),
}


def _validate_authority_item(item_id: object, item_version: object) -> None:
    if not isinstance(item_id, str) or ITEM_ID.fullmatch(item_id) is None:
        raise ValueError("Adoption authority item_id is not canonical")
    if item_version is not None and (
        not isinstance(item_version, str) or SEMVER.fullmatch(item_version) is None
    ):
        raise ValueError("Adoption authority item_version is not strict SemVer")


def _validate_surface(surface: object) -> None:
    if not isinstance(surface, str) or not surface.strip():
        raise ValueError("Adoption group surface must be a non-empty string")


@dataclass(frozen=True)
class CheckDefinition:
    """A stable registry entry for one collector probe."""

    id: str
    feature: str
    probe: str


@dataclass(frozen=True)
class Heal:
    """A safe-heal result or a higher-tier suggestion."""

    tier: int
    action: str
    applied: bool = False


@dataclass(frozen=True)
class ProbeResult:
    """The normalized outcome of one probe."""

    verdict: str
    detail: str
    heal: Heal | None = None
    feature_status: str | None = None
    user_message: str | None = None
    structured_detail: dict[str, object] | None = None

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"Invalid doctor verdict: {self.verdict}")
        if self.feature_status is not None and self.feature_status not in {
            "ok",
            "off",
            "not_installed",
            "broken",
            "unknown",
        }:
            raise ValueError(f"Invalid feature status: {self.feature_status}")
        if self.structured_detail is not None and not isinstance(
            self.structured_detail,
            dict,
        ):
            raise TypeError("ProbeResult structured_detail must be a dict or null")


@dataclass(frozen=True)
class DoctorContext:
    """Filesystem and clock inputs for deterministic collector runs."""

    vault_root: Path
    repo_root: Path
    home: Path
    now: datetime

    @classmethod
    def from_environment(cls) -> "DoctorContext":
        return cls(
            vault_root=paths.VAULT_ROOT.resolve(),
            repo_root=paths.VAULT_ROOT.resolve(),
            home=Path.home(),
            now=datetime.now(timezone.utc),
        )

    def core_path(self, constant_name: str) -> Path:
        """Retarget a core.paths constant to this context's vault root."""
        configured = getattr(paths, constant_name)
        relative = configured.relative_to(paths.VAULT_ROOT)
        return self.vault_root / relative

    @property
    def last_run_path(self) -> Path:
        return self.core_path("SYSTEM_DIR") / ".doctor-last-run.json"

    @property
    def paths_json_path(self) -> Path:
        return self.repo_root / "core" / "paths.json"

    @property
    def launch_agents_dir(self) -> Path:
        return self.home / "Library" / "LaunchAgents"


@dataclass(frozen=True)
class AdoptionItem:
    """One catalog item and its planner-owned action."""

    item_id: str
    item_version: str | None
    action: str

    def __post_init__(self) -> None:
        _validate_authority_item(self.item_id, self.item_version)
        if self.action not in ADOPTION_ACTIONS:
            raise ValueError(f"Invalid adoption authority action: {self.action!r}")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AdoptionReviewFile:
    """One conflict path and the planner-owned reason for reviewing it."""

    path: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise ValueError("Adoption review path must be a non-empty string")
        if self.reason not in ADOPTION_REASON_CODES:
            raise ValueError(f"Invalid adoption review reason: {self.reason!r}")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class AdoptionReviewItem:
    """One conflicted catalog item with item- and path-level reasons."""

    item_id: str
    item_version: str
    action: str
    reasons: tuple[str, ...]
    files: tuple[AdoptionReviewFile, ...]

    def __post_init__(self) -> None:
        _validate_authority_item(self.item_id, self.item_version)
        if self.action not in {
            PlannedAction.CONFLICT.value,
            PlannedAction.UNKNOWN.value,
        }:
            raise ValueError(f"Invalid review authority action: {self.action!r}")
        if (
            not isinstance(self.reasons, tuple)
            or not self.reasons
            or any(reason not in ADOPTION_REASON_CODES for reason in self.reasons)
        ):
            raise ValueError("Adoption review reasons use an invalid authority value")
        if not isinstance(self.files, tuple) or any(
            type(entry) is not AdoptionReviewFile for entry in self.files
        ):
            raise ValueError("Adoption review files must be AdoptionReviewFile records")

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "item_version": self.item_version,
            "action": self.action,
            "reasons": list(self.reasons),
            "files": [entry.to_dict() for entry in self.files],
        }


@dataclass(frozen=True)
class PreservedCustomization:
    """One customized installed file that adoption will preserve."""

    path: str
    state: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise ValueError("Preserved customization path must be a non-empty string")
        if self.state != "stock-modified":
            raise ValueError("Preserved customization state must be stock-modified")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("Preserved customization reason must be a non-empty string")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class InterruptedTransaction:
    """Read-only recovery evidence mirroring Transaction.resume classification."""

    tx_id: str
    verdict: str
    last_event: str | None
    snapshot_present: bool

    def __post_init__(self) -> None:
        if lifecycle_engine.TRANSACTION_ID.fullmatch(self.tx_id) is None:
            raise ValueError("Interrupted transaction id is not canonical")
        if self.verdict not in {"BROKEN", "UNKNOWN"}:
            raise ValueError(f"Invalid interrupted-transaction verdict: {self.verdict}")
        if self.last_event is not None and not isinstance(self.last_event, str):
            raise ValueError("Interrupted transaction last_event must be a string or null")
        if type(self.snapshot_present) is not bool:
            raise ValueError("Interrupted transaction snapshot_present must be a boolean")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LedgerRecovery:
    """A ledger error and the ledger-owned command that can repair its state."""

    verdict: str
    incomplete_publication: bool
    repair_command: str
    detail: str

    def __post_init__(self) -> None:
        if self.verdict != "UNKNOWN":
            raise ValueError(f"Invalid ledger recovery verdict: {self.verdict}")
        if type(self.incomplete_publication) is not bool:
            raise ValueError("Ledger incomplete_publication must be a boolean")
        if not isinstance(self.repair_command, str) or not self.repair_command:
            raise ValueError("Ledger repair_command must be a non-empty string")
        if not isinstance(self.detail, str) or not self.detail:
            raise ValueError("Ledger recovery detail must be a non-empty string")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AdoptionReceiptSummary:
    """Current ledger receipt authority plus snapshot-retention evidence."""

    item_id: str
    item_version: str
    status: str
    transaction_id: str
    when: str
    rewindable: bool
    rewind_verdict: str

    def __post_init__(self) -> None:
        _validate_authority_item(self.item_id, self.item_version)
        if self.status not in ADOPTION_STATUSES:
            raise ValueError(f"Invalid adoption receipt status: {self.status!r}")
        if lifecycle_engine.TRANSACTION_ID.fullmatch(self.transaction_id) is None:
            raise ValueError("Adoption receipt transaction_id is not canonical")
        if not isinstance(self.when, str) or not self.when:
            raise ValueError("Adoption receipt when must be a non-empty string")
        if type(self.rewindable) is not bool:
            raise ValueError("Adoption receipt rewindable must be a boolean")
        if self.rewind_verdict not in {"OK", "UNKNOWN"}:
            raise ValueError("Adoption receipt rewind_verdict must be OK or UNKNOWN")
        if self.rewindable and self.rewind_verdict != "OK":
            raise ValueError("A rewindable receipt must have rewind_verdict OK")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class NewAndSafeGroup:
    id: str
    verdict: str
    count: int
    items: tuple[AdoptionItem, ...]
    surface: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "verdict": self.verdict,
            "count": self.count,
            "items": [item.to_dict() for item in self.items],
            "surface": self.surface,
        }


@dataclass(frozen=True)
class NeedsReviewGroup:
    id: str
    verdict: str
    count: int
    items: tuple[AdoptionReviewItem, ...]
    surface: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "verdict": self.verdict,
            "count": self.count,
            "items": [item.to_dict() for item in self.items],
            "surface": self.surface,
        }


@dataclass(frozen=True)
class PreservedForNowGroup:
    id: str
    verdict: str
    count: int
    held_back_items: tuple[AdoptionItem, ...]
    customized_files: tuple[PreservedCustomization, ...]
    surface: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "verdict": self.verdict,
            "count": self.count,
            "held_back_items": [item.to_dict() for item in self.held_back_items],
            "customized_files": [entry.to_dict() for entry in self.customized_files],
            "surface": self.surface,
        }


@dataclass(frozen=True)
class ContinueOrRecoverGroup:
    id: str
    verdict: str
    count: int
    transactions: tuple[InterruptedTransaction, ...]
    ledger: LedgerRecovery | None
    inspection_error: str | None
    surface: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "verdict": self.verdict,
            "count": self.count,
            "transactions": [entry.to_dict() for entry in self.transactions],
            "ledger": self.ledger.to_dict() if self.ledger else None,
            "inspection_error": self.inspection_error,
            "surface": self.surface,
        }


@dataclass(frozen=True)
class ReceiptsAndRewindGroup:
    id: str
    verdict: str
    count: int
    receipts: tuple[AdoptionReceiptSummary, ...]
    surface: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "verdict": self.verdict,
            "count": self.count,
            "receipts": [entry.to_dict() for entry in self.receipts],
            "surface": self.surface,
        }


AdoptionGroup = (
    NewAndSafeGroup
    | NeedsReviewGroup
    | PreservedForNowGroup
    | ContinueOrRecoverGroup
    | ReceiptsAndRewindGroup
)


@dataclass(frozen=True)
class AdoptionReport:
    """Strict authority/surface contract for Doctor's adoption section.

    All item ids, actions, verdicts, counts, transaction ids, statuses, and
    rewindable booleans are deterministic authority emitted here. Renderers
    may paraphrase only each group's ``surface`` line; they must reproduce all
    other fields verbatim and must never infer, promote, or suppress actions.
    """

    report_version: int
    verdict: str
    groups: tuple[AdoptionGroup, ...]

    def __post_init__(self) -> None:
        if self.report_version != ADOPTION_REPORT_VERSION:
            raise ValueError("Unsupported adoption report version")
        if self.verdict not in VERDICTS:
            raise ValueError(f"Invalid adoption report verdict: {self.verdict}")
        if not isinstance(self.groups, tuple):
            raise ValueError("Adoption report groups must be a tuple")
        expected_types = (
            NewAndSafeGroup,
            NeedsReviewGroup,
            PreservedForNowGroup,
            ContinueOrRecoverGroup,
            ReceiptsAndRewindGroup,
        )
        if tuple(type(group) for group in self.groups) != expected_types:
            raise ValueError("Adoption report group types must match the exact contract")
        if tuple(group.id for group in self.groups) != ADOPTION_GROUP_IDS:
            raise ValueError("Adoption report must contain the exact five ordered groups")
        for group in self.groups:
            if group.verdict not in VERDICTS:
                raise ValueError(f"Invalid adoption group verdict: {group.verdict}")
            if type(group.count) is not int or group.count < 0:
                raise ValueError("Adoption group count must be a non-negative integer")
            _validate_surface(group.surface)
        new_group, review_group, preserved_group, recovery_group, receipt_group = self.groups
        if not isinstance(new_group.items, tuple) or any(
            type(item) is not AdoptionItem for item in new_group.items
        ):
            raise ValueError("new-and-safe items must be AdoptionItem records")
        if any(item.action != PlannedAction.ADOPT.value for item in new_group.items):
            raise ValueError("new-and-safe items must have action adopt")
        if not isinstance(review_group.items, tuple) or any(
            type(item) is not AdoptionReviewItem for item in review_group.items
        ):
            raise ValueError("needs-your-review items must be AdoptionReviewItem records")
        if not isinstance(preserved_group.held_back_items, tuple) or any(
            type(item) is not AdoptionItem for item in preserved_group.held_back_items
        ):
            raise ValueError("preserved held-back items must be AdoptionItem records")
        if any(
            item.action != PlannedAction.SKIP_HELD_BACK.value
            for item in preserved_group.held_back_items
        ):
            raise ValueError("preserved held-back items must have action skip-held-back")
        if not isinstance(preserved_group.customized_files, tuple) or any(
            type(item) is not PreservedCustomization
            for item in preserved_group.customized_files
        ):
            raise ValueError("preserved customized files must be strict authority records")
        if not isinstance(recovery_group.transactions, tuple) or any(
            type(item) is not InterruptedTransaction
            for item in recovery_group.transactions
        ):
            raise ValueError("recovery transactions must be strict authority records")
        if recovery_group.ledger is not None and type(recovery_group.ledger) is not LedgerRecovery:
            raise ValueError("recovery ledger must be a LedgerRecovery record or null")
        if recovery_group.inspection_error is not None and not isinstance(
            recovery_group.inspection_error, str
        ):
            raise ValueError("recovery inspection_error must be a string or null")
        if not isinstance(receipt_group.receipts, tuple) or any(
            type(item) is not AdoptionReceiptSummary for item in receipt_group.receipts
        ):
            raise ValueError("receipt summaries must be strict authority records")
        if any(
            item.status != AdoptionState.ADOPTED.value
            for item in receipt_group.receipts
        ):
            raise ValueError("receipt summaries must have status adopted")
        expected_counts = (
            len(new_group.items),
            len(review_group.items),
            len(preserved_group.held_back_items) + len(preserved_group.customized_files),
            len(recovery_group.transactions)
            + int(recovery_group.ledger is not None)
            + int(recovery_group.inspection_error is not None),
            len(receipt_group.receipts),
        )
        if tuple(group.count for group in self.groups) != expected_counts:
            raise ValueError("Adoption report group count does not match authority records")

    def to_dict(self) -> dict[str, object]:
        return {
            "report_version": self.report_version,
            "verdict": self.verdict,
            "groups": [group.to_dict() for group in self.groups],
        }


def canonical_adoption_report_bytes(report: AdoptionReport) -> bytes:
    """Return canonical JSON bytes for the strict Doctor adoption report."""
    if not isinstance(report, AdoptionReport):
        raise TypeError("report must be an AdoptionReport")
    return (
        json.dumps(
            report.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


PARA_PATH_NAMES = (
    "INBOX_DIR",
    "QUARTER_GOALS_DIR",
    "WEEK_PRIORITIES_DIR",
    "TASKS_DIR",
    "PROJECTS_DIR",
    "AREAS_DIR",
    "RESOURCES_DIR",
    "ARCHIVES_DIR",
)

# Background-job success contracts live in the health promise register
# (core/health/promises.py); .claude/hooks/session-start.sh mirrors it for the
# in-session staleness glance.

QUICK_CHECKS = (
    CheckDefinition("vault.structure", "Vault structure", "_probe_vault_structure"),
    CheckDefinition("vault.configs", "Vault configuration", "_probe_vault_configs"),
    CheckDefinition("vault.git", "Vault history", "_probe_vault_git"),
    CheckDefinition("brain.git", "Dex brain history", "_probe_brain_git"),
    CheckDefinition(
        "topology.pre-split-archive",
        "Pre-split undo archive",
        "_probe_pre_split_archive",
    ),
    CheckDefinition("vault.auto-commit", "Vault auto-commit", "_probe_vault_auto_commit"),
    CheckDefinition(
        "topology.migration-pending",
        "Brain/vault topology",
        "_probe_migration_pending",
    ),
    CheckDefinition("release.catalog", "Release catalog", "_probe_release_catalog"),
    CheckDefinition("adoption.plan", "Adoption plan", "_probe_adoption_plan"),
    CheckDefinition("smoke.history", "Nightly smoke results", "_probe_smoke_history"),
    CheckDefinition("mcp.registered", "MCP registration", "_probe_mcp_registered"),
    CheckDefinition("mcp.orphans", "MCP server registration", "_probe_mcp_orphans"),
    CheckDefinition("python.env", "Python environment", "_probe_python_env"),
    CheckDefinition("hooks.wired", "Claude hooks", "_probe_hooks_wired"),
    CheckDefinition("jobs.loaded", "Background jobs", "_probe_jobs_loaded"),
    CheckDefinition("jobs.fresh", "Background job freshness", "_probe_jobs_fresh"),
    CheckDefinition("preflight.queue", "Preflight health", "_probe_preflight_queue"),
    CheckDefinition(
        "capabilities.rooms",
        "Capability rooms",
        "_probe_capability_rooms",
    ),
    CheckDefinition("entity.engine", "Entity engine", "_probe_entity_engine"),
    CheckDefinition(
        "customizations.skills",
        "Skill customizations",
        "_probe_customization_skills",
    ),
    CheckDefinition(
        "customizations.mcp",
        "MCP customizations",
        "_probe_customization_mcp",
    ),
    CheckDefinition("core.drift", "Shipped-file drift", "_probe_core_drift"),
    CheckDefinition("doctor.self", "Doctor instruments", "_probe_doctor_self"),
)

DEEP_CHECKS = (
    CheckDefinition(
        "customizations.assessment",
        "customization_assessment",
        "_probe_customization_assessment",
    ),
    CheckDefinition(
        "customizations.migration-status",
        "customization_migration_status",
        "_probe_customization_migration_status",
    ),
    CheckDefinition("granola.query_path", "Granola meeting sync", "_probe_granola_query_path"),
    CheckDefinition("pipedrive.connection", "Pipedrive CRM", "_probe_pipedrive_connection"),
    CheckDefinition("config.meeting_sources", "Configured meeting source", "_probe_meeting_sources"),
    CheckDefinition("update.post-canary", "Post-update canary", "_probe_post_update_canary"),
    CheckDefinition("calendar.access", "Calendar access", "_probe_calendar_access"),
    CheckDefinition("qmd.live", "Semantic search", "_probe_qmd_live"),
    CheckDefinition("integrations.enabled", "Enabled integrations", "_probe_integrations_enabled"),
    CheckDefinition("mcp.importable", "MCP imports", "_probe_mcp_importable"),
    CheckDefinition("smoke.journeys", "End-to-end smoke journeys", "_probe_smoke_journeys"),
    CheckDefinition("backup.freshness", "Vault backups", "_probe_backup_freshness"),
)


def _one_line(value: object) -> str:
    return " ".join(str(value).split()) or value.__class__.__name__


def _format_archive_size(size_bytes: int) -> str:
    """Return archive sizes in a compact, human-readable unit."""
    for unit, divisor in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size_bytes >= divisor:
            return f"{size_bytes / divisor:.1f} {unit}"
    return f"{size_bytes / 1024:.1f} KB"


def _sentence(value: object) -> str:
    detail = _one_line(value)
    if detail[-1] not in ".?!":
        detail += "."
    return detail


def _actionable_probe_error(error: Exception) -> str:
    detail = _one_line(error)
    if _is_missing_package_error(error, detail):
        return MISSING_PACKAGES_DETAIL
    return detail


def _is_missing_package_error(value: object, detail: str | None = None) -> bool:
    rendered = detail or _one_line(value)
    return isinstance(value, ModuleNotFoundError) or any(
        marker in rendered for marker in ("ModuleNotFoundError", "No module named")
    )


def _load_yaml(path: Path) -> object:
    """Load YAML lazily so a broken venv can still produce a doctor report."""
    from core.utils.strict_yaml import load_yaml_path

    return load_yaml_path(path)


def _result_json(definition: CheckDefinition, result: ProbeResult) -> dict[str, Any]:
    rendered = {
        "id": definition.id,
        "feature": definition.feature,
        "verdict": result.verdict,
        "detail": _sentence(result.detail),
        "heal": asdict(result.heal) if result.heal else None,
    }
    if result.feature_status is not None:
        rendered["feature_status"] = result.feature_status
    if result.user_message is not None:
        rendered["user_message"] = result.user_message
    return rendered


def _summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        verdict.lower(): sum(check["verdict"] == verdict for check in checks)
        for verdict in ("OK", "OFF", "BROKEN", "UNKNOWN")
    }


def _repair_count_word(count: int) -> str:
    return {1: "one", 2: "two", 3: "three"}.get(count, str(count))


def _paths_export_for(context: DoctorContext) -> dict[str, str]:
    """Reuse core.paths' export and retarget it for an injected test vault."""
    exported = paths.export_json()
    retargeted: dict[str, str] = {}
    for name, raw_path in exported.items():
        configured = Path(raw_path)
        try:
            relative = configured.relative_to(paths.VAULT_ROOT)
        except ValueError:
            retargeted[name] = raw_path
        else:
            retargeted[name] = str(context.vault_root / relative)
    return retargeted


def _repo_shipped_executables(context: DoctorContext) -> list[Path]:
    """Return files marked executable in the repository's Git index."""
    result = subprocess.run(
        ["git", "-C", str(context.repo_root), "ls-files", "--stage", "-z"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git could not inspect shipped script modes")

    executable_paths = []
    for record in result.stdout.split("\0"):
        if not record or "\t" not in record:
            continue
        metadata, relative = record.split("\t", 1)
        mode = metadata.split(" ", 1)[0]
        if mode == "100755":
            executable_paths.append(context.repo_root / relative)
    return executable_paths


def _requeue_entity_dead_letters(context: DoctorContext) -> dict[str, Any]:
    """Run the bridge-owned dead-letter heal under its pending-store lock."""
    node = shutil.which("node")
    if not node:
        raise FileNotFoundError("node is required to re-queue entity writes")
    client = context.repo_root / ".scripts" / "lib" / "entity-engine-client.cjs"
    if not client.is_file():
        raise FileNotFoundError(f"entity bridge is missing: {client}")
    source = (
        "const client=require(process.argv[1]);"
        "const result=client.requeueDeadLetters(process.argv[2]);"
        "process.stdout.write(JSON.stringify(result));"
    )
    result = subprocess.run(
        [node, "-e", source, str(client), str(context.vault_root)],
        cwd=context.repo_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(context.vault_root),
            "VAULT_PATH": str(context.vault_root),
        },
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "entity dead-letter heal failed")
    parsed = json.loads(result.stdout)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("requeued"), int):
        raise ValueError("entity dead-letter heal returned invalid output")
    return parsed


def _tighten_env_permissions(context: DoctorContext) -> None:
    """chmod the vault .env to 0600 through a no-follow descriptor.

    Metadata-only: no bytes are ever read from the file. The descriptor-based
    re-verification (regular file, owned by us) closes the lstat→chmod race a
    path-based ``os.chmod`` would leave open — a symlink swapped in between
    would otherwise be followed to an arbitrary target.
    """
    descriptor = os.open(
        context.vault_root / ".env",
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(".env changed identity during the permission repair")
        if hasattr(os, "geteuid") and opened.st_uid != os.geteuid():
            raise OSError(".env is owned by another user")
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def _apply_t1_heals(context: DoctorContext) -> tuple[dict[str, list[str]], list[str]]:
    """Preview and apply contract-authorized Tier-1 repairs through the service.

    Returns applied actions keyed by the check id they belong to — routing on
    check id, never on the human wording of an action string — plus errors.
    """
    actions: dict[str, list[str]] = {}
    errors: list[str] = []
    planned: list[PlanEntry] = []
    planned_paths_export = False
    planned_executables: list[str] = []

    missing_directories = [context.core_path(name) for name in PARA_PATH_NAMES if not context.core_path(name).is_dir()]
    if missing_directories:
        names = ", ".join(directory.name for directory in missing_directories)
        errors.append(
            "Directory repair requires user action because empty directories are not "
            f"receipt-declared transaction writes: {names}"
        )

    try:
        expected_paths = _paths_export_for(context)
        current_paths: object = None
        try:
            current_paths = json.loads(context.paths_json_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        if current_paths != expected_paths:
            relative = context.paths_json_path.relative_to(context.vault_root).as_posix()
            mode = (
                context.paths_json_path.stat().st_mode & 0o777
                if context.paths_json_path.is_file()
                else 0o644
            )
            planned.append(
                PlanEntry(
                    relative,
                    (json.dumps(expected_paths, indent=2) + "\n").encode("utf-8"),
                    mode=mode,
                )
            )
            planned_paths_export = True
    except Exception as error:
        errors.append(f"Path-export heal failed: {_one_line(error)}")

    try:
        shipped_executables = _repo_shipped_executables(context)
    except Exception as error:
        errors.append(f"Executable-mode heal failed: {_one_line(error)}")
        shipped_executables = []
    for script in shipped_executables:
        try:
            if not script.is_file() or script.stat().st_mode & 0o111:
                continue
            try:
                relative = script.relative_to(context.vault_root).as_posix()
            except ValueError:
                errors.append(
                    f"Executable-mode repair requires user action outside the vault: {script}"
                )
                continue
            planned.append(
                PlanEntry(
                    relative,
                    script.read_bytes(),
                    mode=(script.stat().st_mode & 0o777) | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH,
                )
            )
            planned_executables.append(relative)
        except OSError as error:
            errors.append(f"Executable-mode heal failed for {script}: {_one_line(error)}")

    try:
        finding = _env_permission_finding(context)
        if finding is not None and finding.auto_tighten:
            # Metadata-only repair: never reads, copies, or snapshots the
            # secrets inside .env — it only removes group/other access.
            # Findings that cannot be auto-tightened (foreign owner, symlink)
            # carry their own Tier-3 guidance and are never attempted here.
            _tighten_env_permissions(context)
            actions.setdefault("vault.configs", []).append(
                "tightened .env to owner-only permissions"
            )
    except OSError as error:
        errors.append(f".env permission heal failed: {_one_line(error)}")

    dead_letter_path = context.vault_root / "System" / ".dex" / "entity-dead-letter.jsonl"
    if dead_letter_path.exists():
        try:
            healed = _requeue_entity_dead_letters(context)
            requeued = healed["requeued"]
            if requeued:
                noun = "write" if requeued == 1 else "writes"
                actions.setdefault("entity.engine", []).append(
                    f"re-queued {requeued} dead-lettered entity {noun} with retry counters reset"
                )
        except Exception as error:
            errors.append(f"Entity-write heal failed: {_one_line(error)}")

    try:
        acknowledged = _acknowledge_resolved_preflight_errors(context)
        if acknowledged:
            noun = "error" if acknowledged == 1 else "errors"
            actions.setdefault("preflight.queue", []).append(
                f"acknowledged {acknowledged} resolved preflight {noun}"
            )
    except Exception as error:
        errors.append(f"Preflight-queue heal failed: {_one_line(error)}")

    try:
        room_health = _probe_capability_rooms(context)
        if (
            room_health.verdict == "BROKEN"
            and room_health.heal is not None
            and room_health.heal.tier == 1
        ):
            from core import capabilities

            reconciled = capabilities.reconcile_all(
                context.vault_root,
                profile_path=context.vault_root / "System/user-profile.yaml",
            )
            if any(result.get("user_content_deleted") is not False for result in reconciled):
                raise RuntimeError("capability reconciliation did not preserve user content")
            actions.setdefault("capabilities.rooms", []).append(
                "reconciled capability room assets without deleting user content"
            )
    except Exception as error:
        errors.append(f"Capability-room heal failed: {_one_line(error)}")

    if planned:
        try:
            preview = lifecycle_service._preview_transaction(
                context.vault_root,
                planned,
                purpose="doctor-tier-1",
            )
            lifecycle_service._execute_approved_transaction(
                context.vault_root,
                planned,
                purpose="doctor-tier-1",
                approved_token=str(preview["approval_token"]),
            )
        except Exception as error:
            errors.append(f"Tier-1 transaction failed: {_one_line(error)}")
        else:
            if planned_paths_export:
                actions.setdefault("vault.structure", []).append("regenerated core/paths.json")
            if planned_executables:
                noun = "permission" if len(planned_executables) == 1 else "permissions"
                actions.setdefault("vault.structure", []).append(
                    f"restored executable {noun} on {', '.join(planned_executables)}"
                )

    return actions, errors


def _write_last_run(report: dict[str, Any], context: DoctorContext) -> None:
    relative = context.last_run_path.relative_to(context.vault_root).as_posix()
    plan = [
        PlanEntry(
            relative,
            (json.dumps(report, indent=2) + "\n").encode("utf-8"),
            mode=0o600,
        )
    ]
    preview = lifecycle_service._preview_transaction(
        context.vault_root,
        plan,
        purpose="doctor-report",
    )
    lifecycle_service._execute_approved_transaction(
        context.vault_root,
        plan,
        purpose="doctor-report",
        approved_token=str(preview["approval_token"]),
    )


def collect(
    *,
    deep: bool = False,
    heal: bool = False,
    context: DoctorContext | None = None,
) -> dict[str, Any]:
    """Run the selected registry and return its JSON-serializable report."""
    context = context or DoctorContext.from_environment()
    definitions = [*QUICK_CHECKS, *DEEP_CHECKS] if deep else list(QUICK_CHECKS)
    results: dict[str, ProbeResult] = {}
    failed: list[dict[str, str]] = []

    t1_actions: dict[str, list[str]] = {}
    if heal:
        try:
            t1_actions, t1_errors = _apply_t1_heals(context)
            if t1_errors:
                failed.append({"id": "doctor.self", "error": "; ".join(t1_errors)})
        except Exception as error:
            failed.append({"id": "doctor.self", "error": _one_line(error)})

    # One classification pass over ~/Library/LaunchAgents is shared by
    # jobs.loaded and jobs.fresh instead of re-parsing every plist twice.
    _begin_launch_agent_scan_scope(context)
    try:
        for definition in definitions:
            if definition.id == "doctor.self":
                continue
            try:
                result = globals()[definition.probe](context)
            except Exception as error:
                error_text = _actionable_probe_error(error)
                failed.append({"id": definition.id, "error": error_text})
                result = ProbeResult(
                    "UNKNOWN",
                    error_text
                    if error_text == MISSING_PACKAGES_DETAIL
                    else f"The {definition.feature} probe could not run: {error_text}",
                )
            if result.verdict == "UNKNOWN" and _is_missing_package_error(result.detail):
                result = ProbeResult("UNKNOWN", MISSING_PACKAGES_DETAIL, result.heal)
            check_actions = t1_actions.get(definition.id, [])
            if definition.id == "vault.structure" and check_actions:
                action = "; ".join(check_actions) + "."
                if result.verdict == "OK":
                    repair_word = _repair_count_word(len(check_actions))
                    repair_noun = "repair" if len(check_actions) == 1 else "repairs"
                    detail = f"All standard PARA directories exist after {repair_word} safe {repair_noun}"
                else:
                    detail = f"{result.detail.rstrip('.')} while safe Tier-1 repairs were also applied"
                result = replace(
                    result,
                    detail=detail,
                    heal=Heal(tier=1, action=action, applied=True),
                )
            if definition.id == "entity.engine" and check_actions:
                result = replace(
                    result,
                    heal=Heal(tier=1, action="; ".join(check_actions) + ".", applied=True),
                )
            if definition.id == "preflight.queue" and check_actions:
                result = replace(
                    result,
                    detail=f"{result.detail.rstrip('.')} after a safe Tier-1 queue repair",
                    heal=Heal(tier=1, action="; ".join(check_actions) + ".", applied=True),
                )
            if definition.id == "vault.configs" and check_actions:
                # Merge, never replace: when the probe is still BROKEN (a
                # parse failure, or a symlink/foreign-owner .env finding),
                # its verdict and actionable heal must survive — the applied
                # env repair is only appended as extra detail.
                if result.verdict == "OK" and result.heal is None:
                    result = replace(
                        result,
                        detail=f"{result.detail.rstrip('.')} after a safe Tier-1 permission repair",
                        heal=Heal(tier=1, action="; ".join(check_actions) + ".", applied=True),
                    )
                else:
                    result = replace(
                        result,
                        detail=(
                            f"{result.detail.rstrip('.')}; a safe Tier-1 repair separately "
                            + "; ".join(check_actions)
                        ),
                    )
            if definition.id == "capabilities.rooms" and check_actions:
                result = replace(
                    result,
                    detail=f"{result.detail.rstrip('.')} after a safe Tier-1 reconciliation",
                    heal=Heal(tier=1, action="; ".join(check_actions) + ".", applied=True),
                )
            results[definition.id] = result
    finally:
        _end_launch_agent_scan_scope(context)

    if failed:
        failed_ids = ", ".join(failure["id"] for failure in failed)
        self_result = ProbeResult(
            "BROKEN",
            f"The doctor could not complete these instruments: {failed_ids}",
        )
    else:
        self_result = ProbeResult(
            "OK",
            f"All {len(definitions)} probes completed and the last-run report target is writable",
        )
    results["doctor.self"] = self_result

    checks = [_result_json(definition, results[definition.id]) for definition in definitions]
    adoption = collect_adoption_report(context)
    report = {
        "generated_at": context.now.isoformat(),
        "mode": "deep" if deep else "quick",
        "instruments": {
            "attempted": len(definitions),
            "completed": len(definitions) - len(failed),
            "failed": failed,
        },
        "checks": checks,
        "summary": _summary(checks),
        "adoption": adoption.to_dict(),
    }
    if deep:
        assessment_result = results.get("customizations.assessment")
        if (
            assessment_result is not None
            and assessment_result.structured_detail is not None
        ):
            report["customization_assessment"] = assessment_result.structured_detail
        migration_status_result = results.get("customizations.migration-status")
        if (
            migration_status_result is not None
            and migration_status_result.structured_detail is not None
        ):
            report["customization_migration_status"] = (
                migration_status_result.structured_detail
            )

    try:
        _write_last_run(report, context)
    except Exception as error:
        error_text = _one_line(error)
        if not any(failure["id"] == "doctor.self" for failure in failed):
            failed.append({"id": "doctor.self", "error": error_text})
        report["instruments"] = {
            "attempted": len(definitions),
            "completed": len(definitions) - len(failed),
            "failed": failed,
        }
        results["doctor.self"] = ProbeResult(
            "BROKEN",
            f"The doctor could not write System/.doctor-last-run.json: {error_text}",
        )
        report["checks"] = [_result_json(definition, results[definition.id]) for definition in definitions]
        report["summary"] = _summary(report["checks"])

    return report


def collect_reporter(
    *,
    refresh_id: str,
    heal: bool = False,
    context: DoctorContext | None = None,
):
    """Collect the complete Doctor registry through the proactive reporter contract.

    This is an adapter, not a second collector.  The existing Doctor report is
    still written and remains the authority for detailed evidence and repairs;
    the returned envelope contains only normalized factual check results.
    """
    from core.health.doctor_reporter import from_doctor_report

    report = collect(deep=True, heal=heal, context=context)
    return from_doctor_report(report, refresh_id=refresh_id)


@contextmanager
def _vault_environment(context: DoctorContext) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in ("VAULT_PATH", "VAULT_ROOT")}
    os.environ["VAULT_PATH"] = str(context.vault_root)
    os.environ["VAULT_ROOT"] = str(context.vault_root)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _probe_vault_structure(context: DoctorContext) -> ProbeResult:
    missing = [context.core_path(name).name for name in PARA_PATH_NAMES if not context.core_path(name).is_dir()]
    if missing:
        return ProbeResult(
            "BROKEN",
            f"Missing standard PARA directories: {', '.join(missing)}",
            Heal(tier=1, action=f"Create the missing directories: {', '.join(missing)}.", applied=False),
        )
    return ProbeResult("OK", "All standard PARA directories exist")


@dataclass(frozen=True)
class EnvPermissionFinding:
    """One diagnosable problem with the vault-root .env's file authority."""

    detail: str
    heal: Heal
    auto_tighten: bool


def _env_permission_finding(context: DoctorContext) -> EnvPermissionFinding | None:
    """Classify a vault .env readable by other users; never reads its contents.

    Three shapes, matching how (and whether) the Tier-1 heal may act:
    - a regular file we own → Tier-1, auto-tightenable;
    - a regular file owned by another user → Tier-3 manual guidance (a chmod
      attempt would fail on every heal run and flip doctor.self BROKEN);
    - a symlink whose target is loose → Tier-3 manual guidance (Dex never
      chmods through a link, but every .env reader follows it, so staying
      silent would pass a world-readable key file as OK).
    """
    if os.name != "posix":
        return None
    env_path = context.vault_root / ".env"
    try:
        metadata = env_path.lstat()
    except OSError:
        return None
    if stat.S_ISLNK(metadata.st_mode):
        try:
            target = env_path.stat()
        except OSError:
            return None
        target_mode = stat.S_IMODE(target.st_mode)
        if not stat.S_ISREG(target.st_mode) or not target_mode & 0o077:
            return None
        try:
            resolved = env_path.resolve(strict=True)
        except OSError:
            return None
        return EnvPermissionFinding(
            detail=(
                f".env is a symlink whose target is readable by other users of this "
                f"machine (permissions {target_mode:03o}); Dex never auto-tightens "
                "through a link"
            ),
            heal=Heal(
                tier=3,
                action=f"Run: chmod 600 '{resolved}' (the symlink's real target).",
                applied=False,
            ),
            auto_tighten=False,
        )
    if not stat.S_ISREG(metadata.st_mode):
        return None
    mode = stat.S_IMODE(metadata.st_mode)
    if not mode & 0o077:
        return None
    if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
        return EnvPermissionFinding(
            detail=(
                f".env is readable by other users of this machine (permissions "
                f"{mode:03o}) and is owned by another user, so Dex cannot tighten it"
            ),
            heal=Heal(
                tier=3,
                action="As the file's owner, run: chmod 600 .env — and chown it to your user.",
                applied=False,
            ),
            auto_tighten=False,
        )
    return EnvPermissionFinding(
        detail=(
            f".env is readable by other users of this machine (permissions {mode:03o}; "
            "the API keys it holds belong in an owner-only file)"
        ),
        heal=Heal(tier=1, action="Tighten .env to owner-only permissions.", applied=False),
        auto_tighten=True,
    )


def _probe_vault_configs(context: DoctorContext) -> ProbeResult:
    config_files = (
        (context.core_path("USER_PROFILE_FILE"), "yaml"),
        (context.core_path("PILLARS_FILE"), "yaml"),
        (context.vault_root / ".claude" / "settings.json", "json"),
    )
    failures = []
    for config_path, kind in config_files:
        if not config_path.is_file():
            failures.append(f"{config_path.name} is missing")
            continue
        try:
            if kind == "yaml":
                parsed = _load_yaml(config_path)
            else:
                parsed = json.loads(config_path.read_text())
            if parsed is not None and not isinstance(parsed, dict):
                raise ValueError("top level must be an object")
        except ImportError:
            raise
        except Exception as error:
            failures.append(f"{config_path.name} could not be parsed ({_one_line(error)})")
    env_finding = _env_permission_finding(context)
    if failures:
        # The parse failures keep the Tier-3 hand-repair heal, but the
        # security finding must never be masked by an unrelated config
        # problem — report both in the same detail.
        detail = "; ".join(failures)
        if env_finding is not None:
            detail += f"; {env_finding.detail}"
        return ProbeResult(
            "BROKEN",
            detail,
            Heal(tier=3, action="Repair the named configuration file by hand.", applied=False),
        )
    if env_finding is not None:
        return ProbeResult("BROKEN", env_finding.detail, env_finding.heal)
    return ProbeResult("OK", "user-profile.yaml, pillars.yaml, and .claude/settings.json all parse")


def _release_catalog_path(context: DoctorContext) -> Path:
    return context.vault_root / RELEASE_CATALOG_PATH


def _empty_adoption_report(
    verdict: str,
    surface: str,
    *,
    transactions: tuple[InterruptedTransaction, ...] = (),
    ledger: LedgerRecovery | None = None,
    inspection_error: str | None = None,
) -> AdoptionReport:
    recovery_count = len(transactions) + int(ledger is not None) + int(inspection_error is not None)
    recovery_surface = (
        _recovery_surface(transactions, ledger, inspection_error)
        if recovery_count
        else surface
    )
    return AdoptionReport(
        ADOPTION_REPORT_VERSION,
        verdict,
        (
            NewAndSafeGroup("new-and-safe", verdict, 0, (), surface),
            NeedsReviewGroup("needs-your-review", verdict, 0, (), surface),
            PreservedForNowGroup("preserved-for-now", verdict, 0, (), (), surface),
            ContinueOrRecoverGroup(
                "continue-or-recover",
                verdict,
                recovery_count,
                transactions,
                ledger,
                inspection_error,
                recovery_surface,
            ),
            ReceiptsAndRewindGroup("receipts-and-rewind", verdict, 0, (), surface),
        ),
    )


def _inspect_interrupted_transactions(
    context: DoctorContext,
) -> tuple[tuple[InterruptedTransaction, ...], str | None]:
    """Classify transaction journals like ``Transaction.resume`` without resuming.

    This deliberately does not instantiate a mutating recovery flow or acquire
    the mutation lock. It only reads journals and snapshot-directory presence.
    """
    tx_root = context.vault_root / TX_ROOT_RELATIVE
    if not os.path.lexists(tx_root):
        return (), None
    if tx_root.is_symlink() or not tx_root.is_dir():
        return (), f"Transaction store is unsafe or not a directory: {tx_root}"

    interrupted: list[InterruptedTransaction] = []
    inspection_errors: list[str] = []
    try:
        candidates = sorted(tx_root.iterdir(), key=lambda candidate: candidate.name)
    except OSError as error:
        return (), f"Transaction store could not be inspected: {_one_line(error)}"
    for tx_dir in candidates:
        if lifecycle_engine.TRANSACTION_ID.fullmatch(tx_dir.name) is None:
            inspection_errors.append(
                f"Transaction store contains a non-canonical entry: {tx_dir.name}"
            )
            continue
        if tx_dir.is_symlink() or not tx_dir.is_dir():
            interrupted.append(
                InterruptedTransaction(tx_dir.name, "UNKNOWN", None, False)
            )
            continue
        try:
            entries = Journal(tx_dir / "journal.jsonl").read()
        except (JournalCorruptError, OSError):
            interrupted.append(
                InterruptedTransaction(
                    tx_dir.name,
                    "UNKNOWN",
                    None,
                    _safe_snapshot_present(tx_dir / "snapshot"),
                )
            )
            continue
        events = {entry.event for entry in entries}
        if not entries or "ROLLED-BACK" in events or "COMMITTED" in events:
            continue
        interrupted.append(
            InterruptedTransaction(
                tx_dir.name,
                "BROKEN",
                entries[-1].event,
                _safe_snapshot_present(tx_dir / "snapshot"),
            )
        )
    return tuple(interrupted), "; ".join(inspection_errors) or None


def _safe_snapshot_present(path: Path) -> bool:
    return not path.is_symlink() and path.is_dir()


def _receipt_rewind_evidence(
    context: DoctorContext,
    transaction_id: str,
    item_id: str,
) -> tuple[bool, str]:
    """Run the rewind engine's complete read-only eligibility preflight."""
    snapshot_root = context.vault_root / TX_ROOT_RELATIVE / transaction_id / "snapshot"
    if not os.path.lexists(snapshot_root):
        return False, "OK"
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        return False, "UNKNOWN"
    try:
        receipt = lifecycle_engine.load_adoption_receipt(
            context.vault_root,
            transaction_id,
        )
        if item_id not in receipt.items_adopted:
            return False, "UNKNOWN"
        current_modes, drifted = lifecycle_engine._current_adopted_modes(
            context.vault_root,
            receipt,
        )
        if drifted:
            return False, "UNKNOWN"
        lifecycle_engine._verify_adoption_commit(context.vault_root, receipt)
        lifecycle_engine._snapshot_rewind_plan(
            context.vault_root,
            receipt,
            current_modes,
        )
    except Exception:
        return False, "UNKNOWN"
    return True, "OK"


def _receipt_when(transaction_id: str) -> str:
    """Expose the transaction id's zone-less local timestamp without guessing a zone."""
    try:
        return datetime.strptime(transaction_id[:15], "%Y%m%dT%H%M%S").isoformat()
    except ValueError:
        return transaction_id[:15]


def _ledger_recovery(context: DoctorContext, error: Exception) -> LedgerRecovery:
    detail = _one_line(error)
    return LedgerRecovery(
        "UNKNOWN",
        "publication is incomplete" in detail,
        lifecycle_ledger._repair_command(context.vault_root),
        detail,
    )


def _recovery_surface(
    transactions: tuple[InterruptedTransaction, ...],
    ledger: LedgerRecovery | None,
    inspection_error: str | None,
) -> str:
    parts: list[str] = []
    if transactions:
        parts.append("I found an interrupted update — resume or undo?")
    if ledger is not None:
        parts.append(f"Ledger history is UNKNOWN; run {ledger.repair_command}.")
    if inspection_error is not None:
        parts.append("Transaction recovery evidence could not be checked safely.")
    return " ".join(parts) or "No interrupted update or ledger recovery is waiting."


def collect_adoption_report(context: DoctorContext) -> AdoptionReport:
    """Collect Doctor's deterministic five-group adoption section, read-only.

    This collector never resumes transactions, repairs ledger publication, or
    writes caches. Its authority/surface non-alteration contract is documented
    on :class:`AdoptionReport` and in ``docs/dex-doctor-spec.md``.
    """
    catalog_path = _release_catalog_path(context)
    if not os.path.lexists(catalog_path):
        return _empty_adoption_report(
            "OFF",
            "Adoption reporting is off because no release catalog is installed.",
        )

    transactions, inspection_error = _inspect_interrupted_transactions(context)
    try:
        catalog = load_catalog(catalog_path, release_root=context.vault_root)
    except (CatalogError, UnicodeError) as error:
        return _empty_adoption_report(
            "BROKEN",
            f"Adoption reporting is unavailable because the release catalog is invalid: {_one_line(error)}.",
            transactions=transactions,
            inspection_error=inspection_error,
        )
    except Exception as error:
        return _empty_adoption_report(
            "UNKNOWN",
            f"Adoption reporting could not inspect the release catalog: {_one_line(error)}.",
            transactions=transactions,
            inspection_error=inspection_error,
        )

    try:
        inventory = build_inventory(context.vault_root, catalog=catalog)
    except Exception as error:
        return _empty_adoption_report(
            "UNKNOWN",
            f"Adoption reporting could not build the read-only inventory: {_one_line(error)}.",
            transactions=transactions,
            inspection_error=inspection_error,
        )

    ledger_recovery: LedgerRecovery | None = None
    try:
        ledger_state = lifecycle_ledger.project_state(context.vault_root)
    except (lifecycle_ledger.LedgerError, OSError) as error:
        ledger_recovery = _ledger_recovery(context, error)
        return _empty_adoption_report(
            "UNKNOWN",
            "Adoption actions are withheld until lifecycle history is verified.",
            transactions=transactions,
            ledger=ledger_recovery,
            inspection_error=inspection_error,
        )
    except Exception as error:
        ledger_recovery = _ledger_recovery(context, error)
        return _empty_adoption_report(
            "UNKNOWN",
            "Adoption actions are withheld until lifecycle history is verified.",
            transactions=transactions,
            ledger=ledger_recovery,
            inspection_error=inspection_error,
        )

    catalog_ids = {item.id for item in catalog.items}
    adopted = ledger_state["adopted"]
    held_back = set(ledger_state["held_back"])
    assert isinstance(adopted, dict)
    try:
        plan = build_adoption_plan(
            catalog,
            inventory,
            adoption_states={
                item_id: AdoptionState.ADOPTED
                for item_id in adopted
                if item_id in catalog_ids
            },
            held_back=frozenset(held_back & catalog_ids),
        )
    except Exception as error:
        return _empty_adoption_report(
            "UNKNOWN",
            f"Adoption actions are withheld because the plan is UNKNOWN: {_one_line(error)}.",
            transactions=transactions,
            inspection_error=inspection_error,
        )

    new_items = tuple(
        AdoptionItem(item.item_id, item.item_version, item.action.value)
        for item in plan.items
        if item.action is PlannedAction.ADOPT
    )
    review_items = tuple(
        AdoptionReviewItem(
            item.item_id,
            item.item_version,
            item.action.value,
            tuple(reason.code.value for reason in item.reasons),
            tuple(
                AdoptionReviewFile(path, reason.code.value)
                for reason in item.reasons
                for path in reason.paths
            ),
        )
        for item in plan.items
        if item.action in {PlannedAction.CONFLICT, PlannedAction.UNKNOWN}
    )
    held_items = tuple(
        AdoptionItem(item.item_id, item.item_version, item.action.value)
        for item in plan.items
        if item.action is PlannedAction.SKIP_HELD_BACK
    )
    held_catalog_ids = {item.item_id for item in held_items}
    held_items += tuple(
        AdoptionItem(item_id, None, PlannedAction.SKIP_HELD_BACK.value)
        for item_id in sorted(held_back - held_catalog_ids)
    )
    customized_files = tuple(
        PreservedCustomization(entry.path, entry.state, entry.reason)
        for entry in inventory.customizations.divergences
        if entry.state == "stock-modified"
    )

    receipt_summaries: list[AdoptionReceiptSummary] = []
    for item_id, entry in sorted(
        adopted.items(),
        key=lambda pair: (str(pair[1]["tx_id"]), pair[0]),
        reverse=True,
    ):
        transaction_id = str(entry["tx_id"])
        rewindable, rewind_verdict = _receipt_rewind_evidence(
            context,
            transaction_id,
            item_id,
        )
        receipt_summaries.append(
            AdoptionReceiptSummary(
                item_id,
                str(entry["version"]),
                AdoptionState.ADOPTED.value,
                transaction_id,
                _receipt_when(transaction_id),
                rewindable,
                rewind_verdict,
            )
        )
    receipts = tuple(receipt_summaries)

    recovery_verdict = (
        "UNKNOWN"
        if inspection_error is not None or any(tx.verdict == "UNKNOWN" for tx in transactions)
        else "BROKEN" if transactions else "OK"
    )
    review_verdict = (
        "UNKNOWN"
        if any(item.action is PlannedAction.UNKNOWN for item in plan.items)
        else "OK"
    )
    receipts_verdict = (
        "UNKNOWN"
        if any(receipt.rewind_verdict == "UNKNOWN" for receipt in receipts)
        else "OK"
    )
    report_verdict = (
        "UNKNOWN"
        if "UNKNOWN" in {recovery_verdict, review_verdict, receipts_verdict}
        else "BROKEN" if recovery_verdict == "BROKEN" else "OK"
    )
    return AdoptionReport(
        ADOPTION_REPORT_VERSION,
        report_verdict,
        (
            NewAndSafeGroup(
                "new-and-safe",
                "OK",
                len(new_items),
                new_items,
                f"Here's exactly what this changes for you: {len(new_items)} item(s) are new and safe to adopt.",
            ),
            NeedsReviewGroup(
                "needs-your-review",
                review_verdict,
                len(review_items),
                review_items,
                f"{len(review_items)} item(s) need your review because installed files differ from the release or could not be verified.",
            ),
            PreservedForNowGroup(
                "preserved-for-now",
                "OK",
                len(held_items) + len(customized_files),
                held_items,
                customized_files,
                f"{len(held_items)} held-back item(s) and {len(customized_files)} customized file(s) are preserved for now.",
            ),
            ContinueOrRecoverGroup(
                "continue-or-recover",
                recovery_verdict,
                len(transactions) + int(inspection_error is not None),
                transactions,
                None,
                inspection_error,
                _recovery_surface(transactions, None, inspection_error),
            ),
            ReceiptsAndRewindGroup(
                "receipts-and-rewind",
                receipts_verdict,
                len(receipts),
                receipts,
                f"{len(receipts)} adopted item receipt record(s); {sum(entry.rewindable for entry in receipts)} pass the receipt-backed rewind preflight.",
            ),
        ),
    )


def _probe_release_catalog(context: DoctorContext) -> ProbeResult:
    """Validate the installed release catalog without changing the vault."""
    catalog_path = _release_catalog_path(context)
    if not os.path.lexists(catalog_path):
        return ProbeResult(
            "OFF",
            "No release catalog is installed; this is normal for older Dex releases",
        )
    try:
        catalog = load_catalog(catalog_path, release_root=context.vault_root)
    except (CatalogError, UnicodeError) as error:
        return ProbeResult("BROKEN", f"The installed release catalog is invalid: {_one_line(error)}")
    return ProbeResult(
        "OK",
        f"Release catalog {catalog.release.version} is valid ({len(catalog.items)} items)",
    )


def _probe_adoption_plan(context: DoctorContext) -> ProbeResult:
    """Build and summarize the adoption plan through the same gated entry point /dex-update uses."""
    catalog_path = _release_catalog_path(context)
    if not os.path.lexists(catalog_path):
        return ProbeResult(
            "OFF",
            "Adoption planning is unavailable on this older Dex release because no release catalog is installed",
        )
    try:
        result = lifecycle_service.build_inventory_and_plan(context.vault_root)
    except PlanRejected as error:
        return ProbeResult("BROKEN", f"Updating is blocked: {_one_line(error)}")
    except Exception as error:
        return ProbeResult("UNKNOWN", f"The adoption plan could not be built: {_one_line(error)}")
    counts = result["plan"]["counts"]
    return ProbeResult(
        "OK",
        f"{counts['adopt']} adoptable / {counts['already-adopted']} adopted / "
        f"{counts['conflict']} conflicts",
    )


CUSTOMIZATION_RECORD_PERSISTENCE_CAP = 25


def _customization_persistence_detail(
    authority: dict[str, object],
) -> dict[str, object]:
    """Bound the record list that Doctor writes into its last-run receipt."""
    detail = dict(authority)
    records = authority.get("records")
    if not isinstance(records, list):
        detail["records_truncated"] = False
        return detail
    total = len(records)
    detail["records"] = records[:CUSTOMIZATION_RECORD_PERSISTENCE_CAP]
    detail["records_total"] = total
    detail["records_truncated"] = total > CUSTOMIZATION_RECORD_PERSISTENCE_CAP
    return detail


def _probe_customization_assessment(context: DoctorContext) -> ProbeResult:
    """Build the read-only customization assessment entirely in memory."""
    from core.customization_migration.report import assessment_report
    from core.customization_migration.service import assess

    assessment = assess(context.vault_root)
    authority = _customization_persistence_detail(
        assessment_report(assessment)
    )
    catalog_path = _release_catalog_path(context)
    if os.path.lexists(catalog_path):
        try:
            load_catalog(catalog_path, release_root=context.vault_root)
        except (CatalogError, UnicodeError) as error:
            return ProbeResult(
                "BROKEN",
                f"The installed release catalog is invalid: {_one_line(error)}",
                structured_detail=authority,
            )
    if assessment.baseline_identity_state != "VERIFIED":
        return ProbeResult(
            "UNKNOWN",
            "I couldn't verify which Dex version is installed, so I can't tell you "
            "what you've changed.",
            structured_detail=authority,
        )
    if assessment.completeness == "UNKNOWN":
        observed = assessment.identity.customization_count
        noun = "customization" if observed == 1 else "customizations"
        return ProbeResult(
            "UNKNOWN",
            f"I found {observed} {noun}, but couldn't prove the inventory is complete "
            f"({', '.join(assessment.incomplete_reasons)}). Review the listed exclusions "
            "before creating a Capsule.",
            structured_detail=authority,
        )
    count = assessment.identity.customization_count
    noun = "customization" if count == 1 else "customizations"
    blocked_count = authority["blocked_count"]
    blocked_suffix = f", {blocked_count} blocked" if blocked_count else ""
    return ProbeResult(
        "OK",
        f"Customization assessment completed: {count} {noun}{blocked_suffix}",
        structured_detail=authority,
    )


def _probe_customization_migration_status(context: DoctorContext) -> ProbeResult:
    """Read and validate the bounded capsule status without changing the vault."""
    catalog_path = _release_catalog_path(context)
    if not os.path.lexists(catalog_path):
        return ProbeResult(
            "OFF",
            "Customization migration status is unavailable because no release catalog is installed",
        )
    try:
        load_catalog(catalog_path, release_root=context.vault_root)
    except (CatalogError, UnicodeError) as error:
        return ProbeResult(
            "BROKEN",
            f"The installed release catalog is invalid: {_one_line(error)}",
        )

    try:
        from core.customization_migration.service import migration_status_to_dict
    except ModuleNotFoundError as error:
        missing = error.name or ""
        if missing == "core.customization_migration" or missing.startswith(
            "core.customization_migration."
        ):
            return ProbeResult(
                "OFF",
                "Customization migration status is unavailable on this older Dex release",
            )
        return ProbeResult(
            "UNKNOWN",
            f"The customization migration status module could not load: {_one_line(error)}",
        )

    try:
        authority = migration_status_to_dict(context.vault_root)
    except Exception as error:
        return ProbeResult(
            "UNKNOWN",
            f"The customization migration status could not be read: {_one_line(error)}",
        )

    if not isinstance(authority, dict):
        return ProbeResult(
            "UNKNOWN",
            "The customization migration status response was not an object",
        )
    capsules = authority.get("capsules")
    truncated = authority.get("truncated")
    if not isinstance(capsules, list) or type(truncated) is not bool:
        return ProbeResult(
            "UNKNOWN",
            "The customization migration status response was structurally incomplete",
        )

    recovery_actions = authority.get("recovery_actions", [])
    recovery_token = authority.get("recovery_token")
    if (
        not isinstance(recovery_actions, list)
        or (
            recovery_actions
            and (
                not isinstance(recovery_token, str)
                or len(recovery_token) != 64
            )
        )
        or (not recovery_actions and recovery_token is not None)
    ):
        return ProbeResult(
            "UNKNOWN",
            "The customization recovery status is structurally incomplete",
        )
    expected_recovery_action = (
        "python3 -m core.customization_migration.cli recover "
        f"--confirm-token {recovery_token}"
        if isinstance(recovery_token, str)
        else None
    )
    for recovery in recovery_actions:
        if (
            not isinstance(recovery, dict)
            or set(recovery)
            != {
                "transaction_id",
                "phase",
                "capsule_id",
                "proposal_id",
                "action",
            }
            or not isinstance(recovery["transaction_id"], str)
            or recovery["phase"]
            not in {
                "capsule",
                "staging",
                "verification",
                "activation",
                "rewind",
            }
            or not isinstance(recovery["capsule_id"], str)
            or (
                recovery["proposal_id"] is not None
                and not isinstance(recovery["proposal_id"], str)
            )
            or recovery["action"] != expected_recovery_action
        ):
            return ProbeResult(
                "UNKNOWN",
                "The customization recovery action is structurally incomplete",
            )

    pending = bool(recovery_actions)
    validation_statuses: list[str] = []
    rebuild_broken = bool(recovery_actions)
    rebuild_unknown = False
    for capsule in capsules:
        if not isinstance(capsule, dict):
            return ProbeResult(
                "UNKNOWN",
                "The customization migration status contains a malformed capsule record",
            )
        capsule_id = capsule.get("capsule_id")
        state = capsule.get("state")
        validation = capsule.get("validation")
        if (
            not isinstance(capsule_id, str)
            or not isinstance(state, str)
            or not isinstance(validation, dict)
        ):
            return ProbeResult(
                "UNKNOWN",
                "The customization migration status contains incomplete capsule authority",
            )
        status = validation.get("status")
        mismatches = validation.get("mismatches")
        if not isinstance(status, str) or not isinstance(mismatches, list) or any(
            not isinstance(item, str) for item in mismatches
        ):
            return ProbeResult(
                "UNKNOWN",
                "The customization migration status contains malformed validation authority",
            )
        if capsule_id.startswith("cap-"):
            staging = capsule.get("staging")
            verification_verdicts = capsule.get("verification_verdicts")
            pending_rebuild = capsule.get("pending_rebuild")
            activation = capsule.get("activation")
            activation_receipt_present = capsule.get(
                "activation_receipt_present"
            )
            rewindable = capsule.get("rewindable")
            if (
                not isinstance(staging, dict)
                or not isinstance(verification_verdicts, dict)
                or type(pending_rebuild) is not bool
                or not isinstance(activation, dict)
                or type(activation_receipt_present) is not bool
                or type(rewindable) is not bool
            ):
                return ProbeResult(
                    "UNKNOWN",
                    "The customization rebuild status is structurally incomplete",
                )
            proposals = staging.get("proposals")
            staging_truncated = staging.get("truncated")
            if (
                staging.get("capsule_id") != capsule_id
                or not isinstance(proposals, list)
                or type(staging_truncated) is not bool
                or set(verification_verdicts) != {"OK", "BLOCKED", "UNKNOWN"}
                or any(
                    type(verification_verdicts[key]) is not int
                    or verification_verdicts[key] < 0
                    for key in ("OK", "BLOCKED", "UNKNOWN")
                )
            ):
                return ProbeResult(
                    "UNKNOWN",
                    "The customization staging status is structurally incomplete",
                )
            counted_verdicts = {"OK": 0, "BLOCKED": 0, "UNKNOWN": 0}
            for proposal in proposals:
                if (
                    not isinstance(proposal, dict)
                    or not isinstance(proposal.get("proposal_id"), str)
                    or not isinstance(proposal.get("state"), str)
                    or proposal.get("verification_verdict")
                    not in counted_verdicts
                ):
                    return ProbeResult(
                        "UNKNOWN",
                        "The customization staging status contains a malformed proposal",
                    )
                counted_verdicts[proposal["verification_verdict"]] += 1
                rebuild_broken = rebuild_broken or (
                    proposal["state"] == "recovery-required"
                )
            if counted_verdicts != verification_verdicts:
                return ProbeResult(
                    "UNKNOWN",
                    "The customization verification summary contradicts its proposals",
                )
            activation_required = {
                "capsule_id",
                "proposal_id",
                "state",
                "reason",
                "activation_receipt_present",
                "rewindable",
            }
            if (
                set(activation) != activation_required
                or activation.get("capsule_id") != capsule_id
                or (
                    activation.get("proposal_id") is not None
                    and not isinstance(activation.get("proposal_id"), str)
                )
                or not isinstance(activation.get("state"), str)
                or not isinstance(activation.get("reason"), str)
                or type(activation.get("activation_receipt_present")) is not bool
                or type(activation.get("rewindable")) is not bool
                or activation_receipt_present
                != activation["activation_receipt_present"]
                or rewindable != activation["rewindable"]
            ):
                return ProbeResult(
                    "UNKNOWN",
                    "The customization activation status is structurally incomplete",
                )
            pending = pending or pending_rebuild
            rebuild_broken = rebuild_broken or (
                verification_verdicts["BLOCKED"] > 0
                or activation["state"] == "recovery-required"
            )
            rebuild_unknown = rebuild_unknown or (
                staging_truncated
                or verification_verdicts["UNKNOWN"] > 0
                or (
                    activation_receipt_present
                    and activation["state"]
                    not in {"activated", "rewound"}
                )
            )
        else:
            pending = pending or state == "capsule-created"
        validation_statuses.append(status.upper())

    structured_detail = dict(authority)
    structured_detail["pending"] = pending
    if truncated:
        return ProbeResult(
            "UNKNOWN",
            "The customization migration status reached its capsule limit, so every capsule could not be checked",
            structured_detail=structured_detail,
        )
    if any(status == "BROKEN" for status in validation_statuses):
        return ProbeResult(
            "BROKEN",
            "The preserved capsule evidence failed validation; the mismatch records are surfaced in the status",
            structured_detail=structured_detail,
        )
    if rebuild_broken:
        return ProbeResult(
            "BROKEN",
            "The customization rebuild evidence reports a blocked or recovery-required state",
            structured_detail=structured_detail,
        )
    if any(status != "OK" for status in validation_statuses):
        return ProbeResult(
            "UNKNOWN",
            "The preserved capsule evidence could not be verified",
            structured_detail=structured_detail,
        )
    if rebuild_unknown:
        return ProbeResult(
            "UNKNOWN",
            "The customization rebuild evidence could not be fully verified",
            structured_detail=structured_detail,
        )
    if not capsules:
        detail = "No customization capsules exist"
    elif pending:
        detail = "Every customization capsule validates; a created capsule is pending"
    else:
        detail = "Every customization capsule validates; none are pending"
    return ProbeResult("OK", detail, structured_detail=structured_detail)


def _mcp_config_path(context: DoctorContext) -> Path:
    with _vault_environment(context):
        return preflight.get_mcp_config_path()


def _load_mcp_config(context: DoctorContext) -> dict[str, Any]:
    loaded = json.loads(_mcp_config_path(context).read_text())
    if (
        not isinstance(loaded, dict)
        or "mcpServers" not in loaded
        or not isinstance(loaded["mcpServers"], dict)
    ):
        raise ValueError(".mcp.json must contain an mcpServers object")
    return loaded


def _with_mcp_config_note(context: DoctorContext, detail: str) -> str:
    legacy_path = context.vault_root / "System" / ".mcp.json"
    if _mcp_config_path(context) == legacy_path:
        return f"{detail} (using legacy System/.mcp.json because root .mcp.json is absent)"
    return detail


def _expand_path_token(token: str, context: DoctorContext) -> str:
    expanded = token.replace("{{VAULT_PATH}}", str(context.vault_root))
    expanded = expanded.replace("__VAULT_PATH__", str(context.vault_root))
    expanded = expanded.replace("${CLAUDE_PROJECT_DIR}", str(context.vault_root))
    expanded = expanded.replace("$CLAUDE_PROJECT_DIR", str(context.vault_root))
    return os.path.expanduser(os.path.expandvars(expanded))


def _local_target(token: object, context: DoctorContext, *, command: bool = False) -> Path | None:
    if not isinstance(token, str) or not token or token.startswith("-") or "://" in token:
        return None
    expanded = _expand_path_token(token, context)
    suffixes = {".py", ".js", ".cjs", ".mjs", ".sh"}
    if command:
        if "/" not in expanded and not expanded.startswith((".", "~")):
            return None
    elif Path(expanded).suffix not in suffixes:
        return None
    path = Path(expanded)
    return path if path.is_absolute() else context.vault_root / path


def _entry_targets(entry: object, context: DoctorContext) -> list[Path]:
    if not isinstance(entry, dict):
        raise ValueError("each MCP entry must be an object")
    targets = []
    command_target = _local_target(entry.get("command"), context, command=True)
    if command_target:
        targets.append(command_target)
    args = entry.get("args", [])
    if not isinstance(args, list):
        raise ValueError("each MCP args value must be a list")
    for argument in args:
        target = _local_target(argument, context)
        if target:
            targets.append(target)
    return targets


def _registered_core_scripts(context: DoctorContext, config: dict[str, Any]) -> dict[str, tuple[Path, str]]:
    registered = {}
    for name, entry in config.get("mcpServers", {}).items():
        if not isinstance(entry, dict):
            continue
        interpreter = _expand_path_token(str(entry.get("command", sys.executable)), context)
        for target in _entry_targets(entry, context):
            try:
                relative = target.resolve().relative_to((context.vault_root / "core" / "mcp").resolve())
            except ValueError:
                continue
            if len(relative.parts) == 1 and target.name.endswith("_server.py"):
                registered[name] = (target, interpreter)
                break
    return registered


def _probe_mcp_registered(context: DoctorContext) -> ProbeResult:
    config_path = _mcp_config_path(context)
    if not config_path.exists():
        if not context.core_path("MARKER_FILE").exists():
            return ProbeResult("OFF", ".mcp.json is absent because onboarding has not completed")
        return ProbeResult(
            "BROKEN",
            ".mcp.json is missing after onboarding completed",
            Heal(tier=2, action="Restore .mcp.json from the shipped example.", applied=False),
        )
    try:
        config = _load_mcp_config(context)
        missing = []
        for name, entry in config["mcpServers"].items():
            if not isinstance(entry, dict):
                raise ValueError(f"{name} must contain an object")
            serialized_entry = json.dumps(entry)
            if any(marker in serialized_entry for marker in ("{{VAULT_PATH}}", "{{NODE_PATH}}", "__VAULT_PATH__")):
                missing.append(f"{name} -> live config contains unresolved template values")
                continue
            remote_type = entry.get("type") in {"http", "sse", "streamable-http"} or "url" in entry
            if remote_type:
                url = entry.get("url")
                if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                    raise ValueError(f"{name} must define a valid remote URL")
                continue
            if not isinstance(entry.get("command"), str) or not entry["command"]:
                raise ValueError(f"{name} must define a command string")
            expanded_command = _expand_path_token(entry["command"], context)
            command_target = _local_target(entry["command"], context, command=True)
            if command_target and command_target.is_file() and not os.access(command_target, os.X_OK):
                missing.append(f"{name} -> command {command_target} is not executable")
            elif command_target is None and not shutil.which(expanded_command):
                missing.append(f"{name} -> command {expanded_command}")
            for target in _entry_targets(entry, context):
                if not target.is_file():
                    missing.append(f"{name} -> {target}")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return ProbeResult(
            "BROKEN",
            _with_mcp_config_note(context, f".mcp.json is invalid: {_one_line(error)}"),
            Heal(tier=3, action="Repair .mcp.json by hand while preserving user-added servers.", applied=False),
        )
    if missing:
        return ProbeResult(
            "BROKEN",
            _with_mcp_config_note(context, f"Registered MCP targets are missing: {', '.join(missing)}"),
            Heal(tier=2, action="Repair the missing MCP target paths in .mcp.json.", applied=False),
        )
    return ProbeResult(
        "OK",
        _with_mcp_config_note(
            context,
            f"All {len(config['mcpServers'])} registered MCP entries have valid targets",
        ),
    )


def _probe_mcp_orphans(context: DoctorContext) -> ProbeResult:
    server_dir = context.vault_root / "core" / "mcp"
    shipped = {path.resolve(): path for path in server_dir.glob("*_server.py") if path.is_file()}
    try:
        config = _load_mcp_config(context)
    except FileNotFoundError:
        config = {"mcpServers": {}}
    registered = {
        target.resolve()
        for entry in config["mcpServers"].values()
        for target in _entry_targets(entry, context)
    }
    orphans = [path.name for resolved, path in shipped.items() if resolved not in registered]
    if orphans:
        return ProbeResult(
            "BROKEN",
            _with_mcp_config_note(
                context,
                f"Core MCP servers are not registered: {', '.join(sorted(orphans))}",
            ),
            Heal(tier=2, action="Add the orphaned core MCP servers to .mcp.json.", applied=False),
        )
    return ProbeResult(
        "OK",
        _with_mcp_config_note(context, f"All {len(shipped)} core MCP server files are registered"),
    )


def _python_import_check(python: Path) -> tuple[bool, list[str]]:
    code = """import importlib
import json

names = ["mcp", "yaml", "dateutil", "requests"]
missing = []
for name in names:
    try:
        importlib.import_module(name)
    except Exception:
        missing.append(name)
print(json.dumps(missing))
"""
    result = subprocess.run(
        [str(python), "-c", code],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        return False, [_one_line(result.stderr or result.stdout or f"exit {result.returncode}")]
    return (lambda missing: (not missing, missing))(json.loads(result.stdout))


def _probe_python_env(context: DoctorContext) -> ProbeResult:
    python = context.vault_root / ".venv" / "bin" / "python"
    if not python.is_file() or not os.access(python, os.X_OK):
        return ProbeResult(
            "BROKEN",
            f"The vault Python interpreter is missing or not executable at {python}",
            Heal(tier=2, action="Recreate the vault .venv and install its requirements.", applied=False),
        )
    importable, missing = _python_import_check(python)
    if not importable:
        return ProbeResult(
            "BROKEN",
            f"The vault Python environment cannot import: {', '.join(missing)}",
            Heal(tier=2, action="Install the missing packages into the vault .venv.", applied=False),
        )
    return ProbeResult("OK", "The vault Python and required packages are importable")


def _walk_hook_commands(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "command" and isinstance(child, str):
                yield child
            else:
                yield from _walk_hook_commands(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_hook_commands(child)


def _hook_targets(command: str, context: DoctorContext) -> list[Path]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    targets = []
    for index, token in enumerate(tokens):
        expanded = _expand_path_token(token, context)
        if any(marker in expanded for marker in (">", "<", "|")):
            continue
        candidate = _local_target(expanded, context, command=index == 0)
        if candidate and (index == 0 or candidate.suffix in {".py", ".js", ".cjs", ".mjs", ".sh"}):
            targets.append(candidate)
    return targets


def _missing_hook_executable(command: str, context: DoctorContext) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return None
    executable = _expand_path_token(tokens[0], context)
    if _local_target(executable, context, command=True) is not None:
        return None
    shell_builtins = {"cd", "echo", "export", "false", "printf", "source", "test", "true"}
    if executable in shell_builtins or shutil.which(executable):
        return None
    return executable


def _probe_hooks_wired(context: DoctorContext) -> ProbeResult:
    settings_path = context.vault_root / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text())
    if not isinstance(settings, dict):
        raise ValueError(".claude/settings.json must contain an object")
    hooks = settings.get("hooks", {})
    missing = []
    for command in _walk_hook_commands(hooks):
        missing_executable = _missing_hook_executable(command, context)
        if missing_executable:
            missing.append(f"command executable '{missing_executable}'")
        missing.extend(str(target) for target in _hook_targets(command, context) if not target.is_file())
    if missing:
        return ProbeResult(
            "BROKEN",
            f"Hook commands point at missing files: {', '.join(sorted(set(missing)))}",
            Heal(tier=2, action="Repair the dangling hook command paths.", applied=False),
        )
    return ProbeResult("OK", "Every configured hook command points at an existing file")


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _installed_launch_agents(context: DoctorContext) -> list[tuple[Path, bool]]:
    """Enumerate every launch agent with its presents-as-Dex classification.

    Non-Dex-named plists are enumerated too because ownership evidence is
    the paths inside a plist, not its filename: a user's custom job under
    any label that points into this vault is this vault's business.  The
    naming heuristic (shipped ``com.dex.`` / legacy ``com.claudesidian.``
    prefixes only) exists solely so a corrupt shipped plist reads as
    unreadable instead of foreign — see ``core.utils.launch_agents``.
    """
    directory = context.launch_agents_dir
    if not directory.is_dir():
        return []
    return sorted(
        (path, launch_agents.is_dex_named(path.name))
        for path in directory.glob("*.plist")
    )


def _stored_former_vault_root(context: DoctorContext) -> Path | None:
    """Return the breadcrumb's stored vault path when it names a former root.

    Shared with the session-start hook (``core.utils.launch_agents``) so the
    hook can never warn about a stored former location Doctor refuses to see.
    """
    return launch_agents.stored_former_vault_root(context.vault_root, context.home)


def _plist_references_stale_root(data: dict[str, Any], stale_root: Path) -> bool:
    """Return whether any plist string names the vault's former location."""
    return launch_agents.payload_references_root(data, stale_root)


def _plist_data(plist: Path) -> dict[str, Any]:
    try:
        with plist.open("rb") as handle:
            loaded = plistlib.load(handle)
    except PermissionError:
        raise
    # plistlib raises a zoo of exceptions for damaged files: OSError,
    # InvalidFileException, xml.parsers.expat.ExpatError for truncated XML
    # with a valid header (a classic interrupted write), ValueError for bad
    # scalars, OverflowError for absurd dates. Every one of them means the
    # same thing here — this file is not readable evidence — and none of
    # them may take down the whole probe.
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(f"Could not parse {plist.name}: {_one_line(error)}") from error
    if not isinstance(loaded, dict):
        raise RuntimeError(f"Could not parse {plist.name}: top level is not a dictionary")
    return loaded


def _plist_label(plist: Path, data: dict[str, Any]) -> str:
    return str(data.get("Label") or plist.stem)


def _plist_strings(value: object) -> Iterator[str]:
    yield from launch_agents.iter_plist_strings(value)


def _plist_owned_by_vault(data: dict[str, Any], vault_root: Path) -> bool:
    """Return whether a launch agent's program invocation points into this vault.

    Labels are shared between Dex installs, so they are not ownership
    evidence.  A known ``com.dex.*`` label can still belong to another Dex
    vault on the same Mac; only the ProgramArguments referencing this vault
    make it this vault's responsibility — either an absolute path entry that
    resolves beneath the vault, or the vault root embedded in a shell string
    such as ``/bin/bash -c "cd <vault> && ..."``.  Non-invocation keys
    (WorkingDirectory, StandardOutPath) never claim ownership: a third-party
    tool merely logging into the vault folder is not Dex's job.
    """
    arguments = data.get("ProgramArguments")
    if not isinstance(arguments, list):
        return False
    vault_pattern = launch_agents.reference_pattern(vault_root)
    for argument in arguments:
        if not isinstance(argument, str):
            continue
        if vault_pattern.search(argument):
            return True
        candidate = Path(argument).expanduser()
        if not candidate.is_absolute():
            continue
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            continue
        if resolved.is_relative_to(vault_root):
            return True
    return False


def _with_skipped_launch_agents(detail: str, skipped_count: int) -> str:
    if not skipped_count:
        return detail
    if skipped_count == 1:
        note = "1 Dex launch agent from another Dex product was skipped"
    else:
        note = f"{skipped_count} Dex launch agents from other Dex products were skipped"
    return f"{detail}; {note}"


def _unattributable_launch_agent_detail(plist: Path, error: Exception) -> str:
    return (
        f"Could not determine whether {plist.name} belongs to this vault "
        f"({_one_line(error)})"
    )


def _plist_configuration_issue(plist: Path, data: dict[str, Any], context: DoctorContext) -> str | None:
    arguments = data.get("ProgramArguments")
    if not isinstance(arguments, list) or not arguments or not isinstance(arguments[0], str):
        return f"{plist.name} has no valid ProgramArguments[0]"
    markers = ("{{", "}}", "__VAULT_PATH__", "__HOME__")
    if any(any(marker in value for marker in markers) for value in _plist_strings(data)):
        return f"{plist.name} still contains unsubstituted template values"
    for argument in arguments[1:]:
        target = _local_target(argument, context)
        if target and not target.is_file():
            return f"{plist.name} points at missing program file {target}"
    working_directory = data.get("WorkingDirectory")
    if isinstance(working_directory, str):
        expanded = Path(_expand_path_token(working_directory, context))
        if not expanded.is_absolute():
            expanded = context.vault_root / expanded
        if not expanded.is_dir():
            return f"{plist.name} points at missing working directory {expanded}"
    return None


def _plist_interpreter(plist: Path) -> str:
    result = subprocess.run(
        ["plutil", "-extract", "ProgramArguments.0", "raw", str(plist)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raw_detail = result.stderr.strip() or result.stdout.strip()
        if not raw_detail:
            raise PermissionError(f"plutil could not run while checking {plist.name}")
        detail = raw_detail
        if _looks_like_sandbox_failure(detail):
            raise PermissionError(detail)
        raise RuntimeError(detail)
    return result.stdout.strip()


def _launchctl_domain_check() -> None:
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        detail = _one_line(result.stderr or result.stdout or "launchctl list is unavailable in this environment")
        raise PermissionError(detail)


def _launchctl_status(label: str) -> dict[str, int | bool | None]:
    result = subprocess.run(
        ["launchctl", "list", label],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    combined = _one_line(f"{result.stdout} {result.stderr}")
    if result.returncode != 0:
        if _looks_like_sandbox_failure(combined):
            raise PermissionError(combined)
        return {"loaded": False, "pid": None, "last_exit_status": None}
    pid_match = re.search(r"\bPID\D+(\d+)", result.stdout)
    exit_match = re.search(r"LastExitStatus\D+(-?\d+)", result.stdout)
    return {
        "loaded": True,
        "pid": int(pid_match.group(1)) if pid_match else None,
        "last_exit_status": int(exit_match.group(1)) if exit_match else None,
    }


def _resolved_interpreter(raw: str, context: DoctorContext) -> str | None:
    expanded = _expand_path_token(raw, context)
    if "/" not in expanded:
        return shutil.which(expanded)
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = context.vault_root / candidate
    return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None


_OWNED = "owned"
_STALE = "stale"
_FOREIGN = "foreign"
_UNREADABLE = "unreadable"


@dataclass(frozen=True)
class LaunchAgentRecord:
    """One launch agent's classification, computed once per doctor run."""

    plist: Path
    classification: str  # "owned" | "stale" | "foreign" | "unreadable"
    label: str
    data: dict[str, Any] | None = None
    error_detail: str | None = None  # unreadable only
    stale_references: bool = False  # owned only: former-root strings remain


@dataclass(frozen=True)
class LaunchAgentScan:
    """The classified launch agents plus the evidence they were judged by."""

    stale_root: Path | None
    records: tuple[LaunchAgentRecord, ...]


def _classify_launch_agents(context: DoctorContext) -> LaunchAgentScan:
    """Classify every relevant launch agent exactly once.

    Every Dex-named plist is classified (parse failures included — a corrupt
    shipped plist is UNREADABLE, never assumed foreign).  A plist under any
    other name counts only on path evidence: it references this vault
    (OWNED), or the vault's stored former location (STALE, issue #364).
    Unreadable or irrelevant third-party plists are other products' files
    and can never degrade Dex's own checks.
    """
    stale_root = _stored_former_vault_root(context)
    try:
        vault_root = context.vault_root.resolve()
    except (OSError, RuntimeError):
        vault_root = context.vault_root
    records: list[LaunchAgentRecord] = []
    for plist, dex_named in _installed_launch_agents(context):
        try:
            data = _plist_data(plist)
        except PermissionError:
            # A sandbox that refuses shipped-plist reads makes the whole
            # probe an unknown instrument; other products' files it merely
            # can't read are not this vault's problem.
            if dex_named:
                raise
            continue
        except RuntimeError as error:
            if dex_named:
                records.append(
                    LaunchAgentRecord(
                        plist=plist,
                        classification=_UNREADABLE,
                        label=plist.stem,
                        error_detail=_unattributable_launch_agent_detail(plist, error),
                    )
                )
            continue
        label = _plist_label(plist, data)
        stale_hit = stale_root is not None and _plist_references_stale_root(data, stale_root)
        if _plist_owned_by_vault(data, vault_root):
            records.append(
                LaunchAgentRecord(
                    plist=plist,
                    classification=_OWNED,
                    label=label,
                    data=data,
                    stale_references=stale_hit,
                )
            )
        elif stale_hit:
            # The agent points at this vault's stored former location. That
            # is this vault's job left behind by a move or rename —
            # owned-and-stale, never another product's (issue #364).
            records.append(
                LaunchAgentRecord(
                    plist=plist, classification=_STALE, label=label, data=data
                )
            )
        elif dex_named:
            records.append(
                LaunchAgentRecord(
                    plist=plist,
                    classification=_FOREIGN,
                    label=label,
                    data=data,
                )
            )
    return LaunchAgentScan(stale_root=stale_root, records=tuple(records))


# collect() opens a scan scope so jobs.loaded and jobs.fresh share one
# classification pass per run instead of re-parsing every plist twice.
# Probes called outside a scope (tests, other tools) classify fresh.
_launch_agent_scan_cache: dict[int, LaunchAgentScan | None] = {}


def _begin_launch_agent_scan_scope(context: DoctorContext) -> None:
    _launch_agent_scan_cache[id(context)] = None


def _end_launch_agent_scan_scope(context: DoctorContext) -> None:
    _launch_agent_scan_cache.pop(id(context), None)


def _scan_launch_agents(context: DoctorContext) -> LaunchAgentScan:
    key = id(context)
    if key in _launch_agent_scan_cache:
        cached = _launch_agent_scan_cache[key]
        if cached is None:
            cached = _classify_launch_agents(context)
            _launch_agent_scan_cache[key] = cached
        return cached
    return _classify_launch_agents(context)


def _probe_jobs_loaded(context: DoctorContext) -> ProbeResult:
    scan = _scan_launch_agents(context)
    if not scan.records:
        return ProbeResult("OFF", "No Dex launch agents are installed")
    if not _is_macos():
        return ProbeResult("UNKNOWN", "launchctl and plutil checks are only available on macOS")

    issues: list[tuple[int, str]] = []
    unknowns = []
    runtime_labels = []
    skipped_count = 0
    owned_count = 0
    stale_count = 0
    for record in scan.records:
        if record.classification == _UNREADABLE:
            # A corrupt plist could belong to this vault, but a filename alone
            # cannot establish that safely. Surface the uncertainty instead of
            # falsely treating it as a foreign Dex installation.
            unknowns.append(record.error_detail)
            continue
        if record.classification == _STALE:
            stale_count += 1
            issues.append(
                (
                    2,
                    f"{record.label} still points at this vault's old location "
                    f"({scan.stale_root}) — it keeps running against the moved "
                    "directory until it is repointed or removed",
                )
            )
            continue
        if record.classification == _FOREIGN:
            skipped_count += 1
            continue
        owned_count += 1
        plist, data, label = record.plist, record.data, record.label
        if record.stale_references:
            # Partially repointed: the invocation targets this vault but other
            # keys (WorkingDirectory, log paths, environment) still name the
            # former root — the session-start hook keeps warning until every
            # reference is repointed, so the doctor must surface it too.
            stale_count += 1
            issues.append(
                (
                    2,
                    f"{label} runs against this vault but still references its "
                    f"old location ({scan.stale_root}) — finish repointing it",
                )
            )
            continue
        configuration_issue = _plist_configuration_issue(plist, data, context)
        if configuration_issue:
            issues.append((2, f"{label} has invalid launch-agent configuration ({configuration_issue})"))
            continue
        try:
            raw_interpreter = _plist_interpreter(plist)
        except RuntimeError as error:
            issues.append((2, f"{label} has invalid launch-agent configuration ({_one_line(error)})"))
            continue
        if not _resolved_interpreter(raw_interpreter, context):
            issues.append((3, f"{label} interpreter is missing or not executable ({raw_interpreter})"))
            continue
        runtime_labels.append(label)

    if runtime_labels:
        try:
            _launchctl_domain_check()
        except Exception as error:
            if not issues:
                raise
            unknowns.append(f"launchctl state could not be checked ({_one_line(error)})")
        else:
            for label in runtime_labels:
                try:
                    status = _launchctl_status(label)
                except Exception as error:
                    unknowns.append(f"{label} launchctl state could not be checked ({_one_line(error)})")
                    continue
                if not status["loaded"]:
                    issues.append((2, f"{label} is installed but not loaded"))
                elif isinstance(status.get("pid"), int) and status["pid"] > 0:
                    # LastExitStatus describes the previous process. A live PID
                    # is the current state and must win over stale history.
                    continue
                elif status["last_exit_status"] is None:
                    unknowns.append(f"{label} is loaded but has no observable LastExitStatus")
                elif status["last_exit_status"] != 0:
                    issues.append((2, f"{label} last exited with status {status['last_exit_status']}"))
    if not owned_count and not issues:
        if unknowns:
            return ProbeResult(
                "UNKNOWN",
                _with_skipped_launch_agents("; ".join(unknowns), skipped_count),
            )
        return ProbeResult(
            "OFF",
            _with_skipped_launch_agents("No launch agents for this vault are installed", skipped_count),
        )
    if issues:
        tier = max(issue_tier for issue_tier, _detail in issues)
        action_parts = []
        if any(issue_tier == 3 for issue_tier, _detail in issues):
            action_parts.append("Install or repair the missing job interpreter by hand")
        if stale_count:
            action_parts.append(
                "repoint the stale launch agent at this vault's current location "
                f"({context.vault_root}) — unload it, rewrite the old paths, plutil -lint, "
                "reload — or remove it, and update ~/.config/dex/vault-path, "
                "only after explicit approval"
            )
        if sum(1 for issue_tier, _detail in issues if issue_tier == 2) > stale_count:
            action_parts.append("repair or reload the named launch agent only after explicit approval")
        detail_parts = [detail for _tier, detail in issues]
        detail_parts.extend(unknowns)
        return ProbeResult(
            "BROKEN",
            _with_skipped_launch_agents("; ".join(detail_parts), skipped_count),
            Heal(tier=tier, action="; then ".join(action_parts) + ".", applied=False),
        )
    if unknowns:
        return ProbeResult(
            "UNKNOWN",
            _with_skipped_launch_agents("; ".join(unknowns), skipped_count),
        )
    return ProbeResult(
        "OK",
        _with_skipped_launch_agents(
            f"All {owned_count} installed launch agents for this vault are loaded with valid interpreters",
            skipped_count,
        ),
    )


def _probe_jobs_fresh(context: DoctorContext) -> ProbeResult:
    """Audit installed jobs against the health promise register.

    The register's receipts prove success, not activity, so a job that keeps
    running while failing every time is reported broken here even though its
    log never stops growing.
    """
    from core.health import promises as health_promises

    def _promise_for_label(label: str):
        # Pre-rename installs run the same shipped jobs under the legacy
        # com.claudesidian.* labels; they map onto their com.dex.* promises
        # so their freshness is genuinely audited, not waved through as
        # unauditable user jobs.
        for candidate in launch_agents.promise_label_candidates(label):
            promise = health_promises.promise_by_id(candidate)
            if promise is not None:
                return promise
        return None

    scan = _scan_launch_agents(context)
    unknowns = [
        record.error_detail
        for record in scan.records
        if record.classification == _UNREADABLE
    ]
    installed = sorted(
        {record.label for record in scan.records if record.classification == _OWNED}
    )
    monitored = []
    monitored_ids = set()
    unregistered = []
    for label in installed:
        promise = _promise_for_label(label)
        if promise is None:
            unregistered.append(label)
        elif promise.receipt_kind != "daemon" and promise.id not in monitored_ids:
            monitored_ids.add(promise.id)
            monitored.append(promise)

    # Jobs with no receipt in the promise register cannot be freshness-
    # audited. Say so plainly at every verdict instead of letting "OFF" read
    # as "nothing to monitor" (issue #253).
    coverage_note = ""
    if unregistered:
        count = len(unregistered)
        noun = "launch agent" if count == 1 else "launch agents"
        verb = "is" if count == 1 else "are"
        coverage_note = (
            f"{count} {noun} referencing this vault ({', '.join(unregistered)}) "
            f"{verb} checked for loading only, not freshness "
            "(no registered freshness receipt)"
        )

    def _with_coverage_note(detail: str) -> str:
        return f"{detail}; {coverage_note}" if coverage_note else detail

    if not monitored:
        if unknowns:
            return ProbeResult("UNKNOWN", _with_coverage_note("; ".join(unknowns)))
        return ProbeResult(
            "OFF", _with_coverage_note("No shipped Dex freshness jobs are installed")
        )

    stale = []
    for promise in monitored:
        audit = health_promises.audit_promise(context.vault_root, promise, now=context.now)
        if audit.state in {"never", "broken"}:
            stale.append(audit.detail())
    if stale:
        return ProbeResult(
            "BROKEN",
            _with_coverage_note("; ".join([*stale, *unknowns])),
            Heal(tier=2, action="Run the stale job once and inspect its application log.", applied=False),
        )
    if unknowns:
        return ProbeResult("UNKNOWN", _with_coverage_note("; ".join(unknowns)))
    return ProbeResult(
        "OK",
        _with_coverage_note(
            f"All {len(monitored)} installed job promises are within their promised cadence"
        ),
    )


def _preflight_snapshot(context: DoctorContext) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with _vault_environment(context):
        health = preflight.run_preflight()
        queued = dex_logger.get_unacknowledged_errors(now=context.now)
    return health, queued


def _historical_preflight_errors(context: DoctorContext) -> list[dict[str, Any]]:
    with _vault_environment(context):
        return dex_logger.get_historical_errors(now=context.now)


def _parsed_queue_timestamp(value: object) -> datetime | None:
    from core.utils.timezone import parse_timestamp

    parsed = parse_timestamp(value)
    return parsed.astimezone(timezone.utc) if parsed is not None else None


def _resolved_preflight_error_ids(
    health: dict[str, Any],
    entries: list[dict[str, Any]],
) -> set[str]:
    servers = health.get("servers")
    if not isinstance(servers, dict):
        return set()
    resolved: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        source = entry.get("source")
        failed_at = _parsed_queue_timestamp(entry.get("timestamp"))
        server = servers.get(source) if isinstance(source, str) else None
        succeeded_at = (
            _parsed_queue_timestamp(server.get("checkedAt"))
            if isinstance(server, dict) and server.get("status") == "ok"
            else None
        )
        if (
            isinstance(entry_id, str)
            and failed_at is not None
            and succeeded_at is not None
            and succeeded_at > failed_at
        ):
            resolved.add(entry_id)
    return resolved


def _acknowledge_resolved_preflight_errors(context: DoctorContext) -> int:
    """Acknowledge queue entries only when health has newer same-source success."""
    with _vault_environment(context):
        status, entries = dex_logger._read_queue_with_status()
        if status != "readable":
            return 0
        health = preflight.run_preflight()
        resolved = _resolved_preflight_error_ids(health, entries)
        if not resolved:
            return 0
        acknowledged = 0
        for entry in entries:
            if (
                isinstance(entry, dict)
                and entry.get("id") in resolved
                and not entry.get("acknowledged", False)
            ):
                entry["acknowledged"] = True
                entry["acknowledgedAt"] = context.now.astimezone(timezone.utc).isoformat()
                acknowledged += 1
        if acknowledged:
            dex_logger._write_queue(entries, now=context.now)
        return acknowledged


def _preflight_error_queue_status(context: DoctorContext) -> str:
    with _vault_environment(context):
        return dex_logger.get_error_queue_status()


def _queued_error_date(entry: dict[str, Any]) -> str:
    timestamp = entry.get("timestamp")
    if isinstance(timestamp, str):
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
    return "date unavailable"


def _historical_error_summary(
    context: DoctorContext,
    entries: list[dict[str, Any]],
) -> str | None:
    if not entries:
        return None

    current_version = None
    try:
        package = json.loads((context.vault_root / "package.json").read_text())
        if isinstance(package, dict) and isinstance(package.get("version"), str):
            current_version = package["version"]
    except (OSError, json.JSONDecodeError):
        pass

    previous_version_count = sum(
        isinstance(entry.get("dexVersion"), str)
        and current_version is not None
        and entry["dexVersion"] != current_version
        for entry in entries
    )
    count = len(entries)
    subject = "1 earlier error" if count == 1 else f"{count} earlier errors"
    if previous_version_count == count:
        reason = (
            " from a previous Dex version"
            if count == 1
            else " from previous Dex versions"
        )
    elif previous_version_count:
        reason = (
            " from previous Dex versions or more than "
            f"{dex_logger.STALE_ERROR_DAYS} days ago"
        )
    else:
        reason = (
            " that is old enough to count as history"
            if count == 1
            else " that are old enough to count as history"
        )

    dated = [
        _queued_error_date(entry)
        for entry in entries
        if _queued_error_date(entry) != "date unavailable"
    ]
    if dated:
        return f"{subject}{reason}, last on {max(dated)}"
    return f"{subject}{reason}, dates unavailable"


def _probe_preflight_queue(context: DoctorContext) -> ProbeResult:
    health, queued = _preflight_snapshot(context)
    if _preflight_error_queue_status(context) == "unreadable":
        return ProbeResult(
            "UNKNOWN",
            "The error log could not be read, so queued errors were not checked",
        )
    resolved_ids = _resolved_preflight_error_ids(health, queued)
    queued = [entry for entry in queued if entry.get("id") not in resolved_ids]
    resolved_count = len(resolved_ids)
    resolved_heal = (
        Heal(
            tier=1,
            action=(
                f"Acknowledge {resolved_count} resolved preflight "
                f"{'error' if resolved_count == 1 else 'errors'}."
            ),
            applied=False,
        )
        if resolved_count
        else None
    )
    historical_summary = _historical_error_summary(
        context,
        _historical_preflight_errors(context),
    )
    server_errors = []
    core_server_names = set(preflight.SERVER_MODULES)
    try:
        core_server_names.update(_registered_core_scripts(context, _load_mcp_config(context)))
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        pass
    unknown_core_servers = []
    for name, result in health.get("servers", {}).items():
        if result.get("status") == "error":
            server_errors.append(result.get("humanError") or result.get("error") or f"{name} failed")
        elif result.get("status") == "unknown" and name in core_server_names:
            unknown_core_servers.append(name)
    queued_errors = [
        (
            f"{error.get('humanMessage') or error.get('message') or 'queued background error'} "
            f"(on {_queued_error_date(error)})"
        )
        for error in queued
    ]
    problems = [*server_errors, *queued_errors]
    if problems:
        detail = f"Preflight reported: {'; '.join(str(problem) for problem in problems)}"
        if historical_summary:
            detail += f"; {historical_summary}"
        if unknown_core_servers:
            detail += f"; preflight did not check: {', '.join(sorted(unknown_core_servers))}"
        return ProbeResult("BROKEN", detail, resolved_heal)
    if unknown_core_servers:
        detail = f"Preflight did not check registered core servers: {', '.join(sorted(unknown_core_servers))}"
        if historical_summary:
            detail += f"; {historical_summary}"
        return ProbeResult(
            "UNKNOWN",
            detail,
            resolved_heal,
        )
    detail = "Preflight completed with no server or current queued errors"
    if resolved_count:
        noun = "error has" if resolved_count == 1 else "errors have"
        detail += (
            f"; {resolved_count} queued {noun} a newer successful check"
        )
    if historical_summary:
        detail += f"; {historical_summary}"
    return ProbeResult("OK", detail, resolved_heal)


def _capability_seed_paths(room: str) -> tuple[str, ...]:
    from core import capabilities

    folders = tuple(
        str(folder).rstrip("/")
        for folder in capabilities.surfaces_for(room).get("folders", [])
    )
    return tuple(
        sorted(
            rule.path
            for rule in portable_contract.RULES
            if rule.ownership == "seed"
            and rule.kind == "file"
            and any(
                rule.path == folder or rule.path.startswith(f"{folder}/")
                for folder in folders
            )
        )
    )


def _probe_capability_rooms(context: DoctorContext) -> ProbeResult:
    from core import capabilities

    profile_path = context.vault_root / "System/user-profile.yaml"
    if not capabilities.has_onboarding_evidence(
        context.vault_root,
        profile_path=profile_path,
    ):
        return ProbeResult(
            "OFF",
            "Capability rooms are not active until onboarding has real user evidence",
        )

    missing_folders: list[str] = []
    missing_skills: list[str] = []
    stale_skills: list[str] = []
    missing_seeds: list[str] = []
    for room in capabilities.room_ids():
        room_enabled = capabilities.enabled(room, profile_path=profile_path)
        surfaces = capabilities.surfaces_for(room)
        if room_enabled:
            for relative in surfaces.get("folders", []):
                path = context.vault_root / str(relative)
                if path.is_symlink() or not path.is_dir():
                    missing_folders.append(f"{room}: {relative}")
            for skill in surfaces.get("skills", []):
                path = context.vault_root / ".claude/skills" / str(skill)
                skill_file = path / "SKILL.md"
                if (
                    path.is_symlink()
                    or not path.is_dir()
                    or skill_file.is_symlink()
                    or not skill_file.is_file()
                ):
                    missing_skills.append(f"{room}: {skill}")
            for relative in _capability_seed_paths(room):
                path = context.vault_root / relative
                if path.is_symlink() or not path.is_file():
                    missing_seeds.append(relative)
        else:
            for skill in surfaces.get("skills", []):
                path = context.vault_root / ".claude/skills" / str(skill)
                if path.exists() or path.is_symlink():
                    stale_skills.append(f"{room}: {skill}")

    findings: list[str] = []
    if missing_folders:
        findings.append(
            f"Enabled room folders are missing: {', '.join(missing_folders)}"
        )
    if missing_skills:
        findings.append(
            f"Enabled room skills are missing: {', '.join(missing_skills)}"
        )
    if stale_skills:
        findings.append(
            f"Disabled room skills are still live: {', '.join(stale_skills)}"
        )
    if missing_seeds:
        findings.append(
            "Missing enabled-room seed files: "
            f"{', '.join(missing_seeds)} — run /dex-update to restore"
        )
    if findings:
        return ProbeResult(
            "BROKEN",
            "; ".join(findings),
            Heal(
                tier=1,
                action=(
                    "Reconcile capability room folders and shipped skills "
                    "without deleting user content."
                ),
                applied=False,
            ),
        )
    return ProbeResult(
        "OK",
        "Enabled room folders, shipped skills, and seed files match the saved room choices",
    )


def _display_vault_path(context: DoctorContext, path: Path) -> str:
    try:
        return path.relative_to(context.vault_root).as_posix()
    except ValueError:
        return str(path)


def _unsafe_customization_path(context: DoctorContext, path: Path) -> str | None:
    """Return why *path* must not be read, without resolving symlinks."""
    try:
        relative = path.relative_to(context.vault_root)
    except ValueError:
        return "is outside the vault"
    if any(part in {"", ".", ".."} for part in relative.parts):
        return "contains an unsafe path component"
    if any(
        part.lower() == ".env"
        or part.lower().startswith(".env.")
        or "credential" in part.lower()
        for part in relative.parts
    ):
        return "is credential-sensitive"
    current = context.vault_root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return "is symlinked"
    return None


def _probe_customization_skills(context: DoctorContext) -> ProbeResult:
    from core.utils.validators import validate_skill_frontmatter

    skills_root = context.vault_root / ".claude" / "skills"
    root_safety = _unsafe_customization_path(context, skills_root)
    if root_safety:
        relative = _display_vault_path(context, skills_root)
        return ProbeResult(
            "UNKNOWN",
            f"{relative} {root_safety} and was not read for safety; fix or remove {relative}",
        )
    skill_directories = sorted(
        (
            path
            for path in skills_root.iterdir()
            if path.name not in KNOWN_SKILL_CONTAINER_DIRECTORIES
            and (
                path.is_symlink()
                or (path.is_dir() and any(path.iterdir()))
            )
        ),
        key=lambda path: path.name,
    ) if skills_root.is_dir() else []
    catalogued_paths: frozenset[str] | None = None
    catalog_path = _release_catalog_path(context)
    if catalog_path.is_file():
        try:
            catalog = load_catalog(catalog_path, release_root=context.vault_root)
        except (CatalogError, OSError, UnicodeError):
            pass
        else:
            catalogued_paths = frozenset(
                file.path
                for item in catalog.items
                for file in item.files
            )
    failures = []
    safety_findings = []
    custom_count = 0
    for skill_directory in skill_directories:
        skill_path = skill_directory / "SKILL.md"
        relative = _display_vault_path(context, skill_path)
        is_custom = skill_directory.name.endswith("-custom")
        custom_count += int(is_custom)
        release_carries_skill = catalogued_paths is None or relative in catalogued_paths
        shipped_label = "shipped skill" if release_carries_skill else "skill"
        guidance = (
            f"run /dex-update to restore {relative}"
            if release_carries_skill
            else f"fix or remove {relative}"
        )
        safety_reason = _unsafe_customization_path(context, skill_path)
        if safety_reason:
            if is_custom:
                safety_findings.append(
                    f"user customization {relative} {safety_reason} and was not read for safety; "
                    f"fix or remove {relative}"
                )
            else:
                safety_findings.append(
                    f"{shipped_label} {relative} {safety_reason} and was not read for safety; "
                    f"{guidance}"
                )
            continue
        errors = validate_skill_frontmatter(skill_path)
        if not errors:
            continue
        issue = "; ".join(_one_line(error) for error in errors)
        if is_custom:
            failures.append(
                f"user customization {relative} is invalid ({issue}); fix or remove {relative}"
            )
        else:
            failures.append(
                f"{shipped_label} {relative} is invalid ({issue}); {guidance}"
            )

    findings = [*failures, *safety_findings]
    if findings:
        return ProbeResult("BROKEN" if failures else "UNKNOWN", "; ".join(findings))
    shipped_count = len(skill_directories) - custom_count
    custom_noun = "customization" if custom_count == 1 else "customizations"
    shipped_noun = "skill" if shipped_count == 1 else "skills"
    return ProbeResult(
        "OK",
        f"Validated {custom_count} user {custom_noun} and {shipped_count} shipped {shipped_noun}",
    )


def _customization_mcp_source(context: DoctorContext) -> tuple[Path | None, bool]:
    live_config = _mcp_config_path(context)
    if live_config.exists() or live_config.is_symlink():
        return live_config, False
    shipped_example = context.vault_root / "System" / ".mcp.json.example"
    if shipped_example.exists() or shipped_example.is_symlink():
        return shipped_example, True
    return None, False


def _mcp_customization_failure(
    context: DoctorContext,
    config_path: Path,
    issue: str,
    *,
    shipped_example: bool,
) -> ProbeResult:
    relative = _display_vault_path(context, config_path)
    if shipped_example:
        guidance = f"run /dex-update to restore {relative}"
    else:
        guidance = f"fix your customization in {relative}"
    return ProbeResult("BROKEN", f"{relative} is invalid ({issue}); {guidance}")


def _probe_customization_mcp(context: DoctorContext) -> ProbeResult:
    from core.utils.trust_registry import (
        load_trusted_mcp_registry,
        snapshot_trusted_mcp,
    )
    from core.utils.validators import validate_mcp_config

    config_path, shipped_example = _customization_mcp_source(context)
    if config_path is None:
        return ProbeResult("OK", "No live MCP configuration is present; 0 custom entries require validation")

    config_safety = _unsafe_customization_path(context, config_path)
    if config_safety:
        relative = _display_vault_path(context, config_path)
        guidance = (
            f"run /dex-update to restore {relative}"
            if shipped_example
            else f"fix your customization in {relative}"
        )
        return ProbeResult(
            "UNKNOWN",
            f"{relative} {config_safety} and was not read or executed for safety; {guidance}",
        )

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return _mcp_customization_failure(
            context,
            config_path,
            _one_line(error),
            shipped_example=shipped_example,
        )

    structural_errors = validate_mcp_config(config)
    if shipped_example:
        structural_errors = [
            error for error in structural_errors if "unresolved placeholder" not in error
        ]
    if structural_errors:
        return _mcp_customization_failure(
            context,
            config_path,
            "; ".join(_one_line(error) for error in structural_errors),
            shipped_example=shipped_example,
        )

    servers = config["mcpServers"]
    custom_entries = [
        (name, entry)
        for name, entry in servers.items()
        if isinstance(name, str) and name.startswith("custom-")
    ]
    compile_failures = []
    safety_findings = []
    blessed_findings = []
    trust_registry = load_trusted_mcp_registry(context.vault_root)
    with tempfile.TemporaryDirectory(prefix="dex-doctor-mcp-compile-") as temporary:
        compile_root = Path(temporary)
        compile_index = 0
        for name, entry in custom_entries:
            if trust_registry.invalid_reason is not None:
                safety_findings.append(
                    f"{name} trusted MCP registry is invalid ({trust_registry.invalid_reason})"
                )
                continue
            trusted_target: Path | None = None
            if name in trust_registry.entries:
                decision = snapshot_trusted_mcp(
                    context.vault_root,
                    name,
                    entry,
                    trust_registry,
                    compile_root / "trusted-snapshots",
                )
                if not decision.trusted or decision.snapshot_path is None:
                    safety_findings.append(f"{name} was not executed: {decision.detail}")
                    continue
                trusted_target = decision.snapshot_path
                blessed_file = trust_registry.entries[name].file
                blessed_findings.append(
                    f"{name} is blessed: this runs {blessed_file} with your user permissions "
                    "(nightly and in deep scans), and trusts whatever it imports"
                )
            python_targets = sorted(
                {trusted_target} if trusted_target is not None else {
                    target
                    for target in _entry_targets(entry, context)
                    if target.suffix == ".py"
                },
                key=str,
            )
            for target in python_targets:
                if trusted_target is not None:
                    relative_target = trust_registry.entries[name].file
                    safety_reason = None
                else:
                    relative_target = _display_vault_path(context, target)
                    safety_reason = _unsafe_customization_path(context, target)
                if safety_reason:
                    safety_findings.append(
                        f"{name} target {relative_target} {safety_reason} and was not compiled or "
                        "executed for safety"
                    )
                    continue
                if not target.is_file():
                    compile_failures.append(f"{name} target {relative_target} is missing")
                    continue
                compile_index += 1
                cfile = compile_root / f"target-{compile_index}.pyc"
                try:
                    py_compile.compile(
                        str(target),
                        cfile=str(cfile),
                        doraise=True,
                    )
                except (OSError, py_compile.PyCompileError) as error:
                    compile_failures.append(
                        f"{name} target {relative_target} does not compile ({_one_line(error)})"
                    )

    if compile_failures:
        issues = [*compile_failures, *safety_findings]
        return _mcp_customization_failure(
            context,
            config_path,
            "; ".join(issues),
            shipped_example=shipped_example,
        )

    if safety_findings:
        relative = _display_vault_path(context, config_path)
        guidance = (
            f"run /dex-update to restore {relative}"
            if shipped_example
            else f"fix your customization in {relative}"
        )
        return ProbeResult(
            "UNKNOWN",
            f"{relative} is structurally valid; {'; '.join(safety_findings)}; {guidance}",
        )

    relative = _display_vault_path(context, config_path)
    noun = "entry" if len(custom_entries) == 1 else "entries"
    if blessed_findings:
        return ProbeResult(
            "OK",
            f"{relative} is structurally valid; {'; '.join(blessed_findings)}",
        )
    return ProbeResult(
        "OK",
        f"{relative} is structurally valid; {len(custom_entries)} custom MCP {noun} checked and not executed for safety",
    )


def _git_result(
    context: DoctorContext,
    *arguments: str,
    git_directory: Path | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    executable = next(
        (
            str(candidate)
            for candidate in DOCTOR_GIT_CANDIDATES
            if not candidate.is_symlink() and candidate.is_file() and os.access(candidate, os.X_OK)
        ),
        None,
    )
    if executable is None:
        return subprocess.CompletedProcess([], 127, "", "trusted system git is unavailable")
    safe_path, _tools = release_channel.sanitized_path_with_tools(
        context.vault_root,
        ("node", "python3"),
    )
    return subprocess.run(
        [
            executable,
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.attributesFile=/dev/null",
            "-c",
            "core.excludesFile=/dev/null",
            "-c",
            "submodule.recurse=false",
            "-C",
            str(context.repo_root),
            *([f"--git-dir={git_directory}"] if git_directory is not None else []),
            *arguments,
        ],
        capture_output=True,
        input=input_text,
        env={
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": "/var/empty" if Path("/var/empty").is_dir() else "/",
            "LC_ALL": "C",
            "PATH": safe_path,
        },
        text=True,
        timeout=10,
        check=False,
    )


def _regular_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _topology_state(context: DoctorContext) -> str:
    lifecycle_state = lifecycle_engine.topology_state(context.vault_root)
    return {
        "combined": "migration-pending",
        "invalid-combined": "combined",
    }.get(lifecycle_state, lifecycle_state)


def _probe_vault_git(context: DoctorContext) -> ProbeResult:
    topology = _topology_state(context)
    if topology != "post-split":
        if topology == "invalid-split":
            return ProbeResult(
                "BROKEN",
                "The split topology marker exists, but the vault Git marker is missing or invalid — use /dex-update recovery",
            )
        return ProbeResult(
            "OFF",
            "The separate vault history is not active; the topology check reports the current layout",
        )
    git_directory = context.vault_root / ".git"
    healthy = _git_result(
        context, "rev-parse", "--git-dir", git_directory=git_directory
    )
    if healthy.returncode != 0:
        return ProbeResult(
            "BROKEN",
            "The vault Git repository cannot be opened — your files remain on disk, but history needs repair",
        )
    integrity = _git_result(
        context, "fsck", "--no-progress", git_directory=git_directory
    )
    if integrity.returncode != 0:
        return ProbeResult(
            "BROKEN",
            "The vault Git repository failed its integrity check — do not push it; repair the local history",
        )
    remotes = _git_result(context, "remote", git_directory=git_directory)
    remote_count = (
        len([line for line in remotes.stdout.splitlines() if line.strip()])
        if remotes.returncode == 0
        else 0
    )
    suffix = (
        "no private backup remote configured"
        if remote_count == 0
        else f"{remote_count} private backup remote(s) configured"
    )
    return ProbeResult("OK", f"The local vault history is healthy; {suffix}")


def _probe_brain_git(context: DoctorContext) -> ProbeResult:
    topology_state = _topology_state(context)
    if topology_state != "post-split":
        if topology_state == "invalid-split":
            return ProbeResult(
                "BROKEN",
                "The split topology marker exists, but the brain Git marker is missing or invalid — use the updater recovery path",
            )
        return ProbeResult("OFF", "The separate Dex brain history is not active")
    brain = context.vault_root / ".dex/brain.git"
    installed = _git_result(
        context,
        "rev-parse",
        "--verify",
        "refs/dex/installed^{commit}",
        git_directory=brain,
    )
    if installed.returncode != 0:
        return ProbeResult(
            "BROKEN",
            "The Dex brain history cannot resolve its installed release — rerun /dex-update",
        )
    installed_oid = installed.stdout.strip().lower()
    brain_marker = _regular_json(brain / "dex-brain-v2")
    topology = _regular_json(context.vault_root / "System/.dex/topology.json")
    marker_oid = str(brain_marker.get("installed", "")).lower() if brain_marker else ""
    topology_oid = str(topology.get("installedRelease", "")).lower() if topology else ""
    if not installed_oid or marker_oid != installed_oid or topology_oid != installed_oid:
        return ProbeResult(
            "BROKEN",
            "The Dex brain release identity disagrees across its installed ref and topology markers — rerun /dex-update",
        )
    configured = _git_result(
        context, "config", "--get", "remote.origin.url", git_directory=brain
    )
    effective = _git_result(
        context, "remote", "get-url", "origin", git_directory=brain
    )
    official = re.compile(
        r"^(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)"
        r"davekilleen/Dex(?:\.git)?/?$",
        re.IGNORECASE,
    )
    if (
        configured.returncode != 0
        or effective.returncode != 0
        or not official.fullmatch(configured.stdout.strip())
        or not official.fullmatch(effective.stdout.strip())
    ):
        return ProbeResult(
            "BROKEN",
            "The Dex brain origin is not the effective official repository — repair it before updating",
        )
    integrity = _git_result(context, "fsck", "--no-progress", git_directory=brain)
    if integrity.returncode != 0:
        return ProbeResult(
            "BROKEN",
            "The Dex brain Git store failed its integrity check — stop updating and repair it",
        )
    archive = context.vault_root / ".dex/pre-split-archive.git"
    archive_note = (
        " The pre-split restore archive is still present."
        if archive.is_dir() and not archive.is_symlink()
        else ""
    )
    return ProbeResult(
        "OK",
        f"The Dex brain history is healthy at {installed_oid[:12]}.{archive_note}",
    )


def _probe_pre_split_archive(context: DoctorContext) -> ProbeResult:
    """Describe the retained pre-split history without treating it as a fault."""
    archive = context.vault_root / ".dex/pre-split-archive.git"
    if not archive.exists():
        return ProbeResult("OFF", "No pre-split undo archive is present")
    if archive.is_symlink() or not archive.is_dir():
        return ProbeResult("BROKEN", "The pre-split undo archive is not a safe directory")
    try:
        size_bytes = sum(
            path.stat().st_size
            for path in archive.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
        age_days = max(0, int((context.now.timestamp() - archive.stat().st_mtime) // 86_400))
    except OSError as error:
        return ProbeResult("UNKNOWN", f"Could not inspect the pre-split undo archive: {_one_line(str(error))}")
    size_text = _format_archive_size(size_bytes)
    return ProbeResult(
        "OK",
        f"The pre-split undo archive is present ({age_days} days old, {size_text}). "
        "It is the one-command undo for the brain/vault conversion. Keep it for one full "
        "release cycle after conversion, then Dex can offer its receipted removal.",
    )


def _probe_vault_auto_commit(context: DoctorContext) -> ProbeResult:
    profile_path = context.vault_root / "System/user-profile.yaml"
    if profile_path.is_symlink():
        return ProbeResult(
            "UNKNOWN",
            "The doctor will not follow a symlinked profile to inspect vault auto-commit",
        )
    try:
        profile = _load_yaml(profile_path)
    except FileNotFoundError:
        profile = {}
    if not isinstance(profile, dict):
        return ProbeResult(
            "BROKEN", "Vault auto-commit cannot read user-profile.yaml as a mapping"
        )
    vault_settings = profile.get("vault")
    enabled = (
        isinstance(vault_settings, dict)
        and vault_settings.get("auto_commit") is True
    )
    if not enabled:
        return ProbeResult(
            "OFF", "Vault auto-commit is off by default; local files remain untouched"
        )
    if _topology_state(context) != "post-split":
        return ProbeResult(
            "BROKEN",
            "Vault auto-commit is enabled before the split topology is ready — run /dex-update",
        )
    return ProbeResult(
        "OK", "Vault auto-commit is enabled for local snapshots and never pushes"
    )


def _probe_migration_pending(context: DoctorContext) -> ProbeResult:
    topology = _topology_state(context)
    if topology == "post-split":
        return ProbeResult("OK", "The brain/vault split is complete")
    if topology == "migration-pending":
        return ProbeResult(
            "OFF",
            "Optional one-time upgrade available — run /dex-update when you want it; "
            "notes stay in place either way",
        )
    if topology == "migration-in-progress":
        return ProbeResult(
            "BROKEN",
            "The one-time upgrade is incomplete. Run core/migrations/v1-to-v2-brain-vault-split.cjs "
            "--resume to continue, or --restore to return to the pre-split layout. Do not reinstall, "
            "restore backups, or run raw Git commands while recovery is pending.",
        )
    if topology == "invalid-split":
        return ProbeResult(
            "BROKEN",
            "The split topology markers or DEX_VAULT wiring disagree. Run "
            "core/migrations/v1-to-v2-brain-vault-split.cjs --resume to continue, or --restore "
            "to return to the pre-split layout. Do not reinstall, restore backups, or run raw Git commands.",
        )
    if topology == "zip-or-manual":
        return ProbeResult(
            "OFF", "This ZIP/manual install has no Git topology; use the manual update path"
        )
    return ProbeResult(
        "OFF", "This is the older combined topology; updates keep using the merge path"
    )


def _upstream_release_ref(context: DoctorContext, channel: str | None = None) -> str | None:
    resolved_channel = channel or release_channel.read_channel(context.vault_root)
    for candidate in release_channel.release_ref_candidates(resolved_channel):
        remote_ref = f"refs/remotes/{candidate}"
        result = _git_result(context, "rev-parse", "--verify", "--quiet", f"{remote_ref}^{{commit}}")
        if result.returncode == 0:
            return remote_ref
    return None


def _installed_release_treeish(context: DoctorContext) -> str | None:
    """Resolve the git identity of the release this vault actually runs.

    package.json carries the installed release version and releases are
    tagged, so the matching tag names the exact installed tree — regardless
    of how far ahead the fetched release tip has moved since.
    """
    package = _regular_json(context.repo_root / "package.json")
    version = package.get("version") if isinstance(package, dict) else None
    if not isinstance(version, str) or not version:
        return None
    for tag in (f"v{version}", version):
        ref = f"refs/tags/{tag}"
        result = _git_result(context, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        if result.returncode == 0:
            return ref
    return None


def _git_output_or_raise(result: subprocess.CompletedProcess[str], operation: str) -> str:
    if result.returncode == 0:
        return result.stdout
    detail = _one_line(result.stderr or result.stdout or f"exit {result.returncode}")
    raise RuntimeError(f"git could not {operation}: {detail}")


def _sanctioned_customization_path(relative: str) -> bool:
    if relative in {"System/user-profile.yaml", "System/pillars.yaml"}:
        return True
    parts = relative.split("/")
    if (
        len(parts) >= 3
        and parts[:2] == [".claude", "skills"]
        and parts[2].endswith("-custom")
    ):
        return True
    return (
        len(parts) == 3
        and parts[:2] == ["System", "integrations"]
        and Path(relative).suffix == ".yaml"
    )


def _git_file(
    context: DoctorContext,
    treeish: str,
    relative: str,
    *,
    git_directory: Path | None = None,
) -> str | None:
    result = _git_result(
        context,
        "show",
        f"{treeish}:{relative}",
        git_directory=git_directory,
    )
    return result.stdout if result.returncode == 0 else None


def _working_file(context: DoctorContext, relative: str) -> str | None:
    path = context.repo_root / relative
    try:
        lexical = path.relative_to(context.repo_root)
    except ValueError:
        return None
    if any(
        part in {"", ".", ".."}
        or part.lower() == ".env"
        or part.lower().startswith(".env.")
        or "credential" in part.lower()
        for part in lexical.parts
    ):
        return None
    current = context.repo_root
    for part in lexical.parts:
        current /= part
        if current.is_symlink():
            return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _strip_user_extensions(text: str) -> str:
    lines = text.splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == "## USER_EXTENSIONS_START"),
        None,
    )
    if start is None:
        return text
    end = next(
        (
            index
            for index, line in enumerate(lines[start + 1 :], start=start + 1)
            if line.strip() == "## USER_EXTENSIONS_END"
        ),
        None,
    )
    if end is None:
        return text
    return "".join([*lines[: start + 1], *lines[end:]])


def _mcp_without_custom_entries(text: str) -> str | None:
    try:
        config = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(config, dict) or not isinstance(config.get("mcpServers"), dict):
        return None
    normalized = dict(config)
    normalized["mcpServers"] = {
        name: entry
        for name, entry in config["mcpServers"].items()
        if not isinstance(name, str) or not name.startswith("custom-")
    }
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _without_vault_mode_gitignore_section(text: str) -> str:
    """Drop the update-managed vault-mode block so only real edits remain.

    A vault's ``.gitignore`` is composed at delivery: the update appends a
    marked section that stops the distribution re-include block from exposing
    Dex's own product files inside the user's private history. Those bytes are
    Dex's, rebuilt on every update, so comparing them against the release blob
    would report the composition itself as user drift.
    """
    from core.update.apply_update import GITIGNORE_MANAGED_SECTION

    return GITIGNORE_MANAGED_SECTION.sub("", text).rstrip("\n")


# Shipped files Dex composes per vault at delivery time: their worktree bytes
# are expected to differ from the release blob, so drift is judged on the
# non-composed remainder instead of a plain byte comparison.
COMPOSED_SHIPPED_PATHS = frozenset({"CLAUDE.md", ".mcp.json", ".gitignore"})


def _only_sanctioned_file_changes(
    context: DoctorContext,
    baseline: str,
    relative: str,
    *,
    git_directory: Path | None = None,
) -> bool:
    baseline_text = _git_file(context, baseline, relative, git_directory=git_directory)
    working_text = _working_file(context, relative)
    if baseline_text is None or working_text is None:
        return False
    if relative == "CLAUDE.md":
        return _strip_user_extensions(baseline_text) == _strip_user_extensions(working_text)
    if relative == ".gitignore":
        return _without_vault_mode_gitignore_section(
            baseline_text
        ) == _without_vault_mode_gitignore_section(working_text)
    if relative == ".mcp.json":
        baseline_config = _mcp_without_custom_entries(baseline_text)
        working_config = _mcp_without_custom_entries(working_text)
        return baseline_config is not None and baseline_config == working_config
    return False


def _release_tree_entries(
    context: DoctorContext,
    baseline: str,
    *,
    git_directory: Path | None = None,
) -> dict[str, tuple[str, str]]:
    output = _git_output_or_raise(
        _git_result(
            context,
            "ls-tree",
            "-r",
            "-z",
            baseline,
            git_directory=git_directory,
        ),
        "list release files",
    )
    entries = {}
    for record in output.split("\0"):
        if not record:
            continue
        metadata, separator, relative = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise RuntimeError("git returned an invalid release tree entry")
        mode, object_type, object_id = fields
        if object_type != "blob":
            entries[relative] = (mode, "")
        else:
            entries[relative] = (mode, object_id)
    return entries


def _worktree_blob_mode_matches(
    context: DoctorContext,
    relative: str,
    mode: str,
) -> bool:
    parts = Path(relative).parts
    if (
        not parts
        or "\n" in relative
        or "\r" in relative
        or any(part in {"", ".", ".."} for part in parts)
    ):
        return False
    current = context.repo_root
    for part in parts[:-1]:
        current /= part
        if current.is_symlink():
            return False
    path = context.repo_root / relative
    try:
        if mode == "120000":
            if not path.is_symlink():
                return False
        elif mode in {"100644", "100755"}:
            if path.is_symlink() or not path.is_file():
                return False
            if bool(path.stat().st_mode & 0o111) != (mode == "100755"):
                return False
        else:
            return False
    except OSError:
        return False
    return True


def _worktree_blob_ids(
    context: DoctorContext,
    relatives: list[str],
) -> dict[str, str]:
    if not relatives:
        return {}
    worktree_ids: dict[str, str] = {}
    for offset in range(0, len(relatives), 128):
        batch = relatives[offset : offset + 128]
        hashed = _git_result(
            context,
            "hash-object",
            "--no-filters",
            "--stdin-paths",
            input_text="".join(f"{relative}\n" for relative in batch),
        )
        if hashed.returncode != 0:
            return {}
        object_ids = hashed.stdout.splitlines()
        if len(object_ids) != len(batch):
            return {}
        worktree_ids.update(zip(batch, object_ids, strict=True))
    return worktree_ids


def _symlink_matches_release_blob(path: Path, object_id: str) -> bool:
    algorithm = (
        "sha1"
        if len(object_id) == 40
        else "sha256"
        if len(object_id) == 64
        else None
    )
    if algorithm is None:
        return False
    try:
        data = os.fsencode(os.readlink(path))
    except OSError:
        return False
    digest = hashlib.new(algorithm)
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest() == object_id


def _mismatched_release_blobs(
    context: DoctorContext,
    entries: dict[str, tuple[str, str]],
) -> set[str]:
    hashable = [
        relative
        for relative, (mode, _object_id) in entries.items()
        if mode != "120000"
        and _worktree_blob_mode_matches(context, relative, mode)
    ]
    worktree_ids = _worktree_blob_ids(context, hashable)
    return {
        relative
        for relative, (mode, object_id) in entries.items()
        if (
            not _worktree_blob_mode_matches(context, relative, mode)
            or (
                mode == "120000"
                and not _symlink_matches_release_blob(
                    context.repo_root / relative,
                    object_id,
                )
            )
            or (mode != "120000" and worktree_ids.get(relative) != object_id)
        )
    }


def _worktree_matches_release_blob(
    context: DoctorContext,
    relative: str,
    mode: str,
    object_id: str,
) -> bool:
    if not _worktree_blob_mode_matches(context, relative, mode):
        return False
    if mode == "120000":
        return _symlink_matches_release_blob(context.repo_root / relative, object_id)
    return _worktree_blob_ids(context, [relative]).get(relative) == object_id


def _is_shipped_drift_candidate(relative: str) -> bool:
    try:
        ownership = portable_contract.resolve(relative).ownership
    except portable_contract.ContractViolation:
        return True
    return ownership not in {"seed", "vault", "runtime"}


def _brain_paths_from_installed_release(
    context: DoctorContext,
    baseline: str,
    brain: Path,
) -> set[str]:
    manifest = _git_file(
        context,
        baseline,
        "System/.installed-files.manifest",
        git_directory=brain,
    )
    if manifest is None:
        raise RuntimeError("installed brain release is missing its manifest")
    paths: set[str] = set()
    for relative in manifest.splitlines():
        try:
            resolution = portable_contract.resolve(relative)
        except portable_contract.ContractViolation as error:
            raise RuntimeError(
                f"installed brain release has an unclassified path: {relative}"
            ) from error
        if resolution.ownership == "brain":
            paths.add(relative)
    return paths


def _package_json_object(raw: str) -> dict[str, object] | None:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def _current_package_json(context: DoctorContext, relative: str) -> dict[str, object] | None:
    path = context.repo_root / relative
    if path.is_symlink() or not path.is_file():
        return None
    try:
        return _package_json_object(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def _installer_normalized_package_metadata(
    context: DoctorContext,
    relative: str,
    baseline: str,
    brain: Path,
) -> bool:
    """Recognize only npm/release-builder changes that cannot alter runtime deps."""

    if relative not in {"package.json", "package-lock.json"}:
        return False
    baseline_raw = _git_file(
        context,
        baseline,
        relative,
        git_directory=brain,
    )
    if baseline_raw is None:
        return False
    baseline_value = _package_json_object(baseline_raw)
    current_value = _current_package_json(context, relative)
    current_package = _current_package_json(context, "package.json")
    if (
        baseline_value is None
        or current_value is None
        or current_package is None
        or not isinstance(current_package.get("version"), str)
    ):
        return False

    if relative == "package.json":
        baseline_scripts = baseline_value.get("scripts")
        current_scripts = current_value.get("scripts")
        if not isinstance(baseline_scripts, Mapping) or not isinstance(
            current_scripts, Mapping
        ):
            return False
        for name, command in baseline_scripts.items():
            if current_scripts.get(name) != command:
                return False
        extra_names = set(current_scripts) - set(baseline_scripts)
        if not extra_names or any(
            name not in INSTALLER_STRIPPED_PACKAGE_SCRIPTS
            or current_scripts[name] != INSTALLER_STRIPPED_PACKAGE_SCRIPTS[name]
            for name in extra_names
        ):
            return False
        normalized = dict(current_value)
        normalized["scripts"] = dict(baseline_scripts)
        return normalized == baseline_value

    baseline_packages = baseline_value.get("packages")
    current_packages = current_value.get("packages")
    if not isinstance(baseline_packages, Mapping) or not isinstance(
        current_packages, Mapping
    ):
        return False
    baseline_root = baseline_packages.get("")
    current_root = current_packages.get("")
    if not isinstance(baseline_root, Mapping) or not isinstance(
        current_root, Mapping
    ):
        return False
    package_version = current_package["version"]
    if (
        current_value.get("version") != package_version
        or current_root.get("version") != package_version
        or not isinstance(baseline_value.get("version"), str)
        or not isinstance(baseline_root.get("version"), str)
    ):
        return False
    normalized = copy.deepcopy(current_value)
    normalized["version"] = baseline_value["version"]
    normalized_packages = normalized["packages"]
    assert isinstance(normalized_packages, dict)
    normalized_root = normalized_packages[""]
    assert isinstance(normalized_root, dict)
    normalized_root["version"] = baseline_root["version"]
    return normalized == baseline_value


def _probe_core_drift(context: DoctorContext) -> ProbeResult:
    if _topology_state(context) == "post-split":
        brain = context.vault_root / ".dex/brain.git"
        baseline = "refs/dex/installed"
        installed = _git_result(
            context,
            "rev-parse",
            "--verify",
            f"{baseline}^{{commit}}",
            git_directory=brain,
        )
        if installed.returncode != 0:
            return ProbeResult(
                "UNKNOWN",
                "the brain Git store cannot resolve refs/dex/installed — rerun /dex-update",
            )
        release_entries = _release_tree_entries(
            context, baseline, git_directory=brain
        )
        brain_paths = _brain_paths_from_installed_release(context, baseline, brain)
        brain_entries = {
            relative: release_entries[relative]
            for relative in brain_paths
            if relative in release_entries
        }
        mismatched = _mismatched_release_blobs(
            context,
            brain_entries,
        )
        drifted = sorted(
            relative
            for relative in mismatched
            if not _installer_normalized_package_metadata(
                context,
                relative,
                baseline,
                brain,
            )
            and not (
                relative in COMPOSED_SHIPPED_PATHS
                and _only_sanctioned_file_changes(
                    context,
                    baseline,
                    relative,
                    git_directory=brain,
                )
            )
        )
        if not drifted:
            return ProbeResult(
                "OK", "No shipped brain files differ from refs/dex/installed"
            )
        return ProbeResult(
            "UNKNOWN",
            "Modified shipped brain files: "
            f"{', '.join(drifted)}; the updater snapshots them before replacement",
        )

    channel = release_channel.read_channel(context.vault_root)
    release_ref = _upstream_release_ref(context, channel)
    if release_ref is None:
        if channel == "beta":
            return ProbeResult(
                "UNKNOWN",
                "beta channel selected but no beta release found — staying on stable is safe",
            )
        if channel == "missing-dependency":
            return ProbeResult("UNKNOWN", "PyYAML isn't installed — Dex can't read your update channel setting")
        if channel == "invalid":
            return ProbeResult("UNKNOWN", "couldn't verify your update channel")
        return ProbeResult("UNKNOWN", "no upstream remote — can't compare")

    # The comparison identity must be the release this vault actually has
    # installed — the same altitude the post-split branch gets from
    # refs/dex/installed. Two other reference points are both wrong: the
    # merge-base can lag what is installed (the legacy updater delivered
    # newer release files without advancing shared history, so
    # release-delivered bytes read as user modifications — issue #242
    # item 2), and the fetched release tip can be newer than what is
    # installed (files half-matching a not-yet-installed release would pass,
    # masking a mixed-version vault). package.json records the installed
    # version and releases are tagged, so the matching tag is the installed
    # identity; merge-base stays the fallback for repos without that tag.
    baseline = _installed_release_treeish(context)
    if baseline is None:
        merge_base = _git_result(context, "merge-base", "HEAD", release_ref)
        baseline = merge_base.stdout.strip() if merge_base.returncode == 0 else release_ref
    release_entries = _release_tree_entries(context, baseline)
    mismatched = _mismatched_release_blobs(context, release_entries)
    candidates = sorted(
        relative
        for relative in mismatched
        if _is_shipped_drift_candidate(relative)
        and not _sanctioned_customization_path(relative)
    )
    drifted = [
        relative
        for relative in candidates
        if relative not in COMPOSED_SHIPPED_PATHS
        or not _only_sanctioned_file_changes(context, baseline, relative)
    ]
    if not drifted:
        return ProbeResult("OK", "No tracked shipped files differ from the installed release")
    return ProbeResult(
        "UNKNOWN",
        "Modified shipped files: "
        f"{', '.join(drifted)}; updates may conflict; the doctor can't vouch for modified shipped files",
    )


def _probe_entity_engine(context: DoctorContext) -> ProbeResult:
    """Report entity tracking, creation, verification, quarantine, and index health."""
    try:
        from core.utils.entity_pages import parse_entity_page

        contacts_path = context.core_path("CONTACTS_STATE_FILE")
        suggestions_path = context.core_path("ENTITY_SUGGESTIONS_FILE")
        verification_path = context.core_path("ENTITY_VERIFICATION_FILE")
        gardener_path = context.core_path("GARDENER_STATE_FILE")
        profile_path = context.core_path("USER_PROFILE_FILE")
        people_dir = context.core_path("PEOPLE_DIR")
        companies_dir = context.core_path("COMPANIES_DIR")
        people_index_path = context.core_path("PEOPLE_INDEX_FILE")
        dead_letter_path = (
            context.vault_root / "System" / ".dex" / "entity-dead-letter.jsonl"
        )

        contacts = json.loads(contacts_path.read_text()) if contacts_path.exists() else {}
        suggestions = json.loads(suggestions_path.read_text()) if suggestions_path.exists() else {}
        verification = json.loads(verification_path.read_text()) if verification_path.exists() else {}
        gardener = json.loads(gardener_path.read_text()) if gardener_path.exists() else {}
        dead_letters = []
        if dead_letter_path.exists():
            for line in dead_letter_path.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    dead_letters.append(entry)
        profile = _load_yaml(profile_path) if profile_path.exists() else {}
        if profile is None:
            profile = {}
        if not isinstance(profile, dict):
            raise ValueError("user-profile.yaml must contain a mapping")

        raw_mode = profile.get("entity_creation", {}).get("mode")
        if raw_mode is False:
            raw_mode = "off"
        mode = raw_mode if raw_mode in {"auto", "suggest", "off"} else "suggest"
        mode_label = mode if raw_mode in {"auto", "suggest", "off"} else "suggest (default — key missing)"
        tracked = len(contacts.get("contacts", {}))
        observations = len(contacts.get("observations", {}))
        suggestion_items = suggestions if isinstance(suggestions, list) else suggestions.get("suggestions", [])
        pending = sum(item.get("status") == "suggested" for item in suggestion_items)
        gardener_pages = gardener.get("pages", {}) if isinstance(gardener, dict) else {}
        gardener_legacy_locked = sum(bool(item.get("locked")) for item in gardener_pages.values())
        gardener_user_owned = sum(
            item.get("blocks", {}).get("context-summary", {}).get("owner") == "user"
            for item in gardener_pages.values()
            if isinstance(item, dict) and isinstance(item.get("blocks", {}), dict)
        )
        if profile.get("entity_gardener", {}).get("enabled") is False:
            gardener_label = "off (disabled)"
        elif not _llm_key_available(context):
            gardener_label = "off (no LLM key)"
        else:
            maintained = sum(bool(item.get("output_hash")) for item in gardener_pages.values())
            gardener_label = f"on ({maintained} pages maintained)"
        if gardener_user_owned:
            label = "user-owned summary" if gardener_user_owned == 1 else "user-owned summaries"
            gardener_label += f", {gardener_user_owned} {label}"
        if gardener_legacy_locked:
            label = "legacy lock" if gardener_legacy_locked == 1 else "legacy locks"
            gardener_label += f", {gardener_legacy_locked} {label} pending migration"

        unresolved = len(verification.get("unresolved", []))
        generated_at = verification.get("generated_at")
        stale = False
        if generated_at:
            verified_at = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
            if verified_at.tzinfo is None:
                verified_at = verified_at.replace(tzinfo=timezone.utc)
            stale = context.now - verified_at.astimezone(timezone.utc) > timedelta(hours=48)

        quarantined_paths = []
        for directory in (people_dir, companies_dir):
            if not directory.exists():
                continue
            for page in directory.rglob("*.md"):
                if page.name != "README.md" and parse_entity_page(page).get("quarantined"):
                    quarantined_paths.append(str(page.relative_to(context.vault_root)))

        newest_people_mtime = max(
            (page.stat().st_mtime for page in people_dir.rglob("*.md") if page.name != "README.md"),
            default=0.0,
        ) if people_dir.exists() else 0.0
        index_freshness = "missing"
        if people_index_path.exists():
            people_index = json.loads(people_index_path.read_text())
            built_at = datetime.fromisoformat(str(people_index.get("built_at", "")).replace("Z", "+00:00"))
            index_freshness = "fresh" if built_at.timestamp() >= newest_people_mtime else "stale"

        verification_label = f"{generated_at or 'never'} / {unresolved} unresolved"
        if stale:
            verification_label += " / stale >48h"
        quarantine_label = str(len(quarantined_paths))
        if quarantined_paths:
            quarantine_label += f" ({', '.join(quarantined_paths[:3])})"
        detail = (
            f"Entity engine tracks {tracked} contacts and {observations} observations; "
            f"creation is {mode_label}; {pending} suggestions pending; last verification "
            f"{verification_label}; {quarantine_label} quarantined pages; people index {index_freshness}"
            f"; gardener {gardener_label}; {len(dead_letters)} dead-lettered writes"
        )
        if dead_letters:
            count = len(dead_letters)
            noun = "entity write" if count == 1 else "entity writes"
            heal_action = (
                "Re-queue the dead-lettered entity write with retry counters reset."
                if count == 1
                else "Re-queue the dead-lettered entity writes with retry counters reset."
            )
            user_message = (
                f"{count} {noun} failed permanently. Run /dex-doctor to re-queue "
                f"{'it' if count == 1 else 'them'} with fresh retries; details remain in "
                "System/.dex/entity-dead-letter.jsonl until then."
            )
            return ProbeResult(
                "BROKEN",
                detail,
                Heal(tier=1, action=heal_action, applied=False),
                feature_status="broken",
                user_message=user_message,
            )
        if unresolved or quarantined_paths:
            return ProbeResult("BROKEN", detail)
        if mode == "off":
            return ProbeResult("OFF", detail)
        return ProbeResult("OK", detail)
    except (ImportError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        return ProbeResult("UNKNOWN", f"Entity engine files could not be checked: {_one_line(error)}")


def _probe_doctor_self(_context: DoctorContext) -> ProbeResult:
    return ProbeResult("OK", "The doctor instrument runner completed")


def _looks_like_sandbox_failure(detail: str) -> bool:
    lowered = detail.lower()
    return any(
        marker in lowered
        for marker in (
            "operation not permitted",
            "sandbox",
            "gpu",
            "metal device",
            "not authorized to send apple events",
            "deny file-read",
        )
    )


def _read_vault_env_values(context: DoctorContext) -> dict[str, str]:
    """Parse the vault-root .env with the shared strict credential parser.

    Delegates decoding to ``integration_credentials.parse_env_assignments`` so
    the doctor sees exactly the values every credential path sees (quoted and
    JSON-escaped values decode identically) instead of keeping a divergent
    dotenv dialect. Returns ``{}`` when the file is absent; a present-but-
    unreadable or unparseable file raises (``OSError``/``UnicodeDecodeError``/
    ``ValueError``) so callers can distinguish "no file" from "cannot read".
    Deliberately does not validate permissions or ownership — the doctor must
    be able to see keys inside a loose-permission .env (that looseness is the
    vault.configs finding, not a reason to go blind).
    """
    from core.utils.integration_credentials import parse_env_assignments

    try:
        raw = (context.vault_root / ".env").read_bytes()
    except FileNotFoundError:
        return {}
    return parse_env_assignments(raw)


LLM_KEY_NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")


def _llm_key_available(context: DoctorContext) -> bool:
    """True when an LLM key exists in the environment or the vault-root .env.

    Presence only: this mirrors how the background LLM consumers resolve keys
    (environment first, then the vault-root .env via dotenv). The key values
    are never returned, logged, or included in any probe detail. An unreadable
    or unparseable .env counts as "no key confirmed" rather than an error, so
    a stray byte in .env can never flip the entity-engine check to UNKNOWN.
    """
    if any((os.environ.get(name) or "").strip() for name in LLM_KEY_NAMES):
        return True
    try:
        values = _read_vault_env_values(context)
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return any(values.get(name) for name in LLM_KEY_NAMES)


def _granola_api_key(context: DoctorContext) -> str | None:
    """Resolve the Granola key: environment first, then the vault-root .env.

    Returns ``None`` only when the key is genuinely absent. A present-but-
    unreadable or unparseable .env raises so the probe surfaces the real cause
    as UNKNOWN instead of telling the user to add a key that is already there.
    """
    configured = os.environ.get("GRANOLA_API_KEY")
    if configured and configured.strip():
        return configured.strip()
    return _read_vault_env_values(context).get("GRANOLA_API_KEY") or None


def _granola_filtered_query(context: DoctorContext) -> list[dict[str, Any]]:
    """Run the exact filtered-list path used by real Granola queries."""
    with _vault_environment(context):
        from core.mcp.granola_server import _cutoff_iso, _list_notes

        return _list_notes(
            created_after=_cutoff_iso(7),
            max_notes=1,
            page_size=1,
        )


def _probe_meeting_sources(context: DoctorContext) -> ProbeResult:
    """Compare the configured meeting-notes source with what actually exists.

    A configured source that quietly stops matching reality is how a meeting
    closeout ends up built from the wrong tool's notes: the vault search finds
    nothing and the model improvises. Config-vs-reality is checkable, so
    check it.
    """
    from core.ritual_intelligence.transcript_ingest import SUPPORTED_TRANSCRIPT_SUFFIXES

    profile_path = context.vault_root / "System/user-profile.yaml"
    if profile_path.is_symlink():
        return ProbeResult(
            "UNKNOWN",
            "The doctor will not follow a symlinked profile to inspect meeting sources",
        )
    try:
        profile = _load_yaml(profile_path)
    except FileNotFoundError:
        profile = {}
    except (OSError, ValueError) as error:
        return ProbeResult("UNKNOWN", f"user-profile.yaml could not be read ({_one_line(error)})")
    if not isinstance(profile, dict):
        return ProbeResult("UNKNOWN", "user-profile.yaml is not a mapping")
    sources = profile.get("meeting_sources")
    if not isinstance(sources, dict):
        return ProbeResult("OFF", "No meeting source is configured")
    folder = sources.get("notes_folder")
    if not isinstance(folder, str) or not folder.strip():
        primary = sources.get("primary")
        if isinstance(primary, str) and primary not in {"", "none"}:
            return ProbeResult("OK", f"Meeting source is {primary} (no notes folder to verify)")
        return ProbeResult("OFF", "No meeting source is configured")
    folder = folder.strip()
    vault_root = context.vault_root.resolve()
    target = (context.vault_root / folder).resolve() if not Path(folder).is_absolute() else Path(folder)
    if (
        Path(folder).is_absolute()
        or ".." in Path(folder).parts
        or target == vault_root
        or not target.is_relative_to(vault_root)
    ):
        # resolve() also closes the symlinked-subfolder escape: a notes_folder
        # whose real location is outside the vault is one no meeting flow reads.
        return ProbeResult(
            "BROKEN",
            "The configured meeting-notes folder must be a folder inside the vault",
            Heal(tier=2, action="Point meeting_sources.notes_folder at a vault folder.", applied=False),
        )
    if not target.is_dir():
        return ProbeResult(
            "BROKEN",
            f"Your meeting notes are configured to live in '{folder}', but that folder does not exist "
            "— meeting skills will search blind and may fall back to the wrong source",
            Heal(tier=2, action="Recreate the folder or update meeting_sources.notes_folder.", applied=False),
        )
    has_note = False
    for current_root, dirnames, filenames in os.walk(target, followlinks=False):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        if any(Path(name).suffix.lower() in SUPPORTED_TRANSCRIPT_SUFFIXES for name in filenames):
            has_note = True
            break
    if not has_note:
        # An empty folder is a young or quiet setup, not a defect: reporting
        # BROKEN would turn a brand-new correct configuration into a critical
        # health snapshot on day one.
        return ProbeResult(
            "UNKNOWN",
            f"The configured meeting-notes folder '{folder}' exists but has no notes yet "
            "— if your meeting tool should already be exporting, check that export",
        )
    return ProbeResult("OK", f"Meeting-notes folder '{folder}' exists and contains notes")


def _probe_post_update_canary(context: DoctorContext) -> ProbeResult:
    """Read the post-update canary's receipt so a failed canary stays visible.

    The canary runs once, right after an update applies; this probe is what
    makes its verdict durable — without a reader, a failed walk through the
    lifecycle doors would be a line in a closed terminal and nothing more.
    """
    from core.health.post_update import RECEIPT_CONTRACT, RECEIPT_RELATIVE

    receipt_path = context.vault_root / RECEIPT_RELATIVE
    if not receipt_path.is_file():
        return ProbeResult("OFF", "No post-update check has run yet (normal before the first update on this version)")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ProbeResult("UNKNOWN", "The post-update check's receipt could not be read")
    if not isinstance(receipt, dict) or receipt.get("contract") != RECEIPT_CONTRACT:
        return ProbeResult("UNKNOWN", "The post-update check's receipt has an unrecognized shape")
    version = receipt.get("dex_version")
    version_text = f" (after updating to {version})" if isinstance(version, str) else ""
    if receipt.get("ok") is True:
        return ProbeResult("OK", f"The last post-update check passed{version_text}")
    error = receipt.get("error")
    detail = f": {error}" if isinstance(error, str) and error else ""
    return ProbeResult(
        "BROKEN",
        f"The last post-update check failed{version_text}{detail} — plan/state operations "
        "did not open after the update applied",
        Heal(tier=2, action="Investigate the lifecycle refusal; /dex-rollback can undo the update.", applied=False),
    )


def _probe_granola_query_path(context: DoctorContext) -> ProbeResult:
    if not _granola_api_key(context):
        return ProbeResult("OFF", "Granola is not connected because no API key is configured")
    try:
        notes = _granola_filtered_query(context)
    except Exception as error:
        from core.mcp.granola_server import GranolaAPIError

        if isinstance(error, GranolaAPIError):
            return ProbeResult(
                "BROKEN",
                error.user_message,
                Heal(tier=3, action="Run /granola-setup to repair the Granola connection.", applied=False),
            )
        if _looks_like_sandbox_failure(_one_line(error)):
            return ProbeResult("UNKNOWN", f"The sandbox blocked the Granola query: {_one_line(error)}")
        raise
    return ProbeResult("OK", f"The real filtered Granola query completed and returned {len(notes)} note summaries")


def _probe_pipedrive_connection(context: DoctorContext) -> ProbeResult:
    """Report the real state of the Pipedrive CRM integration.

    The server already speaks the shared feature_status contract, so this probe
    translates that payload rather than re-deriving configuration rules. On a
    resolvable configuration it then makes one cheap authenticated call, so OK
    means "the stored token actually works" and not merely "the settings parse".
    """
    try:
        from core.integrations.pipedrive import pipedrive_server
    except Exception as error:  # pragma: no cover - import guard
        detail = _one_line(error)
        if _looks_like_sandbox_failure(detail):
            return ProbeResult("UNKNOWN", f"The sandbox blocked the Pipedrive import: {detail}")
        return ProbeResult(
            "BROKEN",
            f"The Pipedrive server could not be imported: {detail}",
            Heal(tier=3, action="Run /pipedrive-setup to repair the Pipedrive connection.", applied=False),
        )

    # The server resolves vault-relative settings from the environment, exactly
    # as it does when launched as an MCP process. Point it at the vault under
    # inspection and restore the caller's environment afterwards.
    previous = os.environ.get("VAULT_ROOT")
    os.environ["VAULT_ROOT"] = str(context.vault_root)
    try:
        resolved = pipedrive_server._resolve()
        if not resolved.get("ok"):
            status = resolved.get("status") or {}
            state = str(status.get("feature_status") or status.get("status") or "unknown")
            message = str(status.get("user_message") or "Pipedrive reported no detail.")
            if state == "off":
                return ProbeResult("OFF", message)
            if state in {"broken", "not_installed"}:
                return ProbeResult(
                    "BROKEN",
                    message,
                    Heal(tier=3, action="Run /pipedrive-setup to repair the Pipedrive connection.", applied=False),
                )
            return ProbeResult("UNKNOWN", message)

        # Configuration resolves. Prove the credential with the cheapest
        # authenticated read Pipedrive offers.
        result = pipedrive_server._request("GET", "users/me", resolved)
    except Exception as error:
        detail = _one_line(error)
        if _looks_like_sandbox_failure(detail):
            return ProbeResult("UNKNOWN", f"The sandbox blocked the Pipedrive check: {detail}")
        raise
    finally:
        if previous is None:
            os.environ.pop("VAULT_ROOT", None)
        else:
            os.environ["VAULT_ROOT"] = previous

    if not result.get("ok"):
        detail = _one_line(result.get("error") or "Pipedrive returned no detail.")
        if _looks_like_sandbox_failure(detail):
            return ProbeResult("UNKNOWN", f"The sandbox blocked the Pipedrive call: {detail}")
        return ProbeResult(
            "BROKEN",
            detail,
            Heal(tier=3, action="Run /pipedrive-setup to repair the Pipedrive connection.", applied=False),
        )

    data = result.get("data") or {}
    who = data.get("name") or data.get("email") or "the configured user"
    company = data.get("company_name")
    suffix = f" ({company})" if company else ""
    return ProbeResult("OK", f"The Pipedrive connection answered a live request as {who}{suffix}")


BACKUP_FRESHNESS_WINDOW = timedelta(days=2)
BACKUP_STAMP_FILENAME = "backup-last-run.json"
_BACKUP_HEAL = Heal(
    tier=3,
    action="Run /backup-setup to repair the backup schedule and take a verified backup.",
    applied=False,
)


def _backup_settings(context: DoctorContext) -> dict[str, Any] | None:
    """Return the backup block from the integrations config, or None."""
    config_path = context.core_path("INTEGRATION_CONFIG_FILE")
    if not config_path.exists():
        return None
    parsed = _load_yaml(config_path) or {}
    if not isinstance(parsed, Mapping):
        raise ValueError("integrations config.yaml must contain an object")
    block = parsed.get("backup")
    return dict(block) if isinstance(block, Mapping) else None


def _backup_stamp_timestamp(stamp: Mapping[str, Any], context: DoctorContext) -> datetime:
    parsed = datetime.fromisoformat(str(stamp["timestamp"]))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=context.now.astimezone().tzinfo)
    return parsed


def _probe_backup_freshness(context: DoctorContext) -> ProbeResult:
    try:
        settings = _backup_settings(context)
    except Exception as error:  # noqa: BLE001 - map sandbox denials to UNKNOWN
        detail = _one_line(error)
        if _looks_like_sandbox_failure(detail):
            return ProbeResult("UNKNOWN", f"The sandbox blocked reading the backup configuration: {detail}")
        raise
    if not settings or not settings.get("enabled"):
        return ProbeResult("OFF", "Vault backups are not configured; /backup-setup turns them on")
    stamp_path = context.core_path("DEX_RUNTIME_DIR") / BACKUP_STAMP_FILENAME
    try:
        raw = stamp_path.read_text()
    except FileNotFoundError:
        return ProbeResult(
            "BROKEN",
            "Backups are configured but have never recorded a run",
            _BACKUP_HEAL,
        )
    except OSError as error:
        detail = _one_line(error)
        if _looks_like_sandbox_failure(detail):
            return ProbeResult("UNKNOWN", f"The sandbox blocked reading the backup run record: {detail}")
        raise
    try:
        stamp = json.loads(raw)
        when = _backup_stamp_timestamp(stamp, context)
    except (ValueError, TypeError, KeyError) as error:
        return ProbeResult("UNKNOWN", f"The backup run record could not be read: {_one_line(error)}")
    if not stamp.get("ok"):
        recorded = _one_line(stamp.get("error") or "no error detail was recorded")
        return ProbeResult("BROKEN", f"The last backup run failed: {recorded}", _BACKUP_HEAL)
    age = context.now - when
    if age > BACKUP_FRESHNESS_WINDOW:
        return ProbeResult(
            "BROKEN",
            f"The newest successful backup is {age.days} days old (recorded {when.date().isoformat()})",
            _BACKUP_HEAL,
        )
    destination = _one_line(stamp.get("location") or stamp.get("backend") or "the configured destination")
    summary = (
        f"The last backup succeeded within the last two days "
        f"(set {_one_line(stamp.get('set') or 'unknown')} to {destination})"
    )
    # A run can succeed and still have stored less than the user expects — a
    # history bundle that could not be built, or linked files a restore cannot
    # unpack. Reporting a bare OK for those would recreate the exact silence
    # this check exists to end.
    warnings = stamp.get("warnings")
    if isinstance(warnings, list) and warnings:
        detail = "; ".join(_one_line(str(item)) for item in warnings[:3])
        return ProbeResult("BROKEN", f"{summary}, but it stored less than a full "
                                     f"backup: {detail}", _BACKUP_HEAL)
    return ProbeResult("OK", summary)


def _calendar_permission_status(_context: DoctorContext) -> str:
    if not _is_macos():
        return "unsupported"
    code = (
        "import EventKit; "
        "print(EventKit.EKEventStore.authorizationStatusForEntityType_(EventKit.EKEntityTypeEvent))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    combined = _one_line(f"{result.stdout} {result.stderr}")
    if result.returncode != 0:
        if _looks_like_sandbox_failure(combined):
            raise PermissionError(combined)
        raise RuntimeError(combined)
    try:
        status = int(result.stdout.strip())
    except ValueError as error:
        raise RuntimeError(f"EventKit returned an invalid authorization status: {combined}") from error
    return {
        0: "not_determined",
        1: "restricted",
        2: "denied",
        3: "authorized",
        4: "write_only",
    }.get(status, f"unknown ({status})")


def _calendar_list_result(context: DoctorContext) -> dict[str, Any]:
    """Call the exact helper behind calendar_list_calendars."""
    with _vault_environment(context):
        from core.mcp.calendar_server import _get_calendar_list_result

        return _get_calendar_list_result()


def _configured_work_calendar(context: DoctorContext) -> str | None:
    profile_path = context.core_path("USER_PROFILE_FILE")
    if not profile_path.exists():
        return None
    profile = _load_yaml(profile_path) or {}
    if not isinstance(profile, dict):
        raise ValueError("user-profile.yaml must contain an object")
    calendar = profile.get("calendar", {})
    if not isinstance(calendar, dict):
        return None
    configured = calendar.get("work_calendar")
    return str(configured).strip() if configured else None


def _probe_calendar_access(context: DoctorContext) -> ProbeResult:
    configured = _configured_work_calendar(context)
    status = _calendar_permission_status(context)
    if status == "unsupported":
        return ProbeResult("UNKNOWN", "EventKit calendar access can only be checked on macOS")
    if status == "not_determined" and not configured:
        return ProbeResult("OFF", "Calendar access has never been requested and no work calendar is configured")
    if status == "write_only":
        return ProbeResult(
            "BROKEN",
            "Calendar permission is write only; Dex needs full calendar access to read calendars",
            Heal(
                tier=3,
                action="Grant Full Calendar Access in System Settings > Privacy & Security > Calendars.",
                applied=False,
            ),
        )
    if status in {"not_determined", "restricted", "denied"}:
        return ProbeResult(
            "BROKEN",
            f"Calendar permission is {status.replace('_', ' ')}",
            Heal(
                tier=3,
                action="Enable Calendar access in System Settings > Privacy & Security > Calendars.",
                applied=False,
            ),
        )
    if status != "authorized":
        return ProbeResult("UNKNOWN", f"EventKit returned an unknown permission status: {status}")

    result = _calendar_list_result(context)
    if not result.get("success"):
        detail = _one_line(result.get("error", "calendar_list_calendars failed"))
        if _looks_like_sandbox_failure(detail):
            return ProbeResult("UNKNOWN", f"The sandbox blocked calendar_list_calendars: {detail}")
        if "denied" in detail.lower() or "permission" in detail.lower():
            return ProbeResult(
                "BROKEN",
                detail,
                Heal(
                    tier=3,
                    action="Enable Calendar access in System Settings > Privacy & Security > Calendars.",
                    applied=False,
                ),
            )
        return ProbeResult("UNKNOWN", f"calendar_list_calendars could not complete: {detail}")

    calendars = [str(name) for name in result.get("calendars", [])]
    if configured and configured not in calendars:
        available = ", ".join(calendars) or "none"
        return ProbeResult(
            "BROKEN",
            f"Configured work calendar '{configured}' was not found; available calendars are {available}",
            Heal(
                tier=3,
                action="Set calendar.work_calendar in System/user-profile.yaml to one of the listed names.",
                applied=False,
            ),
        )
    return ProbeResult("OK", f"Calendar access works and {len(calendars)} calendar names were returned")


def _qmd_registered(config: dict[str, Any]) -> bool:
    for name, entry in config.get("mcpServers", {}).items():
        if not isinstance(entry, dict):
            continue
        command = str(entry.get("command", ""))
        args = [str(argument) for argument in entry.get("args", []) if isinstance(argument, str)]
        if "qmd" in name.lower() or Path(command).name == "qmd" or any(Path(argument).name == "qmd" for argument in args):
            return True
    return False


def _qmd_binary(_context: DoctorContext) -> str | None:
    from core.utils.qmd_query import _find_qmd

    return _find_qmd()


def _qmd_status(binary: str) -> tuple[bool, str]:
    result = subprocess.run(
        [binary, "status"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    detail = _one_line(result.stdout if result.returncode == 0 else result.stderr or result.stdout)
    return result.returncode == 0, detail


def _probe_qmd_live(context: DoctorContext) -> ProbeResult:
    try:
        config = _load_mcp_config(context)
    except FileNotFoundError:
        return ProbeResult("OFF", "qmd is not registered, so semantic search remains opt-in")
    if not _qmd_registered(config):
        return ProbeResult("OFF", "qmd is not registered, so semantic search remains opt-in")
    binary = _qmd_binary(context)
    if not binary:
        return ProbeResult(
            "BROKEN",
            "qmd is registered but its binary is not installed",
            Heal(tier=3, action="Run /enable-semantic-search to install and configure qmd.", applied=False),
        )
    healthy, detail = _qmd_status(binary)
    if not healthy:
        if _looks_like_sandbox_failure(detail):
            return ProbeResult("UNKNOWN", f"The sandbox or GPU environment blocked qmd status: {detail}")
        return ProbeResult(
            "BROKEN",
            f"qmd status failed: {detail}",
            Heal(tier=3, action="Run /enable-semantic-search to repair qmd.", applied=False),
        )
    return ProbeResult("OK", f"qmd status completed successfully: {detail}")


def _enabled_integrations(config: object) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(config, dict):
        raise ValueError("integration config must contain an object")
    enabled: dict[str, dict[str, Any]] = {}
    legacy = config.get("enabled", {})
    if isinstance(legacy, dict):
        for name, value in legacy.items():
            if value is True:
                enabled[str(name)] = {}
    for name, settings in config.items():
        if name == "enabled" or not isinstance(settings, dict):
            continue
        if settings.get("enabled") is True:
            enabled[str(name)] = settings
    return sorted(enabled.items())


def _task_sync_health_check(
    context: DoctorContext,
    name: str,
    settings: dict[str, Any],
) -> tuple[bool, str]:
    runner = context.repo_root / ".claude" / "hooks" / "adapters" / "run.cjs"
    if not runner.is_file():
        raise FileNotFoundError("task-sync adapter runner is not installed")
    node = shutil.which("node")
    if not node:
        raise FileNotFoundError("node is required to run task-sync health checks")
    # Lazy import: it needs PyYAML, and the doctor CLI must still emit JSON when
    # yaml is not importable (test_cli_still_emits_json_when_yaml_is_not_importable).
    from core.utils.integration_credentials import resolve_service_credentials

    credentials = resolve_service_credentials(name, settings, context.vault_root)
    runtime_settings = {**settings, **credentials}
    result = subprocess.run(
        [node, str(runner), name, "health"],
        input=json.dumps({"config": runtime_settings, "args": None}),
        cwd=context.vault_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        detail = _one_line(result.stderr or result.stdout)
        for secret in credentials.values():
            detail = detail.replace(secret, "[REDACTED]")
        if result.returncode != 0:
            return False, detail
        return False, "task-sync adapter returned invalid JSON"
    detail = _one_line(payload.get("error") if isinstance(payload, dict) else result.stderr or result.stdout)
    for secret in credentials.values():
        detail = detail.replace(secret, "[REDACTED]")
    if result.returncode != 0:
        return False, detail
    healthy = (
        isinstance(payload, dict)
        and payload.get("ok") is True
        and isinstance(payload.get("result"), dict)
        and payload["result"].get("healthy") is True
    )
    if not healthy:
        return False, _one_line(payload.get("error") if isinstance(payload, dict) else detail)
    return True, name


def _engine_integration_health(context: DoctorContext) -> tuple[list[dict[str, Any]] | None, str]:
    engine = context.repo_root / "core" / "integrations" / "connection-manager" / "connect.cjs"
    if not engine.is_file():
        return None, "connection manager is not installed"
    node = shutil.which("node")
    if not node:
        raise FileNotFoundError("node is required to inspect engine connections")
    result = subprocess.run(
        [node, str(engine), "status", "--json"],
        cwd=context.vault_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "DEX_VAULT": str(context.vault_root),
        },
    )
    detail = _one_line(result.stderr or result.stdout)
    if result.returncode != 0:
        raise RuntimeError(detail or "connection manager status failed")
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise RuntimeError("connection manager status returned invalid JSON") from error
    connections = payload.get("connections") if isinstance(payload, dict) else None
    if not isinstance(connections, list) or any(not isinstance(row, dict) for row in connections):
        raise RuntimeError("connection manager status returned an invalid connection list")
    return connections, detail


def _probe_integrations_enabled(context: DoctorContext) -> ProbeResult:
    config_path = context.vault_root / "System" / "integrations" / "config.yaml"
    config = (_load_yaml(config_path) or {}) if config_path.exists() else {}
    enabled = list(_enabled_integrations(config))

    failures = []
    unknowns = []
    for name, settings in enabled:
        # Only task-sync services have an automated checker (the adapters' health
        # op). Anything else that is enabled must still fail CLOSED as
        # "can't verify" — never silently drop it (test_split_probe_regression).
        if settings.get("task_sync") is not True:
            unknowns.append(f"{name}: no automated health check available")
            continue
        try:
            healthy, detail = _task_sync_health_check(context, name, settings)
        except Exception as error:
            unknowns.append(f"{name}: {_one_line(error)}")
            continue
        if not healthy:
            if _looks_like_sandbox_failure(detail):
                unknowns.append(f"{name}: {detail}")
            else:
                failures.append(f"{name}: {detail}")
    engine_connections: list[dict[str, Any]] = []
    try:
        engine_rows, _detail = _engine_integration_health(context)
        if engine_rows is not None:
            engine_connections = engine_rows
    except Exception as error:
        detail = _one_line(error)
        if _looks_like_sandbox_failure(detail):
            unknowns.append(f"connection manager: {detail}")
        else:
            failures.append(f"connection manager: {detail}")

    for row in engine_connections:
        service = str(row.get("service") or "unknown")
        status = str(row.get("status") or "unknown")
        if status in {"needs_reauth", "not_connected"}:
            failures.append(f"{service}: {status}")
        elif row.get("verified") is not True:
            unknowns.append(
                f"{service}: stored credential has not been live-verified"
            )
    if failures:
        detail_parts = [f"failed: {'; '.join(failures)}"]
        if unknowns:
            detail_parts.append(f"could not check: {'; '.join(unknowns)}")
        return ProbeResult(
            "BROKEN",
            f"Enabled integration checks {'; '.join(detail_parts)}",
            Heal(tier=3, action="Reconnect the named integration with its setup skill.", applied=False),
        )
    if unknowns:
        return ProbeResult(
            "UNKNOWN",
            f"Enabled integration checks could not run: {'; '.join(unknowns)}",
        )
    checked = [name for name, _settings in enabled]
    checked.extend(str(row.get("service") or "unknown") for row in engine_connections)
    if not checked:
        return ProbeResult("OFF", "No task-sync or engine connections are enabled")
    return ProbeResult("OK", f"Integration health passed for: {', '.join(checked)}")


def _mcp_import_check(
    context: DoctorContext,
    module: str,
    interpreter: str,
) -> tuple[bool, str]:
    executable = _resolved_interpreter(interpreter, context)
    if not executable:
        return False, f"interpreter is missing or not executable: {interpreter}"
    with tempfile.TemporaryDirectory(prefix="dex-doctor-import-") as sandbox:
        env = dict(os.environ)
        env["VAULT_PATH"] = sandbox
        env["VAULT_ROOT"] = sandbox
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(context.vault_root) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
        result = subprocess.run(
            [executable, "-c", f"import importlib; importlib.import_module({module!r})"],
            cwd=context.vault_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    detail = _one_line(result.stderr or result.stdout or f"exit {result.returncode}")
    return result.returncode == 0, detail


def _probe_mcp_importable(context: DoctorContext) -> ProbeResult:
    config = _load_mcp_config(context)
    registered = _registered_core_scripts(context, config)
    failures = []
    for _name, (target, interpreter) in registered.items():
        module = f"core.mcp.{target.stem}"
        importable, detail = _mcp_import_check(context, module, interpreter)
        if not importable:
            failures.append(f"{module}: {detail}")
    if failures:
        return ProbeResult(
            "BROKEN",
            f"Registered MCP imports failed: {'; '.join(failures)}",
            Heal(tier=2, action="Reinstall the missing MCP dependencies into the vault .venv.", applied=False),
        )
    return ProbeResult("OK", f"All {len(registered)} registered core MCP servers import in a subprocess")


def _smoke_timestamp(entry: dict[str, Any]) -> datetime | None:
    value = entry.get("generated_at")
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _valid_smoke_entry(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict) or _smoke_timestamp(value) is None:
        return None
    journeys = value.get("journeys")
    summary = value.get("summary")
    if not isinstance(journeys, list) or not isinstance(summary, dict):
        return None
    if not all(
        isinstance(journey, dict)
        and isinstance(journey.get("id"), str)
        and journey.get("verdict") in VERDICTS
        and isinstance(journey.get("detail"), str)
        for journey in journeys
    ):
        return None
    if not isinstance(summary.get("broken"), int):
        return None
    return value


def _read_smoke_history(context: DoctorContext) -> list[dict[str, Any]]:
    history_path = context.vault_root / "System" / ".dex" / "smoke-history.jsonl"
    last_run_path = context.vault_root / "System" / ".smoke-last-run.json"
    history_unreadable = False
    if history_path.exists():
        lines = history_path.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in lines:
            try:
                entry = _valid_smoke_entry(json.loads(line))
            except (json.JSONDecodeError, TypeError):
                entry = None
            if entry is not None:
                entries.append(entry)
        if entries:
            return sorted(entries, key=lambda entry: _smoke_timestamp(entry) or datetime.min)
        history_unreadable = True
    if last_run_path.exists():
        entry = _valid_smoke_entry(json.loads(last_run_path.read_text(encoding="utf-8")))
        if entry is None:
            raise ValueError("smoke last-run file is unreadable")
        return [entry]
    if history_unreadable:
        raise ValueError("smoke history contains no readable ledger entries")
    return []


def _smoke_attribution_paths(context: DoctorContext) -> list[Path]:
    system = context.vault_root / "System"
    paths_to_check = [
        system / "user-profile.yaml",
        system / "pillars.yaml",
        context.vault_root / ".mcp.json",
    ]
    paths_to_check.extend(sorted((system / "integrations").glob("*.yaml")))
    custom_skills = context.vault_root / ".claude" / "skills"
    paths_to_check.extend(
        path
        for root in sorted(custom_skills.glob("*-custom"))
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )
    return paths_to_check


def _smoke_attribution_name(path: Path, context: DoctorContext) -> str:
    system = context.vault_root / "System"
    try:
        return path.relative_to(system).as_posix()
    except ValueError:
        return path.relative_to(context.vault_root).as_posix()


def _probe_smoke_history(context: DoctorContext) -> ProbeResult:
    history_path = context.vault_root / "System" / ".dex" / "smoke-history.jsonl"
    last_run_path = context.vault_root / "System" / ".smoke-last-run.json"
    if not history_path.exists() and not last_run_path.exists():
        return ProbeResult(
            "OFF",
            "nightly checks not installed — run .scripts/install-smoke-automation.sh",
        )
    try:
        entries = _read_smoke_history(context)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return ProbeResult("UNKNOWN", f"nightly smoke ledger is unreadable: {_one_line(error)}")

    latest = entries[-1]
    latest_timestamp = _smoke_timestamp(latest)
    journeys = latest["journeys"]
    broken = [journey for journey in journeys if journey["verdict"] == "BROKEN"]
    unknown = [journey for journey in journeys if journey["verdict"] == "UNKNOWN"]
    if not broken and not unknown:
        ok_count = sum(journey["verdict"] == "OK" for journey in journeys)
        return ProbeResult(
            "OK",
            f"last verified {latest_timestamp.isoformat()} ({ok_count} journeys OK)",
        )
    if not broken:
        return ProbeResult(
            "UNKNOWN",
            f"last nightly check at {latest_timestamp.isoformat()} was inconclusive",
        )

    prior_good_index = next(
        (
            index
            for index in range(len(entries) - 2, -1, -1)
            if entries[index]["summary"].get("broken") == 0
        ),
        None,
    )
    broken_ids = ", ".join(journey["id"] for journey in broken)
    if prior_good_index is None:
        return ProbeResult(
            "BROKEN",
            f"{broken_ids} is broken as of {latest_timestamp.isoformat()}; no prior passing nightly run is available for attribution",
        )

    good_entry = entries[prior_good_index]
    first_broken = next(
        entry
        for entry in entries[prior_good_index + 1 :]
        if entry["summary"].get("broken", 0) > 0
    )
    window_start = _smoke_timestamp(good_entry)
    window_end = _smoke_timestamp(first_broken)
    facts = []
    for path in _smoke_attribution_paths(context):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if window_start < modified <= window_end:
            facts.append(
                f"{_smoke_attribution_name(path, context)} modified {modified.isoformat()}"
            )
    old_version = good_entry.get("dex_version")
    new_version = first_broken.get("dex_version")
    if isinstance(old_version, str) and isinstance(new_version, str) and old_version != new_version:
        facts.append(f"Dex updated from {old_version} to {new_version} in this window")

    detail = (
        f"{broken_ids} broke between {window_start.isoformat()} and {window_end.isoformat()}. "
        f"In that window: {'; '.join(facts)}"
        if facts
        else (
            f"{broken_ids} broke between {window_start.isoformat()} and {window_end.isoformat()}; "
            "nothing obvious changed — run /dex-doctor --deep for the full picture"
        )
    )
    return ProbeResult("BROKEN", detail)


def _probe_smoke_journeys(context: DoctorContext) -> ProbeResult:
    smoke_path = context.repo_root / "core" / "utils" / "smoke.py"
    vault_python = context.vault_root / ".venv" / "bin" / "python"
    interpreter = (
        str(vault_python)
        if vault_python.is_file() and os.access(vault_python, os.X_OK)
        else sys.executable
    )
    env = {
        name: os.environ[name]
        for name in ("PATH", "PYTHONPATH")
        if name in os.environ
    }
    env.update(
        {
            "VAULT_PATH": str(context.vault_root),
            "VAULT_ROOT": str(context.vault_root),
            "DEX_PYTHON": interpreter,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    result = subprocess.run(
        [interpreter, str(smoke_path), "--json"],
        cwd=context.vault_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    if result.returncode == 2:
        detail = _one_line(result.stderr or result.stdout or "exit 2")
        raise RuntimeError(f"smoke harness failed: {detail}")
    if result.returncode not in {0, 1}:
        detail = _one_line(result.stderr or result.stdout or f"exit {result.returncode}")
        raise RuntimeError(f"smoke harness returned exit {result.returncode}: {detail}")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"smoke harness returned invalid JSON: {_one_line(error)}") from error
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise RuntimeError("smoke harness returned an unsupported report schema")
    journeys = report.get("journeys")
    if not isinstance(journeys, list) or not journeys:
        raise RuntimeError("smoke harness returned no journeys")

    rendered = []
    verdicts = []
    for journey in journeys:
        if not isinstance(journey, dict):
            raise RuntimeError("smoke harness returned a malformed journey")
        journey_id = journey.get("id")
        verdict = journey.get("verdict")
        detail = journey.get("detail")
        if not isinstance(journey_id, str) or verdict not in VERDICTS or not isinstance(detail, str):
            raise RuntimeError("smoke harness returned a malformed journey")
        verdicts.append(verdict)
        rendered.append(f"{journey_id} [{verdict}]: {_one_line(detail)}")

    if "BROKEN" in verdicts:
        worst = "BROKEN"
    elif "UNKNOWN" in verdicts:
        worst = "UNKNOWN"
    elif "OK" in verdicts:
        worst = "OK"
    else:
        worst = "OFF"
    if (result.returncode == 1) != (worst == "BROKEN"):
        raise RuntimeError(
            f"smoke harness exit {result.returncode} did not match its {worst} journey roll-up"
        )
    return ProbeResult(worst, " | ".join(rendered))


def main(argv: list[str] | None = None, *, context: DoctorContext | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deep", action="store_true", help="Run live service probes.")
    parser.add_argument("--heal", action="store_true", help="Apply safe Tier-1 repairs before checking.")
    parser.add_argument("--credential-scan", action="store_true", help="Run the bounded local credential scan.")
    parser.add_argument("--credential-migrate", action="store_true", help="Run safe local credential migration.")
    parser.add_argument("--credential-status", action="store_true", help="Render deterministic credential status.")
    parser.add_argument("--credential-rewind", metavar="JOURNAL_ID", help="Rewind one credential migration journal.")
    args = parser.parse_args(argv)

    try:
        credential_actions = [
            ("scan", args.credential_scan, None),
            ("migrate", args.credential_migrate, None),
            ("status", args.credential_status, None),
            ("rewind", args.credential_rewind is not None, args.credential_rewind),
        ]
        selected = [item for item in credential_actions if item[1]]
        if len(selected) > 1:
            parser.error("choose only one credential workflow action")
        if selected:
            from core.utils.credential_workflow import run_credential_workflow

            action, _, journal_id = selected[0]
            root = context.vault_root if context is not None else paths.VAULT_ROOT
            credential_report = run_credential_workflow(root, action, journal_id=journal_id)
            print(json.dumps(credential_report, indent=2))
            return 2 if credential_report.get("migration_state") == "refused" and action != "status" else 0
        report = collect(deep=args.deep, heal=args.heal, context=context)
        output = json.dumps(report, indent=2)
    except Exception as error:
        print(f"dex-doctor could not produce JSON: {_one_line(error)}", file=sys.stderr)
        return 1

    if args.deep:
        _publish_health_snapshot(report, context)
    print(output)
    return 0


def _publish_health_snapshot(report: dict[str, Any], context: DoctorContext | None) -> None:
    """Best-effort: publish a completed deep report as the latest health snapshot.

    This is the store's production writer — the session-start health surface
    and the mid-session pulse both read the latest snapshot, so a Doctor deep
    run is what refreshes the answer they glance at.  Only a complete
    (deep) registry normalizes into a snapshot; failures never disturb the
    prior snapshot or the Doctor report the user is reading.
    """
    try:
        from core.health.doctor_reporter import from_doctor_report
        from core.health.snapshot import HealthStore

        refresh_id = f"doctor-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        normalized = from_doctor_report(report, refresh_id=refresh_id)
        if not normalized.accepted:
            return
        root = context.vault_root if context is not None else paths.VAULT_ROOT
        store = HealthStore(root)
        with store.refresh(refresh_id) as refresh:
            refresh.publish(normalized)
    except Exception:  # noqa: BLE001 - publication must never break a Doctor run
        return


if __name__ == "__main__":
    raise SystemExit(main())
