#!/usr/bin/env python3
"""Run mcp-publisher validate only. Never publish."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

ALLOWED_COMMANDS = frozenset({"validate"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(ALLOWED_COMMANDS))
    parser.add_argument("server_json", nargs="?", default="server.json")
    parser.add_argument(
        "--mcp-publisher",
        default=shutil.which("mcp-publisher"),
        help="Path to mcp-publisher. Defaults to PATH.",
    )
    args = parser.parse_args(argv)

    publisher = args.mcp_publisher
    if not publisher:
        print("mcp-publisher is not installed; skipped official CLI validation.")
        return 0

    server_json = Path(args.server_json).expanduser()
    command = [publisher, "validate", str(server_json)]
    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
