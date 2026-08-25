#!/usr/bin/env python3
"""Shared Dex lifecycle adapter for Codex and Claude plugin hosts."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from core.context.session_boot import build_session_boot  # noqa: E402
from core.gates.safety import evaluate_hook_payload  # noqa: E402


def _read_payload() -> dict[str, Any]:
    try:
        parsed = json.loads(sys.stdin.read() or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _vault(payload: dict[str, Any]) -> Path:
    for value in (
        payload.get("cwd"),
        os.environ.get("DEX_VAULT_PATH"),
        os.environ.get("VAULT_PATH"),
        os.environ.get("CLAUDE_PROJECT_DIR"),
    ):
        if isinstance(value, str) and value.strip():
            try:
                return Path(value).expanduser()
            except (OSError, TypeError, ValueError):
                continue
    return Path.cwd()


def _event(payload: dict[str, Any]) -> str:
    value = payload.get("hook_event_name") or payload.get("hookEventName")
    return value.strip() if isinstance(value, str) else ""


def _session_start(payload: dict[str, Any]) -> int:
    context = build_session_boot(_vault(payload)).get("injected_text")
    if not isinstance(context, str) or not context.strip():
        return 0
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    return 0


def _pre_tool_use(payload: dict[str, Any]) -> int:
    decision = evaluate_hook_payload(payload, vault=_vault(payload))
    if decision.refused:
        # This compact contract is understood by Claude plugins and remains a
        # documented compatibility shape in Codex's hook runner.
        sys.stdout.write(decision.as_hook_json() + "\n")
        return decision.hook_exit
    if decision.reason:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": decision.reason,
            }
        }
        sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    return 0


def main() -> int:
    payload = _read_payload()
    event = _event(payload)
    if event == "SessionStart":
        return _session_start(payload)
    if event == "PreToolUse":
        return _pre_tool_use(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
