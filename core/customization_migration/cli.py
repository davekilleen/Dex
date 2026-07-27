"""Human-confirmed customization migration adapter.

Confirmation tokens bind exact previews; they are integrity values, not secrets.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from core.customization_migration import service as migration_service


def canonical_assessment_bytes(vault_root: Path) -> bytes:
    return migration_service.canonical_json_bytes(
        migration_service.assess_to_dict(vault_root)
    )


def _preview_lines(preview: dict[str, object]) -> list[str]:
    files = preview["files"]
    assert isinstance(files, list)
    byte_total = sum(int(item["byte_size"]) for item in files)
    return [
        f"Capsule ID: {preview['capsule_id']}",
        f"Files: {len(files)}",
        f"Bytes: {byte_total}",
        f"Preview SHA-256: {preview['preview_sha256']}",
    ]


def _safe_field_lines(
    authority: dict[str, object],
    fields: tuple[str, ...],
) -> list[str]:
    return [
        f"{field}: {_render_value(authority[field])}"
        for field in fields
        if field in authority
    ]


def _render_value(value: object) -> str:
    if isinstance(value, (dict, list)) or value is None or type(value) is bool:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    return str(value)


def _staging_preview_lines(preview: dict[str, object]) -> list[str]:
    files = preview["files"]
    candidate = preview["candidate"]
    assert isinstance(files, list)
    assert isinstance(candidate, dict)
    dispositions = candidate["dispositions"]
    assert isinstance(dispositions, list)
    return [
        f"Capsule ID: {preview['capsule_id']}",
        f"Proposal ID: {preview['proposal_id']}",
        *(f"Live path after activation: {item['target_path']}" for item in files),
        *(
            "Disposition: "
            f"{item['customization_id']} = {item['disposition']}"
            for item in dispositions
        ),
        f"Preview SHA-256: {preview['preview_sha256']}",
    ]


def _activation_preview_lines(preview: dict[str, object]) -> list[str]:
    files = preview["files"]
    dispositions = preview["dispositions"]
    assert isinstance(files, list)
    assert isinstance(dispositions, list)
    return [
        f"Capsule ID: {preview['capsule_id']}",
        f"Proposal ID: {preview['proposal_id']}",
        *(f"Live path: {item['target_path']}" for item in files),
        *(
            "Disposition: "
            f"{item['customization_id']} = {item['disposition']}"
            for item in dispositions
        ),
        f"Snapshot retention: {preview['snapshot_retention_note']}",
        f"Rewind: {preview['rewind_note']}",
        f"Approval token: {preview['approval_token']}",
    ]


def _rewind_preview_lines(preview: dict[str, object]) -> list[str]:
    files = preview["files"]
    assert isinstance(files, list)
    lines = [
        f"Capsule ID: {preview['capsule_id']}",
        f"Proposal ID: {preview['proposal_id']}",
        f"Status: {preview['status']}",
        f"Reason: {preview['reason']}",
        *(
            "Restore path: "
            f"{item['path']} "
            f"(existed before activation: {_render_value(item['existed_before_activation'])})"
            for item in files
        ),
    ]
    token = preview["acknowledgement_token"]
    if token is not None:
        lines.append(f"Acknowledgement token: {token}")
    return lines


def _verification_preview_lines(preview: dict[str, object]) -> list[str]:
    return _safe_field_lines(
        preview,
        (
            "confirm_token",
            "capsule_id",
            "proposal_id",
            "staging_receipt_sha256",
            "report_sha256",
            "verdict",
            "static_file_count",
            "behavioural_contract_count",
        ),
    )


_CAPSULE_RECEIPT_FIELDS = (
    "capsule_id",
    "manifest_sha256",
    "file_count",
    "byte_count",
    "transaction_id",
)
_STAGING_RECEIPT_FIELDS = (
    "capsule_id",
    "proposal_id",
    "staged_file_count",
    "staged_byte_count",
    "staging_digest",
    "transaction_id",
)
_VERIFICATION_RECEIPT_FIELDS = (
    "capsule_id",
    "staging_id",
    "report_sha256",
    "transaction_id",
)
_ACTIVATION_STATUS_FIELDS = (
    "capsule_id",
    "proposal_id",
    "state",
    "reason",
    "activation_receipt_present",
    "rewindable",
)
_ACTIVATION_RECEIPT_FIELDS = (
    "capsule_id",
    "proposal_id",
    "verification_report_sha256",
    "candidate_sha256",
    "file_count",
    "transaction_id",
    "activated_epoch_seconds",
    "rewind_available",
)
_REWIND_RECEIPT_FIELDS = (
    "capsule_id",
    "proposal_id",
    "activation_transaction_id",
    "rewind_transaction_id",
    "status",
    "reason",
    "file_count",
    "rewound_epoch_seconds",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m core.customization_migration.cli"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("assess")
    commands.add_parser("preview")
    create = commands.add_parser("create")
    create.add_argument("--confirm-token")
    abandon = commands.add_parser("abandon")
    abandon.add_argument("capsule_id")
    abandon.add_argument("--acknowledge", action="store_true")
    stage = commands.add_parser("stage")
    stage.add_argument("candidate_json")
    stage.add_argument("--confirm-token")
    verify = commands.add_parser("verify")
    verify.add_argument("capsule_id")
    verify.add_argument("proposal_id")
    verify.add_argument("--confirm-token")
    preview_activation = commands.add_parser("preview-activation")
    preview_activation.add_argument("capsule_id")
    preview_activation.add_argument("proposal_id")
    activate = commands.add_parser("activate")
    activate.add_argument("capsule_id")
    activate.add_argument("proposal_id")
    activate.add_argument("--confirm-token")
    preview_rewind = commands.add_parser("preview-rewind")
    preview_rewind.add_argument("capsule_id")
    rewind = commands.add_parser("rewind")
    rewind.add_argument("capsule_id")
    rewind.add_argument("--acknowledge-token")
    activation_status = commands.add_parser("activation-status")
    activation_status.add_argument("capsule_id")
    recover = commands.add_parser("recover")
    recover.add_argument("--confirm-token")
    return parser


def _root() -> Path:
    return migration_service.resolve_vault_root(os.environ.get("VAULT_PATH"))


def run(arguments: list[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        root = _root()
        if options.command == "status":
            status = migration_service.migration_status_to_dict(root)
            capsules = status["capsules"]
            recovery_actions = status.get("recovery_actions", [])
            if not capsules and not recovery_actions:
                print("No customization capsules exist.")
                return 0
            for capsule in capsules:
                validation = capsule["validation"]
                state = str(capsule["state"]).replace("-", " ")
                print(
                    f"Capsule {capsule['capsule_id']} is {state}; "
                    f"validation is {validation['status']}."
                )
            if status["truncated"]:
                print("More capsules exist than this status view can safely show.")
            for recovery in recovery_actions:
                print(f"Recovery phase: {recovery['phase']}")
                print(f"Recovery capsule: {recovery['capsule_id']}")
                if recovery["proposal_id"] is not None:
                    print(f"Recovery proposal: {recovery['proposal_id']}")
                print(f"Recovery action: {recovery['action']}")
            return 0
        if options.command == "assess":
            assessment = migration_service.assess_to_dict(root)
            if assessment["verdict"] != "OK":
                print(
                    "Nothing could be verified, so no customization counts are shown."
                )
                return 0
            records = assessment["records"]
            edges = assessment["edges"]
            groups = Counter(item["group"] for item in assessment["groups"])
            print(
                f"Verified {len(records)} customizations and "
                f"{len(edges)} dependencies."
            )
            if groups:
                print(
                    "Groups: "
                    + ", ".join(
                        f"{name.replace('-', ' ')}: {count}"
                        for name, count in sorted(groups.items())
                    )
                    + "."
                )
            return 0
        if options.command == "preview":
            print("\n".join(_preview_lines(migration_service.preview_to_dict(root))))
            return 0
        if options.command == "create":
            preview = migration_service.preview_to_dict(root)
            print("\n".join(_preview_lines(preview)))
            if options.confirm_token != preview["preview_sha256"]:
                print(
                    "Nothing was created. Run this command again with "
                    f"--confirm-token {preview['preview_sha256']}"
                )
                return 2
            receipt = migration_service.create_confirmed_capsule(
                root, options.confirm_token
            )
            print(f"Created capsule {receipt.capsule_id}.")
            print(
                "\n".join(
                    _safe_field_lines(
                        receipt.to_dict(),
                        _CAPSULE_RECEIPT_FIELDS,
                    )
                )
            )
            return 0
        if options.command == "abandon":
            if not options.acknowledge:
                print(
                    f"This would abandon capsule {options.capsule_id}. "
                    "Run again with --acknowledge to append that event."
                )
                return 2
            migration_service.abandon_existing_capsule(root, options.capsule_id)
            print(f"Capsule {options.capsule_id} is now abandoned.")
            return 0
        if options.command == "stage":
            candidate = migration_service.load_regeneration_candidate(
                options.candidate_json
            )
            preview = migration_service.preview_staging_to_dict(root, candidate)
            print("\n".join(_staging_preview_lines(preview)))
            if options.confirm_token != preview["preview_sha256"]:
                print(
                    "Nothing was staged. Run this command again with "
                    f"--confirm-token {preview['preview_sha256']}"
                )
                return 2
            receipt = migration_service.stage_confirmed_candidate(
                root,
                candidate,
                options.confirm_token,
            )
            print(
                "\n".join(
                    _safe_field_lines(
                        receipt.to_dict(),
                        _STAGING_RECEIPT_FIELDS,
                    )
                )
            )
            return 0
        if options.command == "verify":
            preview = migration_service.preview_verification_to_dict(
                root,
                options.capsule_id,
                options.proposal_id,
            )
            print("\n".join(_verification_preview_lines(preview)))
            if options.confirm_token != preview["confirm_token"]:
                print(
                    "Nothing was sealed. Run this command again with "
                    f"--confirm-token {preview['confirm_token']}"
                )
                return 2
            verification = migration_service.verify_staging_to_dict(
                root,
                options.capsule_id,
                options.proposal_id,
                options.confirm_token,
            )
            report = verification["report"]
            receipt = verification["receipt"]
            assert isinstance(report, dict)
            assert isinstance(receipt, dict)
            print(
                "\n".join(
                    _safe_field_lines(
                        report,
                        ("capsule_id", "proposal_id", "verdict"),
                    )
                )
            )
            print(
                "\n".join(
                    _safe_field_lines(
                        receipt,
                        _VERIFICATION_RECEIPT_FIELDS,
                    )
                )
            )
            return 0
        if options.command in {"preview-activation", "activate"}:
            preview = migration_service.preview_activation_to_dict(
                root,
                options.capsule_id,
                options.proposal_id,
            )
            print("\n".join(_activation_preview_lines(preview)))
            if options.command == "preview-activation":
                return 0
            if options.confirm_token != preview["approval_token"]:
                print(
                    "Nothing was activated. Run this command again with "
                    f"--confirm-token {preview['approval_token']}"
                )
                return 2
            receipt = migration_service.activate_confirmed(
                root,
                options.capsule_id,
                options.proposal_id,
                options.confirm_token,
            )
            receipt_dict = receipt.to_dict()
            receipt_dict["file_count"] = len(receipt.files_written)
            print(
                "\n".join(
                    _safe_field_lines(
                        receipt_dict,
                        _ACTIVATION_RECEIPT_FIELDS,
                    )
                )
            )
            return 0
        if options.command == "activation-status":
            status = migration_service.activation_status_to_dict(
                root,
                options.capsule_id,
            )
            print(
                "\n".join(
                    _safe_field_lines(
                        status,
                        _ACTIVATION_STATUS_FIELDS,
                    )
                )
            )
            return 0
        if options.command in {"preview-rewind", "rewind"}:
            preview = migration_service.preview_rewind_to_dict(
                root,
                options.capsule_id,
            )
            print("\n".join(_rewind_preview_lines(preview)))
            if options.command == "preview-rewind":
                return 0
            token = preview["acknowledgement_token"]
            if options.acknowledge_token != token or token is None:
                if token is None:
                    print("Nothing was rewound because rewind is not available.")
                else:
                    print(
                        "Nothing was rewound. Run this command again with "
                        f"--acknowledge-token {token}"
                    )
                return 2
            receipt = migration_service.rewind_acknowledged(
                root,
                options.capsule_id,
                options.acknowledge_token,
            )
            receipt_dict = receipt.to_dict()
            receipt_dict["file_count"] = len(receipt.files_restored)
            print(
                "\n".join(
                    _safe_field_lines(
                        receipt_dict,
                        _REWIND_RECEIPT_FIELDS,
                    )
                )
            )
            return 0
        if options.command == "recover":
            preview = migration_service.recovery_preview_to_dict(root)
            actions = preview["recovery_actions"]
            token = preview["recovery_token"]
            if not actions or token is None:
                print("No interrupted customization transaction needs recovery.")
                return 0
            for recovery in actions:
                print(f"Recovery phase: {recovery['phase']}")
                print(f"Recovery capsule: {recovery['capsule_id']}")
                if recovery["proposal_id"] is not None:
                    print(f"Recovery proposal: {recovery['proposal_id']}")
                print(f"Recovery action: {recovery['action']}")
            if options.confirm_token != token:
                print(
                    "Nothing was recovered. Run this command again with "
                    f"--confirm-token {token}"
                )
                return 2
            result = migration_service.recover_confirmed(
                root,
                options.confirm_token,
            )
            for recovered in result["recovered"]:
                print(f"Recovered phase: {recovered['phase']}")
                print(f"Recovery status: {recovered['status']}")
                print(
                    "Restored file count: "
                    f"{recovered['restored_file_count']}"
                )
            return 0
    except migration_service.MigrationServiceError as error:
        print(error.message)
        return 2
    except Exception:
        print("The customization migration command could not complete safely.")
        return 2
    return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
