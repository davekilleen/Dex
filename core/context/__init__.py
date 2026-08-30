"""Harness-neutral context payloads used by MCP and Claude wrappers."""

from .decision_record import ask_what_was_decided
from .person_context import (
    ask_what_is_still_open_with_people,
    ask_who_is_in_todays_plan,
    find_people_in_file,
    format_person_context_block,
    get_person_context,
    inject_person_context_for_file,
)
from .session_boot import build_session_boot, format_session_boot_text

__all__ = [
    "ask_what_is_still_open_with_people",
    "ask_what_was_decided",
    "ask_who_is_in_todays_plan",
    "build_session_boot",
    "find_people_in_file",
    "format_person_context_block",
    "format_session_boot_text",
    "get_person_context",
    "inject_person_context_for_file",
]
