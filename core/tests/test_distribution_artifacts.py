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
    version = json.loads((clone / "package.json").read_text(encoding="utf-8"))["version"]
    subprocess.run(
        ["git", "tag", "--delete", f"dist-v{version}"],
        cwd=clone,
        check=False,
        capture_output=True,
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
    assert "core/update/ownership.json" in members
    assert "core/update/apply-update.cjs" in members
    assert "core/migrations/v1-to-v2-brain-vault-split.cjs" in members
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

    version = package_json["version"]
    release_oid = subprocess.run(
        ["git", "rev-parse", "release^{commit}"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dist_oid = subprocess.run(
        ["git", "rev-parse", f"dist-v{version}^{{commit}}"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    main_oid = subprocess.run(
        ["git", "rev-parse", "main^{commit}"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert dist_oid == release_oid
    assert dist_oid != main_oid

    bridge_paths = {
        "01-Quarter_Goals/Quarter_Goals.md",
        "02-Week_Priorities/Week_Priorities.md",
        "03-Tasks/Tasks.md",
    }
    bridge_paths.update(
        subprocess.run(
            [
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                "main",
                "--",
                "06-Resources/Dex_System",
            ],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    assert len(bridge_paths) > 3
    assert bridge_paths <= members


def _prepare_install_runtime(
    install_root: Path,
    *,
    include_git: bool = True,
) -> dict[str, str]:
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

    runtime_path = f"{fake_bin}{os.pathsep}{os.environ['PATH']}"
    if not include_git:
        for command in ("node", "python3", "cut", "grep", "sed"):
            executable = shutil.which(command)
            assert executable is not None, command
            (fake_bin / command).symlink_to(executable)
        runtime_path = str(fake_bin)

    return {
        **os.environ,
        "OSTYPE": "linux-gnu",
        "PATH": runtime_path,
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
    env = _prepare_install_runtime(install_root, include_git=False)

    result = subprocess.run(
        ["/bin/bash", "install.sh"],
        cwd=install_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Git is not installed" in result.stdout
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


def test_distribution_check_rejects_a_release_that_strips_bridge_paths(
    tmp_path: Path,
) -> None:
    clone = _clone_repo(tmp_path, "bridge-release-check")
    shutil.copy2(REPO_ROOT / "scripts/verify-distribution.sh", clone / "scripts/verify-distribution.sh")
    with (clone / ".distignore").open("a", encoding="utf-8") as distignore:
        distignore.write("\n03-Tasks/Tasks.md\n")
    subprocess.run(
        ["git", "add", "--", ".distignore", "scripts/verify-distribution.sh"],
        cwd=clone,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test: strip a bridge seed"],
        cwd=clone,
        check=True,
    )

    result = subprocess.run(
        ["bash", "scripts/verify-distribution.sh"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert result.returncode == 1
    assert "Bridge release path missing: 03-Tasks/Tasks.md" in result.stdout


def test_distribution_check_rejects_a_stripped_split_runtime_dependency(
    tmp_path: Path,
) -> None:
    clone = _clone_repo(tmp_path, "split-runtime-check")
    shutil.copy2(REPO_ROOT / "scripts/verify-distribution.sh", clone / "scripts/verify-distribution.sh")
    with (clone / ".distignore").open("a", encoding="utf-8") as distignore:
        distignore.write("\ncore/update/ownership.cjs\n")
    subprocess.run(
        ["git", "add", "--", ".distignore", "scripts/verify-distribution.sh"],
        cwd=clone,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test: strip split runtime dependency"],
        cwd=clone,
        check=True,
    )

    result = subprocess.run(
        ["bash", "scripts/verify-distribution.sh"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert result.returncode == 1
    assert "Required split release file missing: core/update/ownership.cjs" in result.stdout


def test_distribution_check_pins_non_seed_and_dex_system_bridge_paths(
    tmp_path: Path,
) -> None:
    clone = _clone_repo(tmp_path, "full-bridge-check")
    shutil.copy2(REPO_ROOT / "scripts/verify-distribution.sh", clone / "scripts/verify-distribution.sh")
    subprocess.run(
        [
            "git",
            "rm",
            "--quiet",
            "--",
            "00-Inbox/README.md",
            "06-Resources/Dex_System/README.md",
        ],
        cwd=clone,
        check=True,
    )
    subprocess.run(
        ["git", "add", "--", "scripts/verify-distribution.sh"],
        cwd=clone,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test: delete bridge release paths"],
        cwd=clone,
        check=True,
    )

    result = subprocess.run(
        ["bash", "scripts/verify-distribution.sh"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert result.returncode == 1
    assert "Bridge release path missing: 00-Inbox/README.md" in result.stdout
    assert "Bridge release path missing: 06-Resources/Dex_System/README.md" in result.stdout


def test_ci_validates_the_generated_release_manifest() -> None:
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Build release for ownership validation" in workflow
    assert "scripts/build-release.sh\" --no-tag" in workflow
    assert "archive --output=\"$RUNNER_TEMP/release-artifact.tar\" release" in workflow
    assert "tar -xf \"$RUNNER_TEMP/release-artifact.tar\"" in workflow
    assert 'node "$RELEASE_ARTIFACT/core/update/ownership.cjs" --validate' in workflow

    distribution_check = (REPO_ROOT / "scripts/verify-distribution.sh").read_text(
        encoding="utf-8"
    )
    assert 'archive --output="$RELEASE_ARCHIVE" release' in distribution_check
    assert 'tar -xf "$RELEASE_ARCHIVE"' in distribution_check


def test_release_build_refuses_to_move_an_existing_dist_tag(tmp_path: Path) -> None:
    clone, _ = _build_release_in_clone(tmp_path)
    version = json.loads((clone / "package.json").read_text(encoding="utf-8"))["version"]
    tag = f"dist-v{version}"
    original_dist_oid = subprocess.run(
        ["git", "rev-parse", f"{tag}^{{commit}}"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    with (clone / "install.sh").open("a", encoding="utf-8") as install_script:
        install_script.write("\n# changed distributed bytes without a version bump\n")
    subprocess.run(["git", "add", "install.sh"], cwd=clone, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test: change same-version release bytes"],
        cwd=clone,
        check=True,
    )

    result = subprocess.run(
        ["bash", "scripts/build-release.sh"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 1
    assert "immutable" in (result.stdout + result.stderr).lower()
    assert subprocess.run(
        ["git", "rev-parse", f"{tag}^{{commit}}"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == original_dist_oid


def test_release_build_reproduces_the_stripped_commit_oid(tmp_path: Path) -> None:
    clone, _ = _build_release_in_clone(tmp_path)
    version = json.loads((clone / "package.json").read_text(encoding="utf-8"))["version"]
    first_oid = subprocess.run(
        ["git", "rev-parse", "release^{commit}"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "tag", "--delete", f"dist-v{version}"], cwd=clone, check=True)
    subprocess.run(["git", "branch", "--delete", "--force", "release"], cwd=clone, check=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2037-01-02T03:04:05Z",
        "GIT_COMMITTER_DATE": "2037-01-02T03:04:05Z",
    }

    subprocess.run(
        ["bash", "scripts/build-release.sh"],
        cwd=clone,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert subprocess.run(
        ["git", "rev-parse", "release^{commit}"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == first_oid


def test_tag_release_workflow_builds_and_pushes_the_stripped_dist_commit() -> None:
    workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    ci_workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release_script = (REPO_ROOT / "scripts/release.sh").read_text(encoding="utf-8")

    assert "DEX_RELEASE_SOURCE" in workflow
    assert "bash scripts/build-release.sh" in workflow
    assert 'node "$RELEASE_ARTIFACT/core/update/ownership.cjs" --validate' in workflow
    assert 'refs/tags/dist-v${VERSION}' in workflow
    assert "git push origin release" not in ci_workflow
    assert "release workflow" in release_script.lower()
    assert "workflow_call:" in ci_workflow
    assert "uses: ./.github/workflows/ci.yml" in workflow
    assert "needs: quality" in workflow
    assert "git push --atomic" in workflow
