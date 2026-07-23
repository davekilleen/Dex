"""Tests for the live soft-promise capture hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".claude" / "hooks" / "soft-promise-detector.py"


def _run_hook(stdin: str, state_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
    env["DEX_SOFT_PROMISE_STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=REPO_ROOT,
        env=env,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def test_hook_fails_open_for_empty_and_invalid_stdin(tmp_path: Path) -> None:
    for stdin in ("", "{not-json"):
        result = _run_hook(stdin, tmp_path)

        assert result.returncode == 0
        assert result.stdout == ""


def test_hook_offers_each_commitment_once_per_session(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "prompt": "I'll follow up with Priya",
            "session_id": "soft-promise-hook-test",
            "hook_event_name": "UserPromptSubmit",
        }
    )

    first = _run_hook(payload, tmp_path)
    second = _run_hook(payload, tmp_path)

    assert first.returncode == 0
    output = json.loads(first.stdout)
    assert output["continue"] is True
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "I'll follow up with Priya" in context
    assert "confirm before creating" in context
    assert second.returncode == 0
    assert second.stdout == ""


def test_hook_is_silent_without_a_commitment(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "prompt": "what's the weather",
            "session_id": "soft-promise-no-match",
            "hook_event_name": "UserPromptSubmit",
        }
    )

    result = _run_hook(payload, tmp_path)

    assert result.returncode == 0
    assert result.stdout == ""


def test_hook_never_imports_or_calls_task_creation() -> None:
    source = HOOK.read_text(encoding="utf-8")

    assert "create_task" not in source
