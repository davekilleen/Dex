#!/usr/bin/env python3
"""Collect an honest, machine-readable health report for Dex."""

from __future__ import annotations

import argparse
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
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

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
from core.transaction.engine import TX_ROOT_RELATIVE, PlanEntry
from core.transaction.journal import Journal, JournalCorruptError
from core.utils import preflight, release_channel

VERDICTS = frozenset({"OK", "OFF", "BROKEN", "UNKNOWN"})
DOCTOR_SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
DOCTOR_GIT_CANDIDATES = (Path("/usr/bin/git"), Path("/bin/git"))
MISSING_PACKAGES_DETAIL = (
    "Python packages not installed — run /dex-update (or pip install -r requirements.txt) "
    "then re-run /dex-doctor"
)
RELEASE_CATALOG_PATH = "System/.release-catalog.json"
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


@dataclass(frozen=True)
class JobFreshness:
    """The application log and allowed age for one installed job."""

    log_path: Path
    max_age: timedelta


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

# Keep in sync with .claude/hooks/session-start.sh's background-job staleness table.
JOB_FRESHNESS = {
    "com.dex.smoke-nightly": JobFreshness(
        Path(".scripts/logs/smoke-nightly.log"),
        timedelta(hours=26),
    ),
    "com.dex.meeting-intel": JobFreshness(
        Path(".scripts/logs/meeting-intel.log"),
        timedelta(hours=48),
    ),
    "com.dex.changelog-checker": JobFreshness(
        Path(".scripts/logs/changelog-checker.log"),
        timedelta(days=7),
    ),
    "com.dex.learning-review": JobFreshness(
        Path(".scripts/logs/learning-review.log"),
        timedelta(days=7),
    ),
}

# Ownership includes every launch agent this repo can install; only some emit freshness logs.
SHIPPED_LAUNCH_AGENT_LABELS = frozenset(
    {
        "com.dex.changelog-checker",
        "com.dex.learning-review",
        "com.dex.meeting-intel",
        "com.dex.obsidian-sync",
        "com.dex.smoke-nightly",
    }
)


QUICK_CHECKS = (
    CheckDefinition("vault.structure", "Vault structure", "_probe_vault_structure"),
    CheckDefinition("vault.configs", "Vault configuration", "_probe_vault_configs"),
    CheckDefinition("vault.git", "Vault history", "_probe_vault_git"),
    CheckDefinition("brain.git", "Dex brain history", "_probe_brain_git"),
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
    CheckDefinition("granola.query_path", "Granola meeting sync", "_probe_granola_query_path"),
    CheckDefinition("calendar.access", "Calendar access", "_probe_calendar_access"),
    CheckDefinition("qmd.live", "Semantic search", "_probe_qmd_live"),
    CheckDefinition("integrations.enabled", "Enabled integrations", "_probe_integrations_enabled"),
    CheckDefinition("mcp.importable", "MCP imports", "_probe_mcp_importable"),
    CheckDefinition("smoke.journeys", "End-to-end smoke journeys", "_probe_smoke_journeys"),
)


def _one_line(value: object) -> str:
    return " ".join(str(value).split()) or value.__class__.__name__


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


