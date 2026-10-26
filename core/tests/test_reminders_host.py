"""Host detection for the VS Code Reminders limitation."""

from __future__ import annotations

import pytest

from core.utils.reminders_host import (
    VSCODE_REMINDERS_UNAVAILABLE_MESSAGE,
    is_vscode_host,
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
