"""One real walk through the user's door immediately after an update.

The v1.84.0 activation incident lived exclusively in the moment after a
delivered release applied: from that instant every gated lifecycle operation
(plan, state, adoption, rewind) refused, while updates themselves kept
working — and nothing exercised a gated operation until a human did, so the
breakage surfaced days later as a mystery.  This canary is that exercise,
run at the only moment that matters.  It calls the same public operations
the product uses, read-only, and writes a receipt either way so health
surfaces can see that the check happened.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

RECEIPT_RELATIVE = Path("System/.dex/health/post-update-canary.json")
RECEIPT_CONTRACT = "dex.health.post-update-canary/v1"


def _dex_version(vault_root: Path) -> str | None:
    try:
        document = json.loads((vault_root / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    version = document.get("version")
    return version if isinstance(version, str) else None


def _write_receipt(vault_root: Path, receipt: dict[str, object]) -> None:
    target = vault_root / RECEIPT_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Unique temp name: two concurrent canaries must never interleave into one
    # published receipt, and a crashed attempt must not leave a fixed-name
    # orphan that the next attempt trips over.
    temporary = target.parent / f".{target.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def run_canary(vault_root: str | Path) -> dict[str, object]:
    """Exercise the gated read operations and record what actually happened."""
    root = Path(vault_root).resolve()
    receipt: dict[str, object] = {
        "contract": RECEIPT_CONTRACT,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "dex_version": _dex_version(root),
        "ok": False,
        "error": None,
    }
    try:
        from core.lifecycle import service

        state = service.read_lifecycle_state(root)
        plan = service.build_inventory_and_plan(root)
        if "ledger_state" not in state or "plan" not in plan:
            raise RuntimeError("lifecycle read operations returned unexpected shapes")
        receipt["ok"] = True
    except Exception as error:  # noqa: BLE001 - the canary's job is to report, not raise
        receipt["error"] = f"{type(error).__name__}: {error}"
    try:
        _write_receipt(root, receipt)
    except OSError:
        pass
    return receipt


def main(argv: list[str] | None = None) -> int:
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--vault", type=Path, default=Path.cwd())
        args = parser.parse_args(argv)
        receipt = run_canary(args.vault)
    except SystemExit:
        raise
    except BaseException as error:  # noqa: BLE001 - a canary that crashes is a failed canary
        print(
            "Post-update check FAILED before it could finish "
            f"({type(error).__name__}: {error}). Run /dex-doctor now."
        )
        return 1
    if receipt["ok"]:
        print("Post-update check passed: Dex's plan and state doors both open.")
        return 0
    print(
        "Post-update check FAILED: this update applied, but Dex's plan/state "
        f"doors did not open afterwards ({receipt['error']}). Run /dex-doctor now, "
        "before anything else relies on this install."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