def _apply_t1_heals(context: DoctorContext) -> tuple[list[str], list[str]]:
    """Preview and apply contract-authorized Tier-1 repairs through the service."""
    actions: list[str] = []
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

    dead_letter_path = context.vault_root / "System" / ".dex" / "entity-dead-letter.jsonl"
    if dead_letter_path.exists():
        try:
            healed = _requeue_entity_dead_letters(context)
            requeued = healed["requeued"]
            if requeued:
                noun = "write" if requeued == 1 else "writes"
                actions.append(
                    f"re-queued {requeued} dead-lettered entity {noun} with retry counters reset"
                )
        except Exception as error:
            errors.append(f"Entity-write heal failed: {_one_line(error)}")

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
                actions.append("regenerated core/paths.json")
            if planned_executables:
                noun = "permission" if len(planned_executables) == 1 else "permissions"
                actions.append(
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

    t1_actions: list[str] = []
    if heal:
        try:
            t1_actions, t1_errors = _apply_t1_heals(context)
            if t1_errors:
                failed.append({"id": "doctor.self", "error": "; ".join(t1_errors)})
        except Exception as error:
            failed.append({"id": "doctor.self", "error": _one_line(error)})

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
        entity_actions = [
            action for action in t1_actions if action.startswith("re-queued ")
        ]
        structure_actions = [
            action for action in t1_actions if not action.startswith("re-queued ")
        ]
        if definition.id == "vault.structure" and structure_actions:
            action = "; ".join(structure_actions) + "."
            if result.verdict == "OK":
                repair_word = _repair_count_word(len(structure_actions))
                repair_noun = "repair" if len(structure_actions) == 1 else "repairs"
                detail = f"All standard PARA directories exist after {repair_word} safe {repair_noun}"
            else:
                detail = f"{result.detail.rstrip('.')} while safe Tier-1 repairs were also applied"
            result = ProbeResult(
                result.verdict,
                detail,
                Heal(tier=1, action=action, applied=True),
            )
        if definition.id == "entity.engine" and entity_actions:
            result = ProbeResult(
                result.verdict,
                result.detail,
                Heal(tier=1, action="; ".join(entity_actions) + ".", applied=True),
                feature_status=result.feature_status,
                user_message=result.user_message,
            )
        results[definition.id] = result

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
    if failures:
        return ProbeResult(
            "BROKEN",
            "; ".join(failures),
            Heal(tier=3, action="Repair the named configuration file by hand.", applied=False),
        )
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
    """Build and summarize the adoption plan entirely in memory."""
    catalog_path = _release_catalog_path(context)
    if not os.path.lexists(catalog_path):
        return ProbeResult(
            "OFF",
            "Adoption planning is unavailable on this older Dex release because no release catalog is installed",
        )
    try:
        catalog = load_catalog(catalog_path, release_root=context.vault_root)
        inventory = build_inventory(context.vault_root, catalog=catalog)
        plan = build_adoption_plan(catalog, inventory)
        counts = plan.counts
        return ProbeResult(
            "OK",
            f"{counts['adopt']} adoptable / {counts['already-adopted']} adopted / "
            f"{counts['conflict']} conflicts",
        )
    except Exception as error:
        return ProbeResult("UNKNOWN", f"The adoption plan could not be built: {_one_line(error)}")


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


def _installed_launch_agents(context: DoctorContext) -> list[Path]:
    return sorted(context.launch_agents_dir.glob("com.dex.*.plist"))


def _plist_data(plist: Path) -> dict[str, Any]:
    try:
        with plist.open("rb") as handle:
            loaded = plistlib.load(handle)
    except PermissionError:
        raise
    except (OSError, plistlib.InvalidFileException) as error:
        raise RuntimeError(f"Could not parse {plist.name}: {_one_line(error)}") from error
    if not isinstance(loaded, dict):
        raise RuntimeError(f"Could not parse {plist.name}: top level is not a dictionary")
    return loaded


def _plist_label(plist: Path) -> str:
    return str(_plist_data(plist).get("Label") or plist.stem)


def _plist_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _plist_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _plist_strings(child)


def _plist_owned_by_vault(plist: Path, data: dict[str, Any], context: DoctorContext) -> bool:
    label = str(data.get("Label") or plist.stem)
    if label in SHIPPED_LAUNCH_AGENT_LABELS:
        return True
    arguments = data.get("ProgramArguments")
    if not isinstance(arguments, list):
        return False
    vault_root = context.vault_root.resolve()
    for argument in arguments:
        if not isinstance(argument, str):
            continue
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
        return {"loaded": False, "last_exit_status": None}
    match = re.search(r"LastExitStatus\D+(-?\d+)", result.stdout)
    return {
        "loaded": True,
        "last_exit_status": int(match.group(1)) if match else None,
    }


def _resolved_interpreter(raw: str, context: DoctorContext) -> str | None:
    expanded = _expand_path_token(raw, context)
    if "/" not in expanded:
        return shutil.which(expanded)
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = context.vault_root / candidate
    return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None


def _probe_jobs_loaded(context: DoctorContext) -> ProbeResult:
    plists = _installed_launch_agents(context)
    if not plists:
        return ProbeResult("OFF", "No com.dex launch agents are installed")
    if not _is_macos():
        return ProbeResult("UNKNOWN", "launchctl and plutil checks are only available on macOS")

    issues: list[tuple[int, str]] = []
    unknowns = []
    runtime_labels = []
    skipped_count = 0
    for plist in plists:
        try:
            data = _plist_data(plist)
        except RuntimeError as error:
            if plist.stem in SHIPPED_LAUNCH_AGENT_LABELS:
                issues.append((2, _one_line(error)))
            else:
                skipped_count += 1
            continue
        if not _plist_owned_by_vault(plist, data, context):
            skipped_count += 1
            continue
        label = str(data.get("Label") or plist.stem)
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
                elif status["last_exit_status"] is None:
                    unknowns.append(f"{label} is loaded but has no observable LastExitStatus")
                elif status["last_exit_status"] != 0:
                    issues.append((2, f"{label} last exited with status {status['last_exit_status']}"))
    owned_count = len(plists) - skipped_count
    if not owned_count:
        return ProbeResult(
            "OFF",
            _with_skipped_launch_agents("No launch agents for this vault are installed", skipped_count),
        )
    if issues:
        tier = max(issue_tier for issue_tier, _detail in issues)
        action_parts = []
        if any(issue_tier == 3 for issue_tier, _detail in issues):
            action_parts.append("Install or repair the missing job interpreter by hand")
        if any(issue_tier == 2 for issue_tier, _detail in issues):
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
    installed = {_plist_label(plist) for plist in _installed_launch_agents(context)}
    monitored = [label for label in JOB_FRESHNESS if label in installed]
    if not monitored:
        return ProbeResult("OFF", "No monitored Dex freshness jobs are installed")

    stale = []
    for label in monitored:
        policy = JOB_FRESHNESS[label]
        log_path = context.vault_root / policy.log_path
        if not log_path.is_file():
            stale.append(f"{label} has no run log")
            continue
        modified = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc)
        if context.now.astimezone(timezone.utc) - modified > policy.max_age:
            stale.append(f"{label} last ran on {modified.date().isoformat()}")
    if stale:
        return ProbeResult(
            "BROKEN",
            "; ".join(stale),
            Heal(tier=2, action="Run the stale job once and inspect its application log.", applied=False),
        )
    return ProbeResult("OK", f"All {len(monitored)} installed job logs are within their freshness thresholds")


