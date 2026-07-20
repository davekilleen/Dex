"""Pytest bootstrap for deterministic vault-path tests."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_FIXTURE_VAULT = Path(__file__).resolve().parent / "fixtures" / "vault"
# The shared runtime vault must survive tests that os.fork() (e.g. the
# history-hygiene death-injection suite). A forked child can hit an unhandled
# exception instead of os._exit(), unwind into a rogue interpreter, and reach
# normal shutdown — at which point a tempfile.TemporaryDirectory finalizer would
# delete this vault out from under the still-running parent, corrupting every
# later path-contract test. mkdtemp() registers no such finalizer, so the tree
# is removed only by the explicit, PID-guarded pytest_unconfigure below.
_CREATOR_PID = os.getpid()
_RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="dex-pytest-vault-"))
RUNTIME_FIXTURE_VAULT = _RUNTIME_ROOT / "vault"
shutil.copytree(SOURCE_FIXTURE_VAULT, RUNTIME_FIXTURE_VAULT)

# core.paths binds VAULT_PATH when test modules import it, so force the
# disposable copy here before collection imports any product modules.
os.environ["VAULT_PATH"] = str(RUNTIME_FIXTURE_VAULT)

for relative in (
    "05-Areas/Meetings",
    "05-Areas/Meetings/Daily_Log",
    "System/.dex",
    "04-Projects/DexDiff/beta/diffs",
    "04-Projects/DexDiff/beta/profile",
    "04-Projects/DexDiff/design",
):
    (RUNTIME_FIXTURE_VAULT / relative).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def fixture_vault() -> Path:
    """Return the pristine tracked fixture for read-only checks and per-test copies."""
    return SOURCE_FIXTURE_VAULT


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the suite if any test touched the tracked fixture vault."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", "core/tests/fixtures/vault"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if not result.stdout:
        return

    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_sep("=", "tracked fixture vault was mutated")
        reporter.write_line(result.stdout.rstrip())
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_unconfigure(config: pytest.Config) -> None:
    """Remove the disposable session vault after all plugins finish.

    Guarded by the creator PID so a forked child that reaches this hook during
    its own shutdown cannot delete the vault the parent session still depends on.
    """
    if os.getpid() != _CREATOR_PID:
        return
    shutil.rmtree(_RUNTIME_ROOT, ignore_errors=True)
