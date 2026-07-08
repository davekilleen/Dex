"""Pytest bootstrap: run every suite against a throwaway copy of the fixture vault.

Tests must never write to the checked-in fixture vault at core/tests/fixtures/vault —
several suites (ritual intelligence, transcript reconcile) generate date-relative
notes and SQLite state under VAULT_PATH, which used to leave dirty artifacts in git.
This conftest copies the fixture vault into a temp directory once per session and
points VAULT_PATH at the copy before any test module imports core.paths.

Placed at core/ so it applies to core/tests, core/mcp/tests, and core/migrations/tests
regardless of which suite is invoked.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest

FIXTURE_VAULT_SOURCE = Path(__file__).resolve().parent / "tests" / "fixtures" / "vault"

_session_root = Path(tempfile.mkdtemp(prefix="dex-test-vault-"))
ACTIVE_VAULT = _session_root / "vault"
shutil.copytree(FIXTURE_VAULT_SOURCE, ACTIVE_VAULT)
# Deliberately override any pre-set VAULT_PATH (e.g. from CI env): the test run
# must be hermetic even when the environment points at the checked-in fixtures.
os.environ["VAULT_PATH"] = str(ACTIVE_VAULT)
atexit.register(lambda: shutil.rmtree(_session_root, ignore_errors=True))

for relative in (
    # Legacy numbered-prefix structure (kept for any tests still referencing old paths)
    "05-Areas/Meetings",
    "05-Areas/Meetings/Daily_Log",
    # New PARA structure (post-Obsidian migration)
    "Inbox/Meetings",
    "Inbox/Ideas",
    "Inbox/Daily_Plans",
    "Projects",
    "Planning",
    "People/Internal",
    "People/External",
    "People/Companies",
    "Career/Evidence",
    "Archive/Intel/Meeting_Intel",
    "Archive/Intel/Meeting_Intel/raw",
    "Archive/Intel/Meeting_Intel/summaries",
    "Archive/Intel/Meeting_Intel/Daily_Log",
    "Archive/Learnings",
    "System/.dex",
):
    (ACTIVE_VAULT / relative).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def fixture_vault() -> Path:
    """Return the session's writable copy of the minimal PARA fixture vault."""
    return ACTIVE_VAULT
