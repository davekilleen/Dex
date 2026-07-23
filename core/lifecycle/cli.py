"""Inspect and verify Dex's local lifecycle ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.lifecycle.ledger import (
    LedgerError,
    project_state,
    read_events,
    repair_state,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _non_negative(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a non-negative sequence number") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative sequence number")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.lifecycle.cli",
        description="Inspect or repair Dex lifecycle history.",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        default=Path.cwd(),
        help="Dex vault root (default: current directory)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="print the current lifecycle state as JSON")
    events = commands.add_parser("events", help="print verified lifecycle events as JSON")
    events.add_argument(
        "--since",
        type=_non_negative,
        default=1,
        metavar="SEQ",
        help="include events at or after this sequence (default: 1)",
    )
    commands.add_parser("verify", help="verify the complete immutable event chain")
    commands.add_parser(
        "rebuild-state",
        help="repair an interrupted terminal publication and rebuild the state cache",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    vault_root: Path = args.vault_root
    try:
        if args.command == "status":
            print(_canonical_json(project_state(vault_root)))
            return 0
        if args.command == "events":
            print(_canonical_json(read_events(vault_root, since=args.since)))
            return 0
        if args.command == "verify":
            state = project_state(vault_root)
            count = int(state["last_seq"])
            noun = "event" if count == 1 else "events"
            verb = "forms" if count == 1 else "form"
            print(f"Ledger verified: {count} immutable {noun} {verb} a valid chain.")
            return 0
        state, repairs = repair_state(vault_root)
        print(_canonical_json(state))
        count = int(state["last_seq"])
        noun = "event" if count == 1 else "events"
        actions = [*repairs, f"rebuilt state cache from {count} {noun}"]
        print(f"Ledger rebuild-state completed: {'; '.join(actions)}.", file=sys.stderr)
        return 0
    except (LedgerError, OSError) as error:
        action = "verification" if args.command == "verify" else args.command
        print(f"Ledger {action} failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
