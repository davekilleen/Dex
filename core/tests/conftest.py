"""Pytest bootstrap for deterministic vault-path tests."""

import os
from pathlib import Path

import pytest

FIXTURE_VAULT = Path(__file__).resolve().parent / "fixtures" / "vault"
os.environ.setdefault("VAULT_PATH", str(FIXTURE_VAULT))

for relative in (
    "05-Areas/Meetings",
    "05-Areas/Meetings/Daily_Log",
    "System/.dex",
):
    (FIXTURE_VAULT / relative).mkdir(parents=True, exist_ok=True)


@pytest.fixture
def fixture_vault() -> Path:
    """Return the path to the minimal PARA fixture vault."""
    return FIXTURE_VAULT
