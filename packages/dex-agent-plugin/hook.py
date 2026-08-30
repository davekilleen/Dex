#!/usr/bin/env python3
"""Shared Dex lifecycle adapter for plugin hosts."""

from __future__ import annotations

import argparse
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
    workspace_roots = payload.get("workspace_roots")
    workspace_root = (
        workspace_roots[0]
        if isinstance(workspace_roots, list) and workspace_roots and isinstance(workspace_roots[0], str)
        else None
    )
    for value in (
        payload.get("cwd"),
        workspace_root,
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


def _session_start(payload: dict[str, Any], protocol: str) -> int:
    context = build_session_boot(_vault(payload)).get("injected_text")
    if not isinstance(context, str) or not context.strip():
        return 0
    if protocol == "cursor":
        output = {"additional_context": context}
    else:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
    sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    return 0


def _family_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Map the code-assistant family's documented PreToolUse shapes onto the shared gate."""
    normalized = dict(payload)
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        mapped = dict(tool_input)
    else:
        tool_args = payload.get("toolArgs") or payload.get("tool_args")
        if isinstance(tool_args, dict):
            mapped = dict(tool_args)
        elif isinstance(tool_args, str) and tool_args.strip():
            mapped = {"command": tool_args}
        else:
            mapped = {}
    if "file_path" not in mapped and isinstance(mapped.get("filePath"), str):
        mapped["file_path"] = mapped["filePath"]
    if not mapped.get("command"):
        for key in ("command", "cmd"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                mapped["command"] = value
                break
    normalized["tool_input"] = mapped
    tool_name = payload.get("tool_name")
    if not (isinstance(tool_name, str) and tool_name.strip()):
        family_name = payload.get("toolName")
        if isinstance(family_name, str) and family_name.strip():
            normalized["tool_name"] = family_name
    return normalized


def _pre_tool_use(payload: dict[str, Any], protocol: str) -> int:
    if protocol == "copilot":
        payload = _family_payload(payload)
    decision = evaluate_hook_payload(payload, vault=_vault(payload))
    if decision.refused:
        if protocol == "cursor":
            output = {
                "permission": "deny",
                "user_message": decision.reason,
                "agent_message": decision.reason,
            }
            sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
            return 0
        if protocol == "gemini":
            output = {"decision": "deny", "reason": decision.reason}
            sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
            return 0
        if protocol == "copilot":
            output = {
                "permissionDecision": "deny",
                "permissionDecisionReason": decision.reason,
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": decision.reason,
                },
            }
            sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
            return decision.hook_exit
        # This compact contract is understood by Claude plugins and remains a
        # documented compatibility shape in Codex's hook runner.
        sys.stdout.write(decision.as_hook_json() + "\n")
        return decision.hook_exit
    if decision.reason:
        if protocol == "gemini":
            output = {"decision": "allow", "systemMessage": decision.reason}
            sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
            return 0
        if protocol == "cursor":
            return 0
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": decision.reason,
            }
        }
        sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--protocol",
        choices=("claude", "codex", "cursor", "gemini", "copilot"),
        default="claude",
    )
    args, _ = parser.parse_known_args(argv)
    payload = _read_payload()
    event = _event(payload)
    if event in {"SessionStart", "sessionStart"}:
        return _session_start(payload, args.protocol)
    if event in {"PreToolUse", "preToolUse", "BeforeTool"}:
        return _pre_tool_use(payload, args.protocol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
