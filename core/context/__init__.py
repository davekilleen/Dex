"""Harness-neutral session and person context payloads.

Claude Code hooks and Work MCP tools call these functions so every
harness sees the same facts. Do not reimplement the payloads in a hook.
"""

from core.context.person_context import (
    format_person_context_block,
    get_person_context,
    inject_person_context_for_file,
)
from core.context.session_boot import build_session_boot, format_session_boot_text

__all__ = [
    "build_session_boot",
    "format_person_context_block",
    "format_session_boot_text",
    "get_person_context",
    "inject_person_context_for_file",
]
