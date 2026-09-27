#!/usr/bin/env python3
"""First activation, one adopt+rewind, then refuse CRLF under System/.dex.

Used by the advisory Windows install journey. Every mutation goes through
the lifecycle service / bridge, not a direct write.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.lifecycle.bridge import prepare_vault
from core.lifecycle.engine import AdoptionReceipt, rewind_acknowledgement_token
from core.lifecycle.ledger import read_events
from core.lifecycle.service import (
    build_and_preview_adoption,
    build_inventory_and_plan,
    execute_approved_adoption,
    rewind_adoption_by_receipt,
)


def _scan_crlf(vault: Path) -> list[str]:
    root = vault / "System" / ".dex"
    if not root.is_dir():
        return [f"missing {root.as_posix()}"]
    tainted: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if b"\r\n" in path.read_bytes():
            tainted.append(path.relative_to(vault).as_posix())
    return tainted


def _first_adoptable(plan: dict) -> str | None:
    for item in plan.get("items", []):
        if item.get("action") == "adopt" and item.get("item_id"):
            return str(item["item_id"])
    return None


def _latest_adoption_receipt(vault: Path) -> dict | None:
    try:
        events = read_events(vault, since=1)
    except Exception:
        return None
    if not isinstance(events, list):
        return None
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        receipt = event.get("receipt")
        if isinstance(receipt, dict) and receipt.get("items_adopted"):
            return receipt
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-root", required=True, type=Path)
    args = parser.parse_args()
    vault = args.vault_root.resolve()
    report: dict[str, object] = {"vault_root": str(vault)}

    activation = prepare_vault(vault)
    report["activation"] = activation

    planned = build_inventory_and_plan(vault)
    item_id = _first_adoptable(planned.get("plan", {}))
    if item_id:
        previewed = build_and_preview_adoption(vault, vault, (item_id,))
        executed = execute_approved_adoption(
            vault,
            vault,
            previewed["preview"],
            previewed["approval_token"],
        )
        rewound = rewind_adoption_by_receipt(
            vault,
            executed["receipt"],
            executed["rewind_acknowledgement_token"],
        )
        report["adopt"] = {"item_id": item_id, "receipt": executed["receipt"]}
        report["rewind"] = rewound
    else:
        receipt = _latest_adoption_receipt(vault)
        if receipt is None:
            report["adopt"] = "no-pending-item"
            report["rewind"] = "no-receipt"
        else:
            token = receipt.get("rewind_acknowledgement_token") or receipt.get(
                "acknowledgement_token"
            )
            if not token:
                token = rewind_acknowledgement_token(AdoptionReceipt.from_dict(receipt))
            report["rewind"] = rewind_adoption_by_receipt(vault, receipt, str(token))
            report["adopt"] = "reused-ledger-receipt"

    tainted = _scan_crlf(vault)
    report["crlf"] = tainted
    print(json.dumps(report, default=str, indent=2))
    if tainted:
        print("CRLF found under System/.dex:", ", ".join(tainted), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
