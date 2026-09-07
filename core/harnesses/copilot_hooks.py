"""Documented GitHub CLI / VS Code hook translation, not a host support claim.

The installed command supplies surface and event: native CLI payloads do not
carry an event name, and CLI compatibility payloads cannot identify VS Code.
Policy stays in core.gates.safety; this module never executes proposed actions.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SURFACES = ("copilot-cli", "vscode")
EVENTS = {"preToolUse": "PreToolUse", "PreToolUse": "PreToolUse",
          "sessionStart": "SessionStart", "SessionStart": "SessionStart",
          "sessionEnd": "SessionEnd", "SessionEnd": "SessionEnd",
          "agentStop": "Stop", "Stop": "Stop"}
FAILURE = "Dex could not check this hook request. Check the selected vault and hook runtime."
UNKNOWN_TOOL = "Dex cannot inspect this tool schema yet. Use a reviewed tool or the Dex service."
SHELL = {"bash", "powershell", "Bash", "run_in_terminal", "runTerminalCommand"}
FILES = {"create", "edit", "str_replace_editor", "Write", "Edit", "create_file",
         "replace_string_in_file", "createFile", "editFiles", "multi_replace_string_in_file"}
READS = {"view", "Read", "grep", "rg", "Grep", "glob", "Glob", "web_fetch", "WebFetch",
         "web_search", "WebSearch", "ask_user", "AskUserQuestion", "update_todo", "TodoWrite"}
PATH_ALIASES = {"filePath": "file_path", "notebookPath": "notebook_path",
                "sourcePath": "source_path", "destinationPath": "destination_path"}


def _string(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("invalid string")
    return value  # Literal paths must retain whitespace and shell-like prefixes.


def _object(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_json(raw: str) -> Any:
    def reject_constant(_value: str) -> None:
        raise ValueError("invalid number")

    return json.loads(raw, object_pairs_hook=_unique_object,
                      parse_constant=reject_constant)


def _validate_envelope(payload: dict, surface: str, configured_event: str) -> tuple[str, bool]:
    if surface not in SURFACES or configured_event not in EVENTS:
        raise ValueError("unknown host/event")
    event = EVENTS[configured_event]
    if surface == "vscode" and event == "SessionEnd":
        raise ValueError("VS Code has no documented session-end event")
    native = surface == "copilot-cli" and configured_event[0].islower()
    common = {"timestamp", "cwd", "vault_path", "workspace_roots"}
    common |= {"sessionId"} if native else {"session_id", "hook_event_name", "transcript_path"}
    specific = {
        "PreToolUse": {"toolName", "toolArgs"} if native else {"tool_name", "tool_input", "tool_use_id"},
        "SessionStart": {"source", "initialPrompt" if native else "initial_prompt"},
        "SessionEnd": {"reason"},
        "Stop": {"stop_hook_active", "transcriptPath", "stopReason"} if native else {"stop_hook_active", "stop_reason"},
    }
    if payload.keys() - common - specific[event]:
        raise ValueError("unknown envelope fields")
    if native:
        if any(key in payload for key in ("hook_event_name", "session_id", "tool_name", "tool_input")):
            raise ValueError("mixed payload formats")
        _string(payload.get("sessionId"))
        stamp = payload.get("timestamp")
        if type(stamp) not in (int, float) or not math.isfinite(stamp):
            raise ValueError("invalid timestamp")
        _string(payload.get("cwd"))
    else:
        if any(key in payload for key in ("sessionId", "toolName", "toolArgs")):
            raise ValueError("mixed payload formats")
        if payload.get("hook_event_name") != event:
            raise ValueError("conflicting event")
        _string(payload.get("timestamp"))
        if surface == "copilot-cli" or "session_id" in payload:
            _string(payload.get("session_id"))
    # Do not accept a second spelling capable of contradicting the command.
    if "hookEventName" in payload:
        raise ValueError("unexpected event alias")
    if "cwd" in payload:
        _string(payload["cwd"])
    if "vault_path" in payload:
        _string(payload["vault_path"])
    if event == "PreToolUse" and "cwd" not in payload:
        raise ValueError("cannot resolve relative tool targets without host cwd")
    return event, native


def _inputs(tool: str, arguments: Any, native: bool) -> list[tuple[str, dict]]:
    # CLI toolArgs is unknown in the reference, and may be a JSON string.
    if isinstance(arguments, str):
        if tool in {"apply_patch", "Edit"} and arguments.startswith("*** Begin Patch"):
            arguments = {"patch": arguments}
        elif native:
            arguments = parse_json(arguments)
    args = dict(_object(arguments))
    for source, destination in PATH_ALIASES.items():
        if source in args:
            if destination in args and args[source] != args[destination]:
                raise ValueError("conflicting target aliases")
            args[destination] = args.pop(source)
    if tool not in SHELL | FILES | READS | {"apply_patch"}:
        raise ValueError(UNKNOWN_TOOL)
    # PascalCase CLI maps apply_patch to Edit; its patch data still needs the
    # canonical patch parser, not the single-file Edit path.
    patch = tool == "apply_patch" or (tool == "Edit" and any(k in args for k in ("patch", "input")))
    if tool == "Edit" and isinstance(args.get("command"), str) and args["command"].startswith("*** Begin Patch"):
        patch = True
    canonical = "apply_patch" if patch else "Bash" if tool in SHELL else "Write" if tool in FILES else tool
    inputs = [(canonical, args)]
    if "files" in args:
        files = args["files"]
        if not isinstance(files, list) or not files:
            raise ValueError("invalid files")
        # Keep any independent top-level target; do not overwrite it with a
        # safe member of the array and lose an unsafe path.
        inputs = [("Read", args), *[(canonical, {**args, "path": _string(path)}) for path in files]]
    if "replacements" in args:
        rows = args["replacements"]
        if tool != "multi_replace_string_in_file" or not isinstance(rows, list) or not rows:
            raise ValueError("invalid replacements")
        # Check top-level exposed fields too; they must not disappear when the
        # batch is flattened. Each row must have an inspectable file target.
        if "files" not in args:
            inputs = [("Read", args)]
        for row in rows:
            inputs.extend(_inputs("replace_string_in_file", row, False))
    return inputs


def _denial(surface: str, reason: str) -> dict:
    decision = {"permissionDecision": "deny", "permissionDecisionReason": reason}
    if surface == "vscode":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}}
    return decision


def handle(payload: Any, *, surface: str, event: str) -> dict:
    """Translate one event; any malformed/unknown input raises before action."""
    payload = _object(payload)
    normalized, native = _validate_envelope(payload, surface, event)
    if normalized == "PreToolUse":
        from core.gates.safety import evaluate_hook_payload

        tool = _string(payload.get("toolName" if native else "tool_name"))
        inputs = _inputs(tool, payload.get("toolArgs" if native else "tool_input"), native)
        warning = ""
        for canonical, arguments in inputs:
            request = {key: payload[key] for key in ("cwd", "vault_path", "workspace_roots") if key in payload}
            request.update(hook_event_name="PreToolUse", tool_name=canonical, tool_input=arguments)
            decision = evaluate_hook_payload(request)
            if decision.refused:
                return _denial(surface, decision.reason)
            warning = decision.reason or warning
        # A policy pass must retain the host's ordinary approval flow. An
        # explicit 'allow' can auto-approve a tool in VS Code.
        if warning:
            return {"systemMessage": warning} if surface == "vscode" else {"permissionDecisionReason": warning}
        return {}
    if normalized == "SessionStart":
        from core.vault_selection import select_vault

        source = payload.get("source")
        if source not in (("new",) if surface == "vscode" else ("startup", "resume", "new")):
            raise ValueError("unknown session source")
        # No cwd from VS Code must not turn the plugin cache into a vault.
        if "cwd" not in payload:
            import os

            if not any(os.environ.get(k) for k in ("DEX_VAULT_PATH", "VAULT_PATH", "CLAUDE_PROJECT_DIR")):
                raise ValueError("missing vault binding")
        root = select_vault(explicit=payload.get("vault_path"), cwd=payload.get("cwd"),
                            workspace_roots=payload.get("workspace_roots"))
        from core.context.session_boot import build_session_boot

        context = build_session_boot(root)["injected_text"]
        if not isinstance(context, str):
            raise ValueError("invalid shared context")
        if not context:
            return {}
        return ({"additionalContext": context} if surface == "copilot-cli" else
                {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}})
    if normalized == "SessionEnd":
        if payload.get("reason") not in ("complete", "error", "abort", "timeout", "user_exit"):
            raise ValueError("unknown end reason")
    elif normalized == "Stop":
        if type(payload.get("stop_hook_active")) is not bool:
            raise ValueError("invalid stop flag")
        if surface == "copilot-cli" and payload.get("stopReason" if native else "stop_reason") != "end_turn":
            raise ValueError("unknown turn stop reason")
    # Deliberate no-op: neither event authorizes an autocommit, checkpoint, or
    # transcript read. Stop never becomes SessionEnd.
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface", required=True, choices=SURFACES)
    parser.add_argument("--event", required=True, choices=EVENTS)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("oversized hook")
        output = handle(parse_json(raw), surface=args.surface, event=args.event)
    except Exception:
        # No input, private paths, tool arguments or tracebacks in diagnostics.
        sys.stderr.write(FAILURE + "\n")
        output = _denial(args.surface, FAILURE)
        sys.stdout.write(json.dumps(output) + "\n")
        return 2  # VS Code treats other nonzero exits as non-blocking warnings.
    sys.stdout.write(json.dumps(output, ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
