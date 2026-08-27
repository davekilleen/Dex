"""Every Python package a Dex install pulls in must come from the lock.

Dex used to install its Python dependencies from open-ended ranges
(``pyyaml>=6.0``), so each machine resolved the whole transitive tree fresh
against the package index at install time.  A malicious release published
anywhere in that tree — including deep inside scrapling's — would have landed
in the user's ``.venv``.

The fix: ``pyproject.toml`` declares the ranges, ``uv.lock`` pins the resolved
tree, and the two requirements files installers read are generated from that
lock with exact versions and checksums.  These tests fail if any part of that
chain is loosened again.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

LOCKED_REQUIREMENTS = (
    "core/mcp/requirements.txt",
    "requirements.txt",
)

# A requirement line in a generated export: "name==version[ ; marker] \".
REQUIREMENT_LINE = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)\s*(?P<pin>[=<>!~]=?[^;\\]*)")


def _requirement_lines(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if line and not line.startswith((" ", "\t", "#", "-"))
    ]


@pytest.mark.parametrize("relative", LOCKED_REQUIREMENTS)
def test_every_installed_package_is_pinned_with_a_checksum(relative: str) -> None:
    text = (REPO_ROOT / relative).read_text(encoding="utf-8")
    lines = _requirement_lines(text)

    assert lines, f"{relative} declares no packages"

    for line in lines:
        match = REQUIREMENT_LINE.match(line)
        assert match is not None, f"{relative}: unparsable requirement {line!r}"
        pin = match.group("pin").strip()
        assert pin.startswith("=="), (
            f"{relative}: {match.group('name')} is not pinned to an exact version "
            f"({pin!r}) — regenerate with ./scripts/lock-python-deps.sh"
        )
        assert line.rstrip().endswith("\\"), (
            f"{relative}: {match.group('name')} carries no checksum — "
            "regenerate with ./scripts/lock-python-deps.sh"
        )

    assert "--hash=sha256:" in text, f"{relative} carries no hashes at all"


def test_lock_file_actually_resolves_packages() -> None:
    lock = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")

    assert lock.count("[[package]]") > 1, (
        "uv.lock holds no resolved packages — run ./scripts/lock-python-deps.sh"
    )
    assert 'source = { registry = "https://pypi.org/simple" }' in lock


def test_pyproject_declares_everything_the_generated_files_install() -> None:
    """The declared ranges are the only place a dependency may be introduced."""
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    declared = {
        re.split(r"[\[<>=!;~ ]", dependency, maxsplit=1)[0].lower().replace("_", "-")
        for dependency in project["dependencies"]
    }
    # install.sh accepts Python 3.10+, so the lock has to stay valid that far back.
    assert project["requires-python"] == ">=3.10"
    assert {"mcp", "pyyaml", "python-dateutil", "requests", "aiohttp"} <= declared
    assert "scrapling" in {
        re.split(r"[\[<>=!;~ ]", dependency, maxsplit=1)[0].lower()
        for dependency in project["optional-dependencies"]["scraping"]
    }

    runtime = (REPO_ROOT / "core" / "mcp" / "requirements.txt").read_text(encoding="utf-8")
    runtime_names = {
        REQUIREMENT_LINE.match(line).group("name").lower()  # type: ignore[union-attr]
        for line in _requirement_lines(runtime)
    }
    missing = declared - runtime_names - {"pyobjc-framework-eventkit"}
    assert not missing, f"declared but never installed: {sorted(missing)}"
    # The macOS-only calendar dependency must survive Linux-side re-locking.
    assert "pyobjc-framework-eventkit" in runtime_names
    assert "sys_platform == 'darwin'" in runtime

    # scrapling belongs to the optional extra, not to what install.sh installs.
    assert "scrapling" not in runtime_names
    scraping = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "\nscrapling==" in scraping


def test_installer_refuses_unpinned_or_tampered_packages() -> None:
    install = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")

    assert install.count("--require-hashes -r core/mcp/requirements.txt") >= 1
    # No install path may fall back to resolving ranges against the index.
    assert "install -r core/mcp/requirements.txt" not in install
