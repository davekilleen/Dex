"""Move leftover developer files aside with a preview, confirm token, and restore."""

from __future__ import annotations

import hashlib
import json
import stat
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from core.customization_migration.model import Assessment
from core.customization_migration.service import (
    MigrationServiceError,
    assess,
    canonical_json_bytes,
    resolve_vault_root,
)
from core.dev_only import (
    archive_dir_for,
    archived_source_path,
    is_dev_leftover_archive_path,
)
from core.lifecycle.filesystem import (
    STOCK_HASH_MAX_BYTES,
    FilesystemInspectionError,
    bounded_read,
)
from core.transaction.engine import PlanEntry, Transaction

Clock = Callable[[], datetime]
_MANIFEST_NAME = "manifest.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(clock: Clock) -> str:
    moment = clock()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")


def leftover_paths(assessment: Assessment) -> tuple[str, ...]:
    return tuple(
        exclusion.path
        for exclusion in assessment.exclusions
        if exclusion.reason == "dev-only-leftover"
    )


def _inspect_file(root: Path, relative: str) -> tuple[bytes, str, int]:
    target = root / relative
    try:
        metadata = target.lstat()
    except OSError as error:
        raise MigrationServiceError(
            "leftover-unreadable",
            "A leftover file could not be read.",
        ) from error
    if stat.S_ISLNK(metadata.st_mode):
        raise MigrationServiceError(
            "symlink-refused",
            "A leftover is a symlink, so nothing was moved.",
        )
    if not stat.S_ISREG(metadata.st_mode):
        raise MigrationServiceError(
            "leftover-unreadable",
            "A leftover is not a regular file, so nothing was moved.",
        )
    try:
        raw = bounded_read(root, relative, max_bytes=STOCK_HASH_MAX_BYTES)
    except FilesystemInspectionError as error:
        raise MigrationServiceError(
            "leftover-unreadable",
            "A leftover file could not be read.",
        ) from error
    return raw, hashlib.sha256(raw).hexdigest(), len(raw)


def preview_tidy_dev_leftovers(
    vault_root: Path,
    *,
    clock: Clock = _utc_now,
) -> dict[str, object]:
    """Build a confirm-token-bound preview. Never writes."""
    root = resolve_vault_root(vault_root)
    assessment = assess(root)
    archive_dir = archive_dir_for(_stamp(clock))
    files: list[dict[str, object]] = []
    for path in leftover_paths(assessment):
        _raw, digest, size = _inspect_file(root, path)
        files.append(
            {
                "path": path,
                "sha256": digest,
                "size": size,
                "archived_path": archived_source_path(archive_dir, path),
            }
        )
    # Token binds the leftover set, not the clock-derived folder name, so a
    # dry-run and the later confirm still match when a second has passed.
    token_payload = {
        "files": [
            {"path": item["path"], "sha256": item["sha256"], "size": item["size"]}
            for item in files
        ]
    }
    digest = hashlib.sha256(canonical_json_bytes(token_payload)).hexdigest()
    return {
        "archive_dir": archive_dir,
        "files": files,
        "preview_sha256": digest,
    }


def apply_tidy_dev_leftovers(
    vault_root: Path,
    confirm_token: str,
    *,
    clock: Clock = _utc_now,
) -> dict[str, object]:
    """Move leftover files into the dated archive after the token matches."""
    root = resolve_vault_root(vault_root)
    preview = preview_tidy_dev_leftovers(root, clock=clock)
    if confirm_token != preview["preview_sha256"]:
        raise MigrationServiceError(
            "confirm-token-mismatch",
            "Nothing was moved. Run the dry-run again and pass its preview SHA-256.",
        )
    files = preview["files"]
    assert isinstance(files, list)
    archive_dir = str(preview["archive_dir"])
    if not files:
        return {
            "archive_dir": archive_dir,
            "moved": 0,
            "manifest_path": None,
        }
    manifest_files = [
        {"path": item["path"], "sha256": item["sha256"], "size": item["size"]}
        for item in files
    ]
    manifest = {
        "schema_version": 1,
        "archive_dir": archive_dir,
        "files": manifest_files,
    }
    manifest_raw = canonical_json_bytes(manifest)
    plan: list[PlanEntry] = [
        PlanEntry(
            f"{archive_dir}/{_MANIFEST_NAME}",
            manifest_raw,
            mode=0o600,
            expected_absent=True,
        )
    ]
    for item in files:
        path = str(item["path"])
        raw, digest, size = _inspect_file(root, path)
        if digest != item["sha256"] or size != item["size"]:
            raise MigrationServiceError(
                "leftover-drifted",
                "A leftover file changed after the preview, so nothing was moved.",
            )
        plan.append(
            PlanEntry(
                str(item["archived_path"]),
                raw,
                mode=0o644,
                expected_absent=True,
            )
        )
        plan.append(
            PlanEntry(
                path,
                None,
                expected_current_sha256=digest,
            )
        )
    transaction = Transaction.begin(
        root,
        plan,
        operation="dev-leftover-tidy",
    )
    transaction.run()
    return {
        "archive_dir": archive_dir,
        "moved": len(files),
        "manifest_path": f"{archive_dir}/{_MANIFEST_NAME}",
        "transaction_id": transaction.tx_id,
    }


