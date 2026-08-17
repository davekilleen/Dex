"""Crash-safe transaction seam for first-run vault provisioning.

The Node provisioner supplies one closed plan.  This module validates that
plan, recovers any interrupted Core transaction, and executes every file
mutation through the existing lifecycle transaction engine.  The completion
marker and onboarding-session deletion therefore share one durable commit.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from core import portable_contract
from core.lifecycle import service
from core.transaction.engine import TX_ROOT_RELATIVE, PlanEntry, Transaction
from core.transaction.journal import Journal

SCHEMA_VERSION = 1
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProvisionTransactionError(RuntimeError):
    """The first-run mutation plan could not be proved or committed safely."""


def _closed(
    value: object,
    fields: set[str],
    context: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ProvisionTransactionError(f"{context} must be an object")
    missing = fields - set(value)
    unknown = set(value) - fields
    if missing or unknown:
        raise ProvisionTransactionError(
            f"{context} fields disagree (missing={sorted(missing)}, unknown={sorted(unknown)})"
        )
    return value


def _relative(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise ProvisionTransactionError(f"{context} must be a string")
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or candidate.as_posix() != value
    ):
        raise ProvisionTransactionError(f"{context} is not a canonical vault-relative path")
    return value


def _decode_entry(raw: object, index: int) -> PlanEntry:
    entry = _closed(
        raw,
        {
            "path",
            "action",
            "content_base64",
            "mode",
            "expected_current_sha256",
            "expected_absent",
        },
        f"provision entry {index}",
    )
    relative = _relative(entry["path"], f"provision entry {index} path")
    action = entry["action"]
    mode = entry["mode"]
    expected_current = entry["expected_current_sha256"]
    expected_absent = entry["expected_absent"]
    if action not in {"write", "delete"}:
        raise ProvisionTransactionError(f"provision entry {index} action is invalid")
    if type(mode) is not int or mode < 0 or mode > 0o777:
        raise ProvisionTransactionError(f"provision entry {index} mode is invalid")
    if expected_current is not None and (
        not isinstance(expected_current, str) or _HEX_SHA256.fullmatch(expected_current) is None
    ):
        raise ProvisionTransactionError(
            f"provision entry {index} current-content hash is invalid"
        )
    if type(expected_absent) is not bool:
        raise ProvisionTransactionError(
            f"provision entry {index} expected_absent must be boolean"
        )

    content: bytes | None
    if action == "delete":
        if entry["content_base64"] is not None or expected_current is None or expected_absent:
            raise ProvisionTransactionError(
                f"provision entry {index} deletion preconditions are invalid"
            )
        content = None
    else:
        encoded = entry["content_base64"]
        if not isinstance(encoded, str):
            raise ProvisionTransactionError(
                f"provision entry {index} write payload is missing"
            )
        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ProvisionTransactionError(
                f"provision entry {index} write payload is not canonical base64"
            ) from error
        if base64.b64encode(content).decode("ascii") != encoded:
            raise ProvisionTransactionError(
                f"provision entry {index} write payload is not canonical base64"
            )
        if expected_absent == (expected_current is not None):
            raise ProvisionTransactionError(
                f"provision entry {index} must bind either current bytes or exact absence"
            )

    verdict = portable_contract.update_write_verdict(
        relative,
        exists=expected_current is not None,
        operation="onboarding-provision",
    )
    if not verdict.allowed:
        raise ProvisionTransactionError(f"{relative}: {verdict.action}")
    return PlanEntry(
        relative,
        content,
        mode=mode,
        expected_current_sha256=expected_current,
        expected_absent=expected_absent,
    )


def _decode_plan(document: object) -> list[PlanEntry]:
    plan = _closed(
        document,
        {"schema_version", "entries"},
        "provision transaction",
    )
    if type(plan["schema_version"]) is not int or plan["schema_version"] != SCHEMA_VERSION:
        raise ProvisionTransactionError("provision transaction schema version is unsupported")
    raw_entries = plan["entries"]
    if not isinstance(raw_entries, list):
        raise ProvisionTransactionError("provision transaction entries must be an array")
    entries = [_decode_entry(raw, index) for index, raw in enumerate(raw_entries)]
    relatives = [entry.relative for entry in entries]
    if len(relatives) != len(set(relatives)):
        raise ProvisionTransactionError("provision transaction repeats a file path")
    return entries


def recover(vault_root: str | Path) -> list[dict]:
    """Converge every unfinished Core transaction before first-run planning."""
    try:
        outcomes = Transaction.resume(Path(vault_root).resolve())
    except Exception as error:  # noqa: BLE001 - one fail-closed adapter error
        raise ProvisionTransactionError(
            f"provision transaction recovery failed: {error}"
        ) from error
    unsafe = [
        outcome
        for outcome in outcomes
        if outcome.get("quarantined") is not None
        or outcome.get("resumed") is not True
        or outcome.get("committed") is not False
        or outcome.get("journal_ok") is not True
    ]
    if unsafe:
        raise ProvisionTransactionError(
            "provision transaction recovery is incomplete or quarantined"
        )
    _committed_transactions(Path(vault_root).resolve())
    return outcomes


def _committed_transactions(vault_root: Path) -> list[dict[str, str]]:
    """Return exact durable commits and reject every non-terminal journal."""
    tx_root = vault_root / TX_ROOT_RELATIVE
    if not tx_root.exists():
        return []
    if tx_root.is_symlink() or not tx_root.is_dir():
        raise ProvisionTransactionError("provision transaction root is unsafe")
    committed: list[dict[str, str]] = []
    for tx_dir in sorted(tx_root.iterdir(), key=lambda candidate: candidate.name):
        if tx_dir.is_symlink() or not tx_dir.is_dir():
            raise ProvisionTransactionError("provision transaction entry is unsafe")
        try:
            entries = Journal(tx_dir / "journal.jsonl").read()
        except Exception as error:  # noqa: BLE001 - strict recovery audit
            raise ProvisionTransactionError(
                f"provision transaction {tx_dir.name} journal is unreadable"
            ) from error
        events = {entry.event for entry in entries}
        terminal = events & {"COMMITTED", "ROLLED-BACK"}
        if len(terminal) != 1:
            raise ProvisionTransactionError(
                f"provision transaction {tx_dir.name} is not singly terminal"
            )
        if "COMMITTED" in terminal:
            begins = [entry for entry in entries if entry.event == "BEGIN"]
            if (
                len(begins) != 1
                or not isinstance(begins[0].payload.get("operation"), str)
            ):
                raise ProvisionTransactionError(
                    f"provision transaction {tx_dir.name} has no exact operation"
                )
            committed.append(
                {
                    "transaction_id": tx_dir.name,
                    "operation": str(begins[0].payload["operation"]),
                }
            )
    return committed


def execute(vault_root: str | Path, document: object) -> dict[str, object]:
    """Validate and commit one complete first-run file plan."""
    root = Path(vault_root).resolve()
    recover(root)
    entries = _decode_plan(document)
    if not entries:
        return {
            "api_version": service.api_version,
            "receipt": None,
            "declared_paths": [],
        }
    try:
        preview = service._preview_transaction(
            root,
            entries,
            purpose="onboarding-provision",
            operation="onboarding-provision",
        )
        executed = service._execute_approved_transaction(
            root,
            entries,
            purpose="onboarding-provision",
            operation="onboarding-provision",
            approved_token=str(preview["approval_token"]),
        )
    except Exception as error:  # noqa: BLE001 - translate the deep module seam
        raise ProvisionTransactionError(f"provision transaction failed: {error}") from error

    receipt = dict(executed["receipt"])
    return {
        "api_version": service.api_version,
        "receipt": receipt,
        "declared_paths": receipt["declared_paths"],
    }


def _strict_json(raw: str) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ProvisionTransactionError(f"provision transaction repeats field {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ProvisionTransactionError(
            f"provision transaction contains non-JSON constant {value}"
        )

    try:
        return json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=reject_constant,
        )
    except ProvisionTransactionError:
        raise
    except json.JSONDecodeError as error:
        raise ProvisionTransactionError(
            f"provision transaction is not strict JSON: {error}"
        ) from error


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute crash-safe Dex first-run plans")
    parser.add_argument("--vault", required=True)
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.recover:
            root = Path(args.vault).resolve()
            recovered = recover(root)
            committed = _committed_transactions(root)
            result: object = {
                "ok": True,
                "recovered": recovered,
                "committed_transactions": committed,
                "committed_transaction_ids": [
                    transaction["transaction_id"] for transaction in committed
                ],
            }
        else:
            result = {"ok": True, **execute(args.vault, _strict_json(sys.stdin.read()))}
    except ProvisionTransactionError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
