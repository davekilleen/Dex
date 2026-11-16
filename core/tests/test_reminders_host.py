"""Host detection for the VS Code Reminders limitation."""

from __future__ import annotations

import pytest

from core.utils.reminders_host import (
    CLAUDE_DESKTOP_REMINDERS_UNAVAILABLE_MESSAGE,
    VSCODE_REMINDERS_UNAVAILABLE_MESSAGE,
    is_claude_desktop_host,
    is_cursor_host,
    is_terminal_host,
    is_vscode_host,
    reminders_blocked_without_helper,
)


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, False),
        ({"TERM_PROGRAM": "Apple_Terminal"}, False),
        ({"TERM_PROGRAM": "iTerm.app"}, False),
        ({"CLAUDE_CODE": "1"}, False),
        ({"TERM_PROGRAM": "vscode"}, True),
        ({"TERM_PROGRAM": "VSCode"}, True),
        ({"VSCODE_PID": "1234"}, True),
        ({"VSCODE_CWD": "/tmp/workspace"}, True),
        ({"VSCODE_IPC_HOOK": "/tmp/vscode-ipc"}, True),
        ({"VSCODE_INJECTION": "1"}, True),
        (
            {"TERM_PROGRAM": "vscode", "CURSOR_TRACE_ID": "abc"},
            False,
        ),
        (
            {"VSCODE_PID": "1234", "CURSOR_AGENT": "1"},
            False,
        ),
    ],
)
def test_is_vscode_host_uses_only_the_supplied_environment(env, expected):
    assert is_vscode_host(env) is expected


def test_is_vscode_host_does_not_read_os_environ_when_env_is_passed(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "vscode")
    monkeypatch.setenv("VSCODE_PID", "999")

    assert is_vscode_host({}) is False


def test_unavailable_message_tells_the_user_what_to_do_instead():
    assert "can't be switched on from inside VS Code" in VSCODE_REMINDERS_UNAVAILABLE_MESSAGE
    assert "Claude app" in VSCODE_REMINDERS_UNAVAILABLE_MESSAGE
    assert "Terminal" in VSCODE_REMINDERS_UNAVAILABLE_MESSAGE
    assert "home folder" not in VSCODE_REMINDERS_UNAVAILABLE_MESSAGE.lower()


def test_claude_desktop_and_cursor_and_terminal_hosts():
    assert is_claude_desktop_host({"CLAUDE_DESKTOP": "1"}) is True
    assert is_claude_desktop_host({"__CFBundleIdentifier": "com.anthropic.claudefordesktop"}) is True
    assert is_claude_desktop_host({"CLAUDE_CODE": "1", "CLAUDE_DESKTOP": "1"}) is False
    assert is_cursor_host({"CURSOR_TRACE_ID": "abc"}) is True
    assert is_terminal_host({"TERM": "xterm-256color"}) is True
    assert is_terminal_host({"TERM_PROGRAM": "vscode"}) is False
    assert reminders_blocked_without_helper({"TERM_PROGRAM": "vscode"}) == VSCODE_REMINDERS_UNAVAILABLE_MESSAGE
    assert reminders_blocked_without_helper({"CLAUDE_DESKTOP": "1"}) == CLAUDE_DESKTOP_REMINDERS_UNAVAILABLE_MESSAGE
    assert reminders_blocked_without_helper({"CURSOR_TRACE_ID": "abc"}) is None
    assert reminders_blocked_without_helper(
        {"TERM_PROGRAM": "vscode", "DEX_HELPER_PROCESS": "1"}
    ) is None