def _resolve_archive_dir(root: Path, archive_dir: str) -> str:
    relative = archive_dir.strip().replace("\\", "/")
    if relative.startswith("./"):
        relative = relative[2:]
    if not is_dev_leftover_archive_path(relative):
        raise MigrationServiceError(
            "invalid-archive",
            "Restore only accepts a Dex leftover archive folder.",
        )
    if (
        Path(relative).is_absolute()
        or any(part in {"", ".", ".."} for part in Path(relative).parts)
    ):
        raise MigrationServiceError(
            "invalid-archive",
            "Restore only accepts a Dex leftover archive folder.",
        )
    target = root / relative
    if target.is_symlink() or not target.is_dir():
        raise MigrationServiceError(
            "invalid-archive",
            "The leftover archive folder is missing or is not a real directory.",
        )
    return relative


def restore_dev_leftovers(vault_root: Path, archive_dir: str) -> dict[str, object]:
    """Move archived leftovers back to their original paths, byte-identical."""
    root = resolve_vault_root(vault_root)
    relative = _resolve_archive_dir(root, archive_dir)
    manifest_path = f"{relative}/{_MANIFEST_NAME}"
    try:
        raw = bounded_read(root, manifest_path, max_bytes=STOCK_HASH_MAX_BYTES)
        document = json.loads(raw.decode("utf-8"))
    except (FilesystemInspectionError, UnicodeError, json.JSONDecodeError) as error:
        raise MigrationServiceError(
            "invalid-archive",
            "The leftover archive manifest could not be read.",
        ) from error
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise MigrationServiceError(
            "invalid-archive",
            "The leftover archive manifest is not a recognised restore record.",
        )
    files = document.get("files")
    if not isinstance(files, list):
        raise MigrationServiceError(
            "invalid-archive",
            "The leftover archive manifest is not a recognised restore record.",
        )
    plan: list[PlanEntry] = []
    for item in files:
        if not isinstance(item, dict):
            raise MigrationServiceError(
                "invalid-archive",
                "The leftover archive manifest is not a recognised restore record.",
            )
        source_path = item.get("path")
        digest = item.get("sha256")
        size = item.get("size")
        if (
            not isinstance(source_path, str)
            or not isinstance(digest, str)
            or type(size) is not int
        ):
            raise MigrationServiceError(
                "invalid-archive",
                "The leftover archive manifest is not a recognised restore record.",
            )
        archived = archived_source_path(relative, source_path)
        payload, actual_digest, actual_size = _inspect_file(root, archived)
        if actual_digest != digest or actual_size != size:
            raise MigrationServiceError(
                "archive-drifted",
                "An archived leftover no longer matches its manifest, so nothing was restored.",
            )
        if (root / source_path).exists():
            raise MigrationServiceError(
                "restore-blocked",
                "A leftover path already exists, so nothing was restored.",
            )
        plan.append(
            PlanEntry(
                source_path,
                payload,
                mode=0o644,
                expected_absent=True,
            )
        )
        plan.append(
            PlanEntry(
                archived,
                None,
                expected_current_sha256=digest,
            )
        )
    plan.append(
        PlanEntry(
            manifest_path,
            None,
            mode=0o600,
            expected_current_sha256=hashlib.sha256(raw).hexdigest(),
        )
    )
    if len(plan) == 1:
        # Manifest-only archive: still remove the manifest so restore is a
        # complete undo of an empty tidy.
        pass
    transaction = Transaction.begin(
        root,
        plan,
        operation="dev-leftover-tidy",
    )
    transaction.run()
    return {
        "archive_dir": relative,
        "restored": len(files),
        "transaction_id": transaction.tx_id,
    }


def preview_to_lines(preview: dict[str, object]) -> list[str]:
    files = preview["files"]
    assert isinstance(files, list)
    # FOUNDER COPY - DRAFT PENDING APPROVAL (DEX-277).
    lines = [
        "Tidy dev-only leftovers",
        f"Archive: {preview['archive_dir']}",
        f"Files: {len(files)}",
        f"Preview SHA-256: {preview['preview_sha256']}",
    ]
    for item in files:
        lines.append(f"{item['path']} ({item['size']} bytes) -> {item['archived_path']}")
    return lines


__all__ = [
    "apply_tidy_dev_leftovers",
    "leftover_paths",
    "preview_tidy_dev_leftovers",
    "preview_to_lines",
    "restore_dev_leftovers",
]
