"""Guards for the first-run Python that executes provision_transaction."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVISIONER = REPO_ROOT / "core" / "provision.cjs"
ONBOARDING_SERVER = REPO_ROOT / "core" / "mcp" / "onboarding_server.py"


def test_provisioner_resolves_vault_venv_before_system_python() -> None:
    source = PROVISIONER.read_text(encoding="utf-8")
    assert "function resolveStagePython" in source
    assert "function vaultPython" in source
    assert ".venv" in source
    assert "resolveStagePython(vaultRoot, 'DEX_PROVISION_PYTHON')" in source


def test_onboarding_server_refuses_old_python_before_importing_paths() -> None:
    source = ONBOARDING_SERVER.read_text(encoding="utf-8")
    version_check = source.index("sys.version_info < (3, 10)")
    paths_import = source.index("from core.paths import")
    assert version_check < paths_import
    assert "Dex setup needs Python 3.10 or newer" in source
