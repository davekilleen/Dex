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
    ".gitignore",
    ".github/workflows/ci.yml",
    ".scripts/lib/tests/entity-pages.test.cjs",
    "package.json",
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
    assert not any(path == ".logs" or path.startswith(".logs/") for path in members)


def test_repository_tracks_no_runtime_logs() -> None:
    result = subprocess.run(
        ["git", "ls-files", "--", ".logs"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == []


def _clone_repo(tmp_path: Path, name: str) -> Path:
    clone = tmp_path / name
    subprocess.run(
        ["git", "clone", "--local", "--no-hardlinks", "--quiet", str(REPO_ROOT), str(clone)],
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Dex Tests"], cwd=clone, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=clone, check=True)
    return clone


def _build_release_in_clone(
    tmp_path: Path,
    *,
    source: str = "main",
    target: str = "release",
    name: str = "release-build",
) -> tuple[Path, set[str]]:
    """Build from the current checkout without ever switching its branches."""
    clone = _clone_repo(tmp_path, name)
    subprocess.run(["git", "checkout", "-B", "main", "HEAD"], cwd=clone, check=True, capture_output=True)

    # Let this test prove uncommitted changes while developing; once committed,
    # these copies are identical to the clone's files.
    for relative_path in RELEASE_BUILD_INPUTS:
        file_source = REPO_ROOT / relative_path
        destination = clone / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_source, destination)

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

    command = ["bash", "scripts/build-release.sh"]
    if (source, target) != ("main", "release"):
        subprocess.run(["git", "branch", source, "main"], cwd=clone, check=True)
        command.extend(["--source", source, "--target", target])

    subprocess.run(
        command,
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", target],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    )
    return clone, set(result.stdout.splitlines())


def _release_manifest(clone: Path, branch: str) -> list[str]:
    return subprocess.run(
        ["git", "show", f"{branch}:System/.installed-files.manifest"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()


def test_release_branch_strips_dev_files_and_keeps_user_runtime(tmp_path: Path) -> None:
    clone, members = _build_release_in_clone(tmp_path)

    stripped_prefixes = (
        ".logs/",
        "core/tests/",
        "core/mcp/tests/",
        "core/migrations/tests/",
        ".claude/hooks/tests/",
        ".scripts/lib/tests/",
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

    manifest = _release_manifest(clone, "release")
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
        # Generous sanity ceiling, not a perf assertion: the smoke run spawns several
        # subprocess journeys, which can exceed a tight 30s budget on a loaded CI runner
        # and flake this test even though the run succeeds.
        timeout=90,
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
    assert "test:scripts" not in package_json.get("scripts", {})


def test_beta_release_branch_uses_same_stripping_and_manifest(tmp_path: Path) -> None:
    clone, beta_members = _build_release_in_clone(
        tmp_path,
        source="beta",
        target="release-beta",
        name="beta-release-build",
    )

    assert "System/.installed-files.manifest" in beta_members
    assert not any(path.startswith("core/tests/") for path in beta_members)
    assert not any(path.startswith("scripts/") for path in beta_members)
    assert set(_release_manifest(clone, "release-beta")) == beta_members


def test_release_build_rejects_invalid_source_and_target_branches(tmp_path: Path) -> None:
    clone = _clone_repo(tmp_path, "release-build-guards")
    subprocess.run(["git", "checkout", "-B", "main", "HEAD"], cwd=clone, check=True)

    same_branch = subprocess.run(
        ["bash", "scripts/build-release.sh", "--source", "main", "--target", "main"],
        cwd=clone,
        capture_output=True,
        text=True,
    )
    missing_source = subprocess.run(
        ["bash", "scripts/build-release.sh", "--source", "not-a-branch"],
        cwd=clone,
        capture_output=True,
        text=True,
    )

    assert same_branch.returncode == 1
    assert "source and target branches must differ" in same_branch.stderr
    assert missing_source.returncode == 1
    assert "branch 'not-a-branch' not found" in missing_source.stderr


def test_distribution_check_rejects_enabled_integration_templates(tmp_path: Path) -> None:
    clone = _clone_repo(tmp_path, "integration-template-check")

    shutil.copy2(REPO_ROOT / "scripts/verify-distribution.sh", clone / "scripts/verify-distribution.sh")
    integrations = clone / "System/integrations"
    (integrations / "config.yaml").write_text(
        "enabled:\n  notion: false\nhooks:\n  meeting_prep:\n    use_notion: false\n",
        encoding="utf-8",
    )
    (integrations / "enabled-fixture.yaml").write_text("enabled: true\n", encoding="utf-8")
    (integrations / "hooks-fixture.yaml").write_text(
        "enabled: false\nhooks:\n  meeting_prep: true\n",
        encoding="utf-8",
    )
    (integrations / "flow-fixture.yaml").write_text(
        "slack: {enabled: true}\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "rm",
            "--quiet",
            "--",
            "System/integrations/slack.yaml",
        ],
        cwd=clone,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "add",
            "-f",
            "--",
            "scripts/verify-distribution.sh",
            "System/integrations/config.yaml",
            "System/integrations/enabled-fixture.yaml",
            "System/integrations/flow-fixture.yaml",
            "System/integrations/hooks-fixture.yaml",
        ],
        cwd=clone,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test: add unsafe integration templates"],
        cwd=clone,
        check=True,
    )

    result = subprocess.run(
        ["bash", "scripts/verify-distribution.sh"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 1
    assert "enabled-fixture.yaml:1:enabled: true" in result.stdout
    assert "flow-fixture.yaml:1:slack: {enabled: true}" in result.stdout
    assert "hooks-fixture.yaml:3:  meeting_prep: true" in result.stdout
