"""Shared pre-action gates used by MCP and Claude wrappers."""

from .safety import GateDecision, evaluate_hook_payload, evaluate_safety_gate

__all__ = ["GateDecision", "evaluate_hook_payload", "evaluate_safety_gate"]
