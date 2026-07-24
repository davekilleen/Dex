"""Human-invoked consent-side adapter for customization migration."""

from __future__ import annotations

import argparse
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m core.customization_migration.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("assess")
    commands.add_parser("preview")
    create = commands.add_parser("create")
    create.add_argument("--confirm-token")
    abandon = commands.add_parser("abandon")
    abandon.add_argument("capsule_id")
    abandon.add_argument("--acknowledge", action="store_true")
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
            if not capsules:
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
