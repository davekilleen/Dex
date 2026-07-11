"""Regression tests for artifacts produced from the public repository."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

RELEASE_BUILD_INPUTS = (
    ".distignore",
    ".gitattributes",
    ".github/workflows/ci.yml",
    "requirements.txt",
    "requirements-dev.txt",
    "core/utils/manifest.py",
    "core/utils/smoke.py",
    "scripts/build-release.sh",
    "scripts/generate-manifest.sh",
    "scripts/verify-distribution.sh",
)


def _archive_members() -> set[str]:
    """Return paths from the archive users receive from the current checkout."""
    result = subprocess.run(
        ["git", "archive", "--worktree-attributes", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        return set(archive.getnames())


def test_git_archive_keeps_skill_scripts_but_strips_top_level_scripts() -> None:
    members = _archive_members()

    assert ".claude/skills/anthropic-docx/scripts/document.py" in members
    assert not any(path == "scripts" or path.startswith("scripts/") for path in members)


def _build_release_in_clone(tmp_path: Path) -> tuple[Path, set[str]]:
    """Build from the current checkout without ever switching its branches."""
    clone = tmp_path / "release-build"
    subprocess.run(
        ["git", "clone", "--local", "--no-hardlinks", "--quiet", str(REPO_ROOT), str(clone)],
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Dex Tests"], cwd=clone, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=clone, check=True)
    subprocess.run(["git", "checkout", "-B", "main", "HEAD"], cwd=clone, check=True, capture_output=True)

    # Let this test prove uncommitted changes while developing; once committed,
    # these copies are identical to the clone's files.
    for relative_path in RELEASE_BUILD_INPUTS:
        source = REPO_ROOT / relative_path
        destination = clone / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    spaced_fixture = clone / "core/tests/fixtures/vault/has space.md"
    spaced_fixture.write_text("release stripping regression\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "--", *RELEASE_BUILD_INPUTS, str(spaced_fixture.relative_to(clone))],
        cwd=clone,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test: prepare release build fixture"],
        cwd=clone,
        check=True,
    )

    subprocess.run(
        ["bash", "scripts/build-release.sh"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "release"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    )
    return clone, set(result.stdout.splitlines())


def test_release_branch_strips_dev_files_and_keeps_user_runtime(tmp_path: Path) -> None:
    clone, members = _build_release_in_clone(tmp_path)

    stripped_prefixes = (
        "core/tests/",
        "core/mcp/tests/",
        "core/migrations/tests/",
        ".claude/hooks/tests/",
        "scripts/",
    )
    for prefix in stripped_prefixes:
        assert not any(path.startswith(prefix) for path in members), prefix
    assert "pyproject.toml" not in members
    assert "requirements-dev.txt" not in members
    assert "core/tests/fixtures/vault/has space.md" not in members

    assert "core/utils/doctor.py" in members
    assert "core/utils/manifest.py" in members
    assert "core/utils/smoke.py" in members
    assert ".claude/skills/dex-update/SKILL.md" in members
    assert ".claude/skills/anthropic-docx/scripts/document.py" in members
    assert "System/.installed-files.manifest" in members

    manifest = subprocess.run(
        ["git", "show", "release:System/.installed-files.manifest"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert manifest == sorted(manifest)
    assert set(manifest) == members
    assert "core/tests/test_distribution_artifacts.py" not in manifest

    subprocess.run(
        ["git", "checkout", "--quiet", "release"],
        cwd=clone,
        check=True,
    )
    smoke_result = subprocess.run(
        [sys.executable, "core/utils/smoke.py", "--json"],
        cwd=clone,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert smoke_result.returncode == 0, smoke_result.stderr or smoke_result.stdout
    assert json.loads(smoke_result.stdout)["schema_version"] == 1
    assert subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""

    source_servers = {
        path
        for path in subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "main", "--", "core/mcp"],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        if path.endswith("_server.py") and "/tests/" not in path
    }
    assert source_servers
    assert source_servers <= members

    package_json = json.loads(
        subprocess.run(
            ["git", "show", "release:package.json"],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert "test:hooks" not in package_json.get("scripts", {})
