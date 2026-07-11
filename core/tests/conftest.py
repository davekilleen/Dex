"""Pytest bootstrap for deterministic vault-path tests."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_FIXTURE_VAULT = Path(__file__).resolve().parent / "fixtures" / "vault"
_RUNTIME_DIRECTORY = tempfile.TemporaryDirectory(prefix="dex-pytest-vault-")
RUNTIME_FIXTURE_VAULT = Path(_RUNTIME_DIRECTORY.name) / "vault"
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
    """Remove the disposable session vault after all plugins finish."""
    _RUNTIME_DIRECTORY.cleanup()