def _preflight_snapshot(context: DoctorContext) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with _vault_environment(context):
        health = preflight.run_preflight()
        queue_path = preflight.get_error_queue_path()
        queued = json.loads(queue_path.read_text()) if queue_path.exists() else []
    if not isinstance(queued, list):
        raise ValueError("the preflight error queue must contain a list")
    return health, queued


def _probe_preflight_queue(context: DoctorContext) -> ProbeResult:
    health, queued = _preflight_snapshot(context)
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
        error.get("humanMessage") or error.get("message") or "queued background error"
        for error in queued
        if not error.get("acknowledged", False)
    ]
    problems = [*server_errors, *queued_errors]
    if problems:
        detail = f"Preflight reported: {'; '.join(str(problem) for problem in problems)}"
        if unknown_core_servers:
            detail += f"; preflight did not check: {', '.join(sorted(unknown_core_servers))}"
        return ProbeResult("BROKEN", detail)
    if unknown_core_servers:
        return ProbeResult(
            "UNKNOWN",
            f"Preflight did not check registered core servers: {', '.join(sorted(unknown_core_servers))}",
        )
    return ProbeResult("OK", "Preflight completed with no server or queued errors")


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
        (path for path in skills_root.iterdir() if path.is_symlink() or path.is_dir()),
        key=lambda path: path.name,
    ) if skills_root.is_dir() else []
    failures = []
    safety_findings = []
    custom_count = 0
    for skill_directory in skill_directories:
        skill_path = skill_directory / "SKILL.md"
        relative = _display_vault_path(context, skill_path)
        is_custom = skill_directory.name.endswith("-custom")
        custom_count += int(is_custom)
        safety_reason = _unsafe_customization_path(context, skill_path)
        if safety_reason:
            if is_custom:
                safety_findings.append(
                    f"user customization {relative} {safety_reason} and was not read for safety; "
                    f"fix or remove {relative}"
                )
            else:
                safety_findings.append(
                    f"shipped skill {relative} {safety_reason} and was not read for safety; "
                    f"run /dex-update to restore {relative}"
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
                f"shipped skill {relative} is invalid ({issue}); run /dex-update to restore {relative}"
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
        env={
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": "/var/empty" if Path("/var/empty").is_dir() else "/",
            "LC_ALL": "C",
            "PATH": DOCTOR_SAFE_PATH,
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
    vault_git = context.vault_root / ".git"
    brain_git = context.vault_root / ".dex/brain.git"
    topology = _regular_json(context.vault_root / "System/.dex/topology.json")
    vault_marker = _regular_json(vault_git / "dex-vault-v2")
    brain_marker = _regular_json(brain_git / "dex-brain-v2")
    if topology and topology.get("topology") == "brain-vault-split":
        environment = topology.get("environment")
        wired_vault = environment.get("DEX_VAULT") if isinstance(environment, dict) else None
        try:
            vault_wiring_matches = (
                isinstance(wired_vault, str)
                and Path(wired_vault).resolve() == context.vault_root.resolve()
            )
        except OSError:
            vault_wiring_matches = False
        if (
            topology.get("vaultGitDir") == ".git"
            and topology.get("brainGitDir") == ".dex/brain.git"
            and vault_wiring_matches
            and vault_git.is_dir()
            and not vault_git.is_symlink()
            and brain_git.is_dir()
            and not brain_git.is_symlink()
            and vault_marker
            and vault_marker.get("role") == "vault"
            and brain_marker
            and brain_marker.get("role") == "brain"
        ):
            return "post-split"
        return "invalid-split"
    migration_state = _regular_json(
        context.vault_root / "System/.dex/migration-v2-state.json"
    )
    if migration_state and migration_state.get("status") != "complete":
        return "migration-in-progress"
    if any(
        candidate.exists()
        for candidate in (
            context.vault_root / ".dex/pre-split-archive.git",
            context.vault_root / ".dex/vault-staging.git",
        )
    ):
        return "migration-in-progress"
    migrator = context.vault_root / "core/migrations/v1-to-v2-brain-vault-split.cjs"
    if vault_git.exists() and migrator.is_file() and not migrator.is_symlink():
        return "migration-pending"
    if not vault_git.exists():
        return "zip-or-manual"
    return "combined"


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
            "BROKEN",
            "Dex needs its one-time brain/vault upgrade — run /dex-update; notes stay in place",
        )
    if topology == "migration-in-progress":
        return ProbeResult(
            "BROKEN",
            "The one-time upgrade is incomplete — run /dex-update so recovery can resume",
        )
    if topology == "invalid-split":
        return ProbeResult(
            "BROKEN",
            "The split topology markers or DEX_VAULT wiring disagree — use updater or migrator recovery, never raw Git",
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


def _only_sanctioned_file_changes(
    context: DoctorContext,
    baseline: str,
    relative: str,
) -> bool:
    baseline_text = _git_file(context, baseline, relative)
    working_text = _working_file(context, relative)
    if baseline_text is None or working_text is None:
        return False
    if relative == "CLAUDE.md":
        return _strip_user_extensions(baseline_text) == _strip_user_extensions(working_text)
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


def _worktree_matches_release_blob(
    context: DoctorContext,
    relative: str,
    mode: str,
    object_id: str,
) -> bool:
    parts = Path(relative).parts
    if not parts or any(
        part in {"", ".", ".."}
        or part.lower() == ".env"
        or part.lower().startswith(".env.")
        or "credential" in part.lower()
        for part in parts
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
            data = os.readlink(path).encode("utf-8")
        elif mode in {"100644", "100755"}:
            if path.is_symlink() or not path.is_file():
                return False
            data = path.read_bytes()
            if bool(path.stat().st_mode & 0o111) != (mode == "100755"):
                return False
        else:
            return False
    except (OSError, UnicodeError):
        return False

    algorithm = "sha1" if len(object_id) == 40 else "sha256" if len(object_id) == 64 else None
    if algorithm is None:
        return False
    digest = hashlib.new(algorithm)
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest() == object_id


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
        drifted = sorted(
            relative
            for relative in brain_paths
            if relative in release_entries
            and not _worktree_matches_release_blob(
                context,
                relative,
                *release_entries[relative],
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
        if channel == "invalid":
            return ProbeResult("UNKNOWN", "couldn't verify your update channel")
        return ProbeResult("UNKNOWN", "no upstream remote — can't compare")

    merge_base = _git_result(context, "merge-base", "HEAD", release_ref)
    baseline = merge_base.stdout.strip() if merge_base.returncode == 0 else release_ref
    release_entries = _release_tree_entries(context, baseline)
    candidates = sorted(
        relative
        for relative, (mode, object_id) in release_entries.items()
        if not _sanctioned_customization_path(relative)
        and not _worktree_matches_release_blob(context, relative, mode, object_id)
    )
    drifted = [
        relative
        for relative in candidates
        if not _only_sanctioned_file_changes(context, baseline, relative)
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
        elif not any(os.environ.get(key) for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")):
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


def _granola_api_key(context: DoctorContext) -> str | None:
    configured = os.environ.get("GRANOLA_API_KEY")
    if configured and configured.strip():
        return configured.strip()
    env_path = context.vault_root / ".env"
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        name, separator, value = line.partition("=")
        if not separator or name.strip() != "GRANOLA_API_KEY":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


def _granola_filtered_query(context: DoctorContext) -> list[dict[str, Any]]:
    """Run the exact filtered-list path used by real Granola queries."""
    with _vault_environment(context):
        from core.mcp.granola_server import _cutoff_iso, _list_notes

        return _list_notes(
            created_after=_cutoff_iso(7),
            max_notes=1,
            page_size=1,
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


def _integration_checker_command(
    context: DoctorContext,
    name: str,
    settings: dict[str, Any],
) -> list[str]:
    configured = settings.get("health_checker") or settings.get("health_check")
    if isinstance(configured, list) and all(isinstance(part, str) for part in configured):
        return [_expand_path_token(part, context) for part in configured]
    if isinstance(configured, str):
        checker = Path(_expand_path_token(configured, context))
        if not checker.is_absolute():
            checker = context.vault_root / checker
        return [shutil.which("node") or "node", str(checker)]

    candidates = (
        context.vault_root / "core" / "integrations" / name / "connection.cjs",
        context.vault_root / ".scripts" / "integrations" / name / "connection.cjs",
        context.vault_root / ".scripts" / name / "connection.cjs",
        context.vault_root / ".claude" / "skills" / f"{name}-setup" / "connection.cjs",
    )
    checker = next((candidate for candidate in candidates if candidate.is_file()), None)
    if checker is None:
        raise FileNotFoundError(f"no existing {name} connection health checker was found")
    node = shutil.which("node")
    if not node:
        raise FileNotFoundError("node is required to run integration connection checkers")
    return [node, str(checker)]


def _integration_health_check(
    context: DoctorContext,
    name: str,
    settings: dict[str, Any],
) -> tuple[bool, str]:
    command = _integration_checker_command(context, name, settings)
    result = subprocess.run(
        command,
        cwd=context.vault_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    detail = _one_line(result.stdout if result.returncode == 0 else result.stderr or result.stdout)
    if result.returncode != 0:
        return False, detail
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return True, detail
    if isinstance(payload, dict):
        for key in ("healthy", "success", "ok", "connected"):
            if payload.get(key) is False:
                return False, _one_line(payload.get("error") or payload.get("message") or detail)
    return True, detail


def _probe_integrations_enabled(context: DoctorContext) -> ProbeResult:
    config_path = context.vault_root / "System" / "integrations" / "config.yaml"
    if not config_path.exists():
        return ProbeResult("OFF", "No integrations are enabled")
    config = _load_yaml(config_path) or {}
    enabled = _enabled_integrations(config)
    if not enabled:
        return ProbeResult("OFF", "No integrations are enabled")

    failures = []
    unknowns = []
    for name, settings in enabled:
        try:
            healthy, detail = _integration_health_check(context, name, settings)
        except Exception as error:
            unknowns.append(f"{name}: {_one_line(error)}")
            continue
        if not healthy:
            if _looks_like_sandbox_failure(detail):
                unknowns.append(f"{name}: {detail}")
            else:
                failures.append(f"{name}: {detail}")
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
    names = ", ".join(name for name, _settings in enabled)
    return ProbeResult("OK", f"Existing health checkers passed for enabled integrations: {names}")


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
    env = {
        name: os.environ[name]
        for name in ("PATH", "PYTHONPATH")
        if name in os.environ
    }
    env.update(
        {
            "VAULT_PATH": str(context.vault_root),
            "VAULT_ROOT": str(context.vault_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    result = subprocess.run(
        [sys.executable, str(smoke_path), "--json"],
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

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
