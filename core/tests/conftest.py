"""Shared test fixtures."""

from pathlib import Path

import pytest

FIXTURE_VAULT = Path(__file__).resolve().parent / "fixtures" / "vault"


@pytest.fixture
def fixture_vault() -> Path:
    """Return the path to the minimal PARA fixture vault."""
    return FIXTURE_VAULT
