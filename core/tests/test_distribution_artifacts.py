"""Regression tests for artifacts produced from the public repository."""

from __future__ import annotations

import io
import json
import os
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
    "install.sh",
    "package.json",
    "requirements.txt",
    "requirements-dev.txt",
    "core/utils/manifest.py",
    "core/utils/smoke.py",
    "core/migrations/v1-to-v2-brain-vault-split.cjs",
    "core/update/ownership.cjs",
    "core/update/ownership.json",
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


def _build_release_in_clone(tmp_path: Path) -> tuple[Path, set[str]]:
    """Build from the current checkout without ever switching its branches."""
    clone = _clone_repo(tmp_path, "release-build")
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
    assert "test" not in package_json.get("scripts", {})
    assert "test:hooks" not in package_json.get("scripts", {})
    assert "test:scripts" not in package_json.get("scripts", {})


def _prepare_install_runtime(install_root: Path) -> dict[str, str]:
    fake_bin = install_root.parent / "fake-bin"
    fake_bin.mkdir(exist_ok=True)
    pnpm = fake_bin / "pnpm"
    pnpm.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pnpm.chmod(0o755)

    venv_bin = install_root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    pip = venv_bin / "pip"
    pip.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pip.chmod(0o755)
    python = venv_bin / "python"
    python.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"core/paths.py\" ]; then printf '{}\\n' > core/paths.json; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    python.chmod(0o755)

    return {
        **os.environ,
        "OSTYPE": "linux-gnu",
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
    }


def _assert_split_install(install_root: Path) -> None:
    assert (install_root / ".git" / "dex-vault-v2").is_file()
    assert (install_root / ".dex" / "brain.git" / "dex-brain-v2").is_file()
    assert (install_root / ".dex" / "pre-split-archive.git").is_dir()

    topology = json.loads(
        (install_root / "System/.dex/topology.json").read_text(encoding="utf-8")
    )
    assert topology["topology"] == "brain-vault-split"
    installed = subprocess.run(
        [
            "git",
            f"--git-dir={install_root / '.dex/brain.git'}",
            "rev-parse",
            "refs/dex/installed",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert installed == topology["installedRelease"]
    assert subprocess.run(
        ["git", "remote"],
        cwd=install_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""
    assert subprocess.run(
        [
            "git",
            f"--git-dir={install_root / '.dex/brain.git'}",
            "remote",
            "get-url",
            "origin",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "https://github.com/davekilleen/Dex.git"
    assert "vault_schema: 1" in (
        install_root / "System/user-profile.yaml"
    ).read_text(encoding="utf-8")
    assert "## USER_EXTENSIONS_START" not in (
        install_root / "CLAUDE.md"
    ).read_text(encoding="utf-8")
    assert (install_root / "CLAUDE-custom.md").is_file()


def test_fresh_clone_install_converges_to_split_topology_and_reruns_safely(
    tmp_path: Path,
) -> None:
    release_repo, _ = _build_release_in_clone(tmp_path)
    install_root = tmp_path / "fresh-install"
    subprocess.run(
        [
            "git",
            "clone",
            "--local",
            "--no-hardlinks",
            "--quiet",
            "--branch",
            "release",
            str(release_repo),
            str(install_root),
        ],
        check=True,
    )
    subprocess.run(
        ["git", "remote", "set-url", "origin", "https://github.com/davekilleen/Dex.git"],
        cwd=install_root,
        check=True,
    )
    env = _prepare_install_runtime(install_root)

    first = subprocess.run(
        ["bash", "install.sh"],
        cwd=install_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    _assert_split_install(install_root)
    first_vault_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=install_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    second = subprocess.run(
        ["bash", "install.sh"],
        cwd=install_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    _assert_split_install(install_root)
    assert subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=install_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == first_vault_head


def test_zip_install_stays_unsplit_and_explains_manual_updates(tmp_path: Path) -> None:
    release_repo, _ = _build_release_in_clone(tmp_path)
    install_root = tmp_path / "zip-install"
    install_root.mkdir()
    archive = subprocess.run(
        ["git", "archive", "release"],
        cwd=release_repo,
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as release_archive:
        release_archive.extractall(install_root)
    env = _prepare_install_runtime(install_root)

    result = subprocess.run(
        ["bash", "install.sh"],
        cwd=install_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (install_root / ".git").exists()
    assert not (install_root / ".dex/brain.git").exists()
    report = (install_root / "System/migration-report-v2.md").read_text(encoding="utf-8")
    assert "downloaded as a ZIP" in report
    assert "manual-update path" in report
    assert "automatic updates are unavailable" in result.stdout.lower()


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
            "System/integrations/.sync-state.json",
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
