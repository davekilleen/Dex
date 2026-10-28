#!/usr/bin/env python3
"""Dex Helper app executable.

Launch this app with ``open -W -n -a`` so LaunchServices makes Dex Helper
the responsible process. Do not spawn this file as a child of the MCP
server for Calendar or Reminders EventKit calls.

Argv is only the op and temp JSON paths — never titles or other event data.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _dex_root() -> Path:
    marker = Path(__file__).resolve().parent.parent / "Resources" / "dex-root.txt"
    if marker.is_file():
        text = marker.read_text(encoding="utf-8").strip()
        if text:
            return Path(text)
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        sys.stderr.write("Usage: DexHelper <op> <json-out-path> [json-in-path]\n")
        return 2
    op, out_path = args[0], args[1]
    payload: dict[str, object] = {}
    if len(args) > 2:
        payload = json.loads(Path(args[2]).read_text(encoding="utf-8"))
    root = _dex_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    # Shared EventKit scripts skip the editor denial loop when this process
    # is Dex Helper itself — LaunchServices may inherit VS Code markers.
    os.environ["DEX_HELPER_PROCESS"] = "1"
    from core.utils.eventkit_ops import run_op

    code, text = run_op(op, payload)
    Path(out_path).write_text(text + ("\n" if text and not text.endswith("\n") else ""), encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
