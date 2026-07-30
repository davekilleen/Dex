#!/usr/bin/env python3
"""Read-only stdio adapter for customization migration evidence."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from pathlib import Path
from types import MappingProxyType

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# Add the vault root to sys.path so `from core.*` resolves when this server is
# launched as a bare file path (core/mcp/<this file> → three parents up).
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.customization_migration import service as migration_service
from core.customization_migration.capsule_model import EVIDENCE_SECTIONS_V0
from core.utils.feature_status import feature_status

_FEATURE = "customization-migration"
_MAX_ARRAY_ITEMS = 500
_MAX_PAGE_ITEMS = 100
_MAX_PAGE_BYTES = 256 * 1024
_COMPLETE_VIA = "read_customization_capsule_section"
_CONFIRMATION_GUIDANCE = (
    "use the Dex CLI preview command to obtain the confirmation token"
)

app = Server("dex-customization-migration-mcp")


def _root() -> Path:
    return migration_service.resolve_vault_root(os.environ.get("VAULT_PATH"))


def _text(payload: dict[str, object]) -> list[types.TextContent]:
    return [
        types.TextContent(
            type="text",
            text=json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    ]


def _error(code: str, message: str, *, state: str = "broken"):
    return _text(
        feature_status(
            _FEATURE,
            state,
            message,
            error={"code": code, "message": message},
        )
    )


def _closed_arguments(
    arguments: object,
    *,
    allowed: frozenset[str],
    required: frozenset[str] = frozenset(),
) -> dict[str, object]:
    if not isinstance(arguments, dict):
        raise migration_service.MigrationServiceError(
            "malformed-arguments", "Arguments must be a JSON object."
        )
    if not set(arguments).issubset(allowed) or not required.issubset(arguments):
        raise migration_service.MigrationServiceError(
            "malformed-arguments", "Arguments do not match the closed tool schema."
        )
    return arguments


def _bounded_assessment(value: dict[str, object]) -> tuple[dict[str, object], bool]:
    result = copy.deepcopy(value)
    records = result.get("records")
    truncated = isinstance(records, list) and len(records) > _MAX_ARRAY_ITEMS
    if truncated:
        result["records"] = records[:_MAX_ARRAY_ITEMS]
    return result, truncated


def _bounded_preview(value: dict[str, object]) -> tuple[dict[str, object], bool]:
    result = copy.deepcopy(value)
    result.pop("preview_sha256", None)
    result["confirmation"] = _CONFIRMATION_GUIDANCE
    truncated = False
    files = result.get("files")
    if isinstance(files, list) and len(files) > _MAX_ARRAY_ITEMS:
        result["files"] = files[:_MAX_ARRAY_ITEMS]
        truncated = True
    assessment = result.get("assessment")
    if isinstance(assessment, dict):
        result["assessment"], assessment_truncated = _bounded_assessment(assessment)
        truncated = truncated or assessment_truncated
    return result, truncated


def canonical_assessment_bytes(vault_root: Path) -> bytes:
    return migration_service.canonical_json_bytes(
        migration_service.assess_to_dict(vault_root)
    )


def _page(records: list[object], cursor: int) -> tuple[list[object], int | None]:
    page: list[object] = []
    index = cursor
    while index < len(records) and len(page) < _MAX_PAGE_ITEMS:
        candidate = [*page, records[index]]
        if len(migration_service.canonical_json_bytes(candidate)) > _MAX_PAGE_BYTES:
            if not page:
                raise migration_service.MigrationServiceError(
                    "record-too-large", "One evidence record exceeds the page limit."
                )
            break
        page = candidate
        index += 1
    return page, None if index == len(records) else index


def _capsule_status_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "capsule_id": {
                "type": "string",
                "pattern": "^cap-[0-9a-f]{16}$",
            },
        },
        "required": ["capsule_id"],
        "additionalProperties": False,
    }


_EMPTY_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
_CAPSULE_SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "capsule_id": {"type": "string", "pattern": "^cap-[0-9a-f]{16}$"},
        "section": {
            "type": "string",
            "enum": sorted(EVIDENCE_SECTIONS_V0),
        },
        "cursor": {"type": "integer", "minimum": 0},
    },
    "required": ["capsule_id", "section"],
    "additionalProperties": False,
}
_CAPSULE_BLOB_SCHEMA = {
    "type": "object",
    "properties": {
        "capsule_id": {"type": "string", "pattern": "^cap-[0-9a-f]{16}$"},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
    "required": ["capsule_id", "sha256"],
    "additionalProperties": False,
}
TOOL_REGISTRY = MappingProxyType(
    {
        tool.name: tool
        for tool in (
            types.Tool(
                name="assess_customizations",
                description="Assess vault customizations without changing the vault.",
                inputSchema=_EMPTY_SCHEMA,
            ),
            types.Tool(
                name="preview_customization_capsule",
                description=(
                    "Preview a protected evidence capsule without creating it."
                ),
                inputSchema=_EMPTY_SCHEMA,
            ),
            types.Tool(
                name="read_customization_migration_status",
                description="Read capsule states and validation verdicts.",
                inputSchema=_EMPTY_SCHEMA,
            ),
            types.Tool(
                name="read_staging_status",
                description=(
                    "Read staged proposal states and verification verdicts."
                ),
                inputSchema=_capsule_status_schema(),
            ),
            types.Tool(
                name="read_activation_status",
                description=(
                    "Read activation, receipt-presence, and rewindable status."
                ),
                inputSchema=_capsule_status_schema(),
            ),
            types.Tool(
                name="read_customization_capsule_section",
                description=(
                    "Read one bounded page from one existing capsule section."
                ),
                inputSchema=_CAPSULE_SECTION_SCHEMA,
            ),
            types.Tool(
                name="read_customization_capsule_blob",
                description=(
                    "Read one digest-bound, sensitivity-gated Capsule blob as "
                    "bounded UTF-8 text."
                ),
                inputSchema=_CAPSULE_BLOB_SCHEMA,
            ),
        )
    }
)


@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return list(TOOL_REGISTRY.values())


@app.call_tool()
async def handle_call_tool(
    name: str,
    arguments: dict[str, object] | None,
) -> list[types.TextContent]:
    if name not in TOOL_REGISTRY:
        return _error("unknown-tool", "The requested tool is not available.")
    try:
        if name == "assess_customizations":
            _closed_arguments(arguments or {}, allowed=frozenset())
            assessment, truncated = _bounded_assessment(
                migration_service.assess_to_dict(_root())
            )
            state = "ok" if assessment.get("verdict") == "OK" else "unknown"
            extra: dict[str, object] = {"assessment": assessment}
            if truncated:
                extra.update(truncated=True, complete_via=_COMPLETE_VIA)
            return _text(
                feature_status(
                    _FEATURE,
                    state,
                    (
                        "Customization assessment is complete."
                        if state == "ok"
                        else (
                            "Customization assessment is partial; review the listed "
                            "exclusions before creating a Capsule."
                            if assessment.get("partial") is True
                            else "Customization assessment could not be verified."
                        )
                    ),
                    **extra,
                )
            )
        if name == "preview_customization_capsule":
            _closed_arguments(arguments or {}, allowed=frozenset())
            preview, truncated = _bounded_preview(
                migration_service.preview_to_dict(_root())
            )
            extra = {"preview": preview}
            if truncated:
                extra.update(truncated=True, complete_via=_COMPLETE_VIA)
            return _text(
                feature_status(
                    _FEATURE,
                    "ok",
                    "Customization capsule preview is ready.",
                    **extra,
                )
            )
        if name == "read_customization_migration_status":
            _closed_arguments(arguments or {}, allowed=frozenset())
            return _text(
                feature_status(
                    _FEATURE,
                    "ok",
                    "Customization migration status was read.",
                    migration_status=migration_service.migration_status_to_dict(_root()),
                )
            )
        if name in {"read_staging_status", "read_activation_status"}:
            values = _closed_arguments(
                arguments or {},
                allowed=frozenset({"capsule_id"}),
                required=frozenset({"capsule_id"}),
            )
            capsule_id = values["capsule_id"]
            if not isinstance(capsule_id, str):
                raise migration_service.MigrationServiceError(
                    "malformed-arguments", "capsule_id must be a string."
                )
            if name == "read_staging_status":
                return _text(
                    feature_status(
                        _FEATURE,
                        "ok",
                        "Customization staging status was read.",
                        staging_status=migration_service.staging_status_to_dict(
                            _root(),
                            capsule_id,
                        ),
                    )
                )
            return _text(
                feature_status(
                    _FEATURE,
                    "ok",
                    "Customization activation status was read.",
                    activation_status=migration_service.activation_status_to_dict(
                        _root(),
                        capsule_id,
                    ),
                )
            )
        if name == "read_customization_capsule_section":
            values = _closed_arguments(
                arguments or {},
                allowed=frozenset({"capsule_id", "section", "cursor"}),
                required=frozenset({"capsule_id", "section"}),
            )
            capsule_id = values["capsule_id"]
            section = values["section"]
            if not isinstance(capsule_id, str):
                raise migration_service.MigrationServiceError(
                    "malformed-arguments", "capsule_id must be a string."
                )
            if not isinstance(section, str):
                raise migration_service.MigrationServiceError(
                    "malformed-arguments", "section must be a string."
                )
            if section not in EVIDENCE_SECTIONS_V0:
                raise migration_service.MigrationServiceError(
                    "invalid-section", "section is not supported."
                )
            cursor = values.get("cursor", 0)
            if type(cursor) is not int:
                raise migration_service.MigrationServiceError(
                    "invalid-cursor", "cursor must be an integer offset."
                )
            records, digest = migration_service.read_section_records(
                _root(), capsule_id, section
            )
            if cursor < 0 or cursor > len(records):
                raise migration_service.MigrationServiceError(
                    "invalid-cursor", "cursor is outside the section record range."
                )
            page, next_cursor = _page(records, cursor)
            return _text(
                feature_status(
                    _FEATURE,
                    "ok",
                    "Customization capsule evidence page was read.",
                    capsule_id=capsule_id,
                    section=section,
                    section_digest=digest,
                    total_record_count=len(records),
                    records=page,
                    next_cursor=next_cursor,
                    complete=next_cursor is None,
                )
            )
        if name == "read_customization_capsule_blob":
            values = _closed_arguments(
                arguments or {},
                allowed=frozenset({"capsule_id", "sha256"}),
                required=frozenset({"capsule_id", "sha256"}),
            )
            capsule_id = values["capsule_id"]
            sha256 = values["sha256"]
            if not isinstance(capsule_id, str) or not isinstance(sha256, str):
                raise migration_service.MigrationServiceError(
                    "malformed-arguments",
                    "capsule_id and sha256 must be strings.",
                )
            blob = migration_service.read_capsule_blob_text(
                _root(),
                capsule_id,
                sha256,
            )
            return _text(
                feature_status(
                    _FEATURE,
                    "ok",
                    "Customization capsule blob text was read.",
                    **blob,
                )
            )
        return _error("operation-failed", "The registered tool has no handler.")
    except migration_service.MigrationServiceError as error:
        state = "unknown" if error.code == "invalid-vault-root" else "broken"
        return _error(error.code, error.message, state=state)
    except Exception:
        return _error(
            "operation-failed",
            "The customization migration check could not be completed safely.",
            state="unknown",
        )


async def _main() -> None:
    _root()
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-customization-migration-mcp",
                server_version="0.1.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
