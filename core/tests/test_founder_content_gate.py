"""Regression tests for the static founder-content gate.

Mirrors ``test_security_gate.py``: each test copies the gate scripts into a fresh
fixture repository, plants tracked content, and runs the real wrapper end-to-end.
The load-bearing case is ``test_removing_allowlist_entry_turns_gate_red`` — proof
that the gate actually fails on founder content and is not silently a no-op.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
CORE_UTILS = Path(__file__).resolve().parents[2] / "core/utils/local_git.py"

# The gate scripts themselves contain the token words (the TOKENS list and the
# allowlist regexes), so every allowlist must permit them, exactly as the real one
# does. Prepended to each fixture allowlist so tests only declare their extra rules.
SELF_ALLOW = (
    r"^scripts/check-founder-content\.py:.*:(dave|killeen|pendo|cursor)$" + "\n"
    r"^scripts/founder-content-allowlist\.txt:.*:(dave|killeen|pendo|cursor)$" + "\n"
    r"^scripts/check-founder-content\.py:.*:personal-path$" + "\n"
    r"^scripts/founder-content-allowlist\.txt:.*:personal-path$" + "\n"
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _fixture(tmp_path: Path, allowlist_text: str) -> Path:
    root = tmp_path / "repository"
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Dex Tests")
    _git(root, "config", "user.email", "tests@example.com")
    scripts = root / "scripts"
    scripts.mkdir()
    shutil.copy2(REPO_SCRIPTS / "check-founder-content.sh", scripts / "check-founder-content.sh")
    shutil.copy2(REPO_SCRIPTS / "check-founder-content.py", scripts / "check-founder-content.py")
    (scripts / "founder-content-allowlist.txt").write_text(SELF_ALLOW + allowlist_text, encoding="utf-8")
    core_utils = root / "core/utils"
    core_utils.mkdir(parents=True)
    (root / "core/__init__.py").write_text("")
    (core_utils / "__init__.py").write_text("")
    shutil.copy2(CORE_UTILS, core_utils / "local_git.py")
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", "scripts/check-founder-content.sh"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ},
    )


def test_gate_flags_planted_founder_name_outside_allowlist(tmp_path):
    root = _fixture(tmp_path, "")
    (root / "notes").mkdir()
    (root / "notes/leak.md").write_text("Reach out to Dave directly for access.\n", encoding="utf-8")
    _git(root, "add", ".")

    result = _run(root)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "notes/leak.md" in combined
    assert '"token": "dave"' in combined


def test_gate_passes_on_clean_and_allowlisted_tree(tmp_path):
    root = _fixture(tmp_path, "^README\\.md:.*:dave$\n")
    (root / "README.md").write_text("# Dex by Dave\n", encoding="utf-8")
    (root / "safe.md").write_text("A perfectly ordinary sentence.\n", encoding="utf-8")
    _git(root, "add", ".")

    result = _run(root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No un-allowlisted founder-personal content" in result.stdout


def test_gate_ignores_canonical_davekilleen_handle(tmp_path):
    # \b does not break inside "davekilleen", so the canonical repo URL/handle is
    # not a finding and needs no allowlist entry.
    root = _fixture(tmp_path, "")
    (root / "urls.md").write_text(
        "Clone https://github.com/davekilleen/dex and adopt @davekilleen.\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")

    result = _run(root)

    assert result.returncode == 0, result.stdout + result.stderr


def test_removing_allowlist_entry_turns_gate_red(tmp_path):
    # With the entry the legitimate branding passes; remove it and the same tree
    # goes red — proving the gate is not a silent no-op.
    allowlisted = _fixture(tmp_path / "with", "^README\\.md:.*:dave$\n")
    (allowlisted / "README.md").write_text("# Dex by Dave\n", encoding="utf-8")
    _git(allowlisted, "add", ".")
    assert _run(allowlisted).returncode == 0

    bare = _fixture(tmp_path / "without", "")
    (bare / "README.md").write_text("# Dex by Dave\n", encoding="utf-8")
    _git(bare, "add", ".")
    result = _run(bare)

    assert result.returncode != 0
    assert '"file": "README.md"' in result.stdout


@pytest.mark.parametrize(
    "leak",
    (
        "~/dex/product/notes.md",
        "~/Vault/System/credentials",
        "$HOME/dex/product",
        "path.join(os.homedir(), 'Vault')",
        # Built at runtime: a literal /Users/ path in source would trip
        # scripts/verify-distribution.sh's own hardcoded-path scan.
        "/".join(("", "Users", "founder", "private", "dex")),
    ),
)
def test_gate_flags_personal_layout_paths(tmp_path, leak):
    root = _fixture(tmp_path, "")
    (root / "leak.md").write_text(f"{leak}\n", encoding="utf-8")
    _git(root, "add", ".")

    result = _run(root)

    assert result.returncode != 0
    assert '"file": "leak.md"' in result.stdout
    assert '"token": "personal-path"' in result.stdout


@pytest.mark.parametrize("name", ("alice", "testuser", "yourname"))
def test_gate_allows_documented_user_path_placeholders(tmp_path, name):
    root = _fixture(tmp_path, "")
    placeholder_path = "/".join(("", "Users", name, "Documents", "dex"))
    (root / "example.md").write_text(f"{placeholder_path}\n", encoding="utf-8")
    _git(root, "add", ".")

    result = _run(root)

    assert result.returncode == 0, result.stdout + result.stderr
