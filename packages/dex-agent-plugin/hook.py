#!/usr/bin/env python3
"""Shared Dex lifecycle adapter for Codex and Claude plugin hosts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from core.context.session_boot import build_session_boot  # noqa: E402
from core.context.vault_selection import VaultSelectionError, select_vault  # noqa: E402
from core.gates.safety import evaluate_hook_payload, read_hook_event, refusal  # noqa: E402


def _read_payload() -> dict[str, Any]:
    parsed = json.loads(sys.stdin.read())
    if not isinstance(parsed, dict):
        raise ValueError("invalid hook payload")
    return parsed


def _vault(payload: dict[str, Any]) -> Path:
    if "vault_path" in payload and not isinstance(payload["vault_path"], str):
        raise VaultSelectionError("Blocked: invalid explicit vault selection.")
    return select_vault(explicit=payload.get("vault_path"), cwd=payload.get("cwd"),
                        workspace_roots=payload.get("workspace_roots"))


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


def _pre_tool_use(payload: dict[str, Any], protocol: str) -> int:
    return _emit_decision(evaluate_hook_payload(payload), protocol)


def _emit_decision(decision, protocol: str) -> int:
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
        choices=("claude", "codex", "cursor", "gemini"),
        default="claude",
    )
    args, _ = parser.parse_known_args(argv)
    try:
        payload = _read_payload()
        event = read_hook_event(payload)
        if event == "SessionStart":
            return _session_start(payload, args.protocol)
        if event == "PreToolUse":
            return _pre_tool_use(payload, args.protocol)
        return _emit_decision(refusal("Blocked: unknown or missing safety hook event."), args.protocol)
    except VaultSelectionError as exc:
        return _emit_decision(refusal(str(exc), exc.code), args.protocol)
    except Exception:
        # Never expose paths or traceback data; a crashed checker made no decision.
        return _emit_decision(refusal("Blocked: Dex could not check this hook request. Check the selected vault and runtime."), args.protocol)



if __name__ == "__main__":
    raise SystemExit(main())
