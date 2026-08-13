"""Harness-neutral pre-action safety gates.

Claude Code hooks and Work MCP tools call these functions so every
harness gets the same refusal. Do not reimplement interceptors in a hook.
Matchers that are Claude-only (preferred scraper, ``claude mcp add`` scope)
stay in the hook.
"""

from core.gates.safety import (
    GateDecision,
    evaluate_hook_payload,
    evaluate_safety_gate,
)

__all__ = [
    "GateDecision",
    "evaluate_hook_payload",
    "evaluate_safety_gate",
]
