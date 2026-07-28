"""Regression guard for the interpreter used by installer lifecycle adoption.

Adoption imports PyYAML, which install.sh only installs into .venv. Handing the
system Python to adoption breaks every fresh install that has a release catalog.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_install_adoption_uses_the_venv_python_when_available() -> None:
    installer = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    adoption_lines = [
        line
        for line in installer.splitlines()
        if "core/provision.cjs" in line and "--adopt" in line
    ]

    assert len(adoption_lines) == 1
    assert 'DEX_LIFECYCLE_PYTHON="$DEX_ADOPTION_PYTHON"' in adoption_lines[0]
    assert 'DEX_LIFECYCLE_PYTHON="$PYTHON_CMD"' not in adoption_lines[0]
    assert 'DEX_ADOPTION_PYTHON="$PYTHON_CMD"' in installer
    assert '[ -n "$VENV_PYTHON" ] && [ -f "$VENV_PYTHON" ]' in installer
    assert 'DEX_ADOPTION_PYTHON="$VENV_PYTHON"' in installer
