"""Regression tests for artifacts produced from the public repository."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import yaml

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
    "core/utils/update_verifier.py",
    "core/utils/smoke.py",
    "scripts/build-release.sh",
    "scripts/build-vault-bundle.sh",
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


def _git_json(clone: Path, revision_path: str) -> dict[str, object]:
    return json.loads(
        subprocess.run(
            ["git", "show", revision_path],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )


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
    assert "core/utils/update_verifier.py" in members
    assert ".claude/skills/dex-update/SKILL.md" in members
    assert ".claude/skills/anthropic-docx/scripts/document.py" in members
    assert "System/.installed-files.manifest" in members
    assert "System/.release-evidence-profile.json" in members

    manifest = _release_manifest(clone, "release")
    assert manifest == sorted(manifest)
    assert set(manifest) == members
    assert "core/tests/test_distribution_artifacts.py" not in manifest
    profile = json.loads(
        subprocess.run(
            ["git", "show", "release:System/.release-evidence-profile.json"],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert profile == {"schema_version": 1, "profile": "legacy-v1", "release_version": "1.61.0"}

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
    assert "System/.release-evidence-profile.json" in beta_members
    assert not any(path.startswith("core/tests/") for path in beta_members)
    assert not any(path.startswith("scripts/") for path in beta_members)
    assert set(_release_manifest(clone, "release-beta")) == beta_members
    beta_version = _git_json(clone, "release-beta:package.json")["version"]
    beta_short_sha = subprocess.run(
        ["git", "rev-parse", "--short", "release-beta"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    beta_tag = f"dist/release-beta/v{beta_version}-{beta_short_sha}"
    assert subprocess.run(
        ["git", "rev-parse", f"{beta_tag}^{{}}"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == subprocess.run(
        ["git", "rev-parse", "release-beta"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_release_build_uses_selected_source_version_for_tree_profile_manifest_and_tag(tmp_path: Path) -> None:
    clone = _clone_repo(tmp_path, "selected-source-version")
    subprocess.run(["git", "checkout", "-B", "main", "HEAD"], cwd=clone, check=True, capture_output=True)
    for relative_path in RELEASE_BUILD_INPUTS:
        destination = clone / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative_path, destination)
    subprocess.run(["git", "add", "--", *RELEASE_BUILD_INPUTS], cwd=clone, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "--allow-empty", "-m", "test: current builder"], cwd=clone, check=True
    )
    subprocess.run(["git", "checkout", "-b", "selected"], cwd=clone, check=True, capture_output=True)
    selected_package = json.loads((clone / "package.json").read_text())
    selected_package["version"] = "2.3.4"
    (clone / "package.json").write_text(json.dumps(selected_package, indent=2) + "\n")
    subprocess.run(["git", "add", "package.json"], cwd=clone, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "selected v2.3.4"], cwd=clone, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=clone, check=True, capture_output=True)
    current_package = json.loads((clone / "package.json").read_text())
    current_package["version"] = "9.8.7"
    (clone / "package.json").write_text(json.dumps(current_package, indent=2) + "\n")
    subprocess.run(["git", "add", "package.json"], cwd=clone, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "current v9.8.7"], cwd=clone, check=True)

    subprocess.run(
        ["bash", "scripts/build-release.sh", "--source", "selected", "--target", "release-selected"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert _git_json(clone, "release-selected:package.json")["version"] == "2.3.4"
    assert _git_json(clone, "release-selected:System/.release-evidence-profile.json")["release_version"] == "2.3.4"
    members = set(
        subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "release-selected"],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    assert set(_release_manifest(clone, "release-selected")) == members
    short = subprocess.run(
        ["git", "rev-parse", "--short", "release-selected"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tag = f"dist/release-selected/v2.3.4-{short}"
    assert subprocess.run(
        ["git", "rev-parse", f"{tag}^{{}}"], cwd=clone, check=True, capture_output=True, text=True
    ).stdout.strip() == subprocess.run(
        ["git", "rev-parse", "release-selected"], cwd=clone, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert not subprocess.run(
        ["git", "tag", "--list", "dist/release-selected/v9.8.7-*"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_release_build_rejects_malformed_selected_package_before_creating_refs(tmp_path: Path) -> None:
    clone = _clone_repo(tmp_path, "malformed-selected-source")
    subprocess.run(["git", "checkout", "-B", "main", "HEAD"], cwd=clone, check=True, capture_output=True)
    for relative_path in RELEASE_BUILD_INPUTS:
        destination = clone / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative_path, destination)
    subprocess.run(["git", "add", "--", *RELEASE_BUILD_INPUTS], cwd=clone, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "--allow-empty", "-m", "test: current builder"], cwd=clone, check=True
    )
    subprocess.run(["git", "checkout", "-b", "malformed"], cwd=clone, check=True, capture_output=True)
    (clone / "package.json").write_text('{"version":"2.0.0","version":"3.0.0"}\n')
    subprocess.run(["git", "add", "package.json"], cwd=clone, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "malformed package"], cwd=clone, check=True)
    subprocess.run(["git", "checkout", "main"], cwd=clone, check=True, capture_output=True)

    result = subprocess.run(
        ["bash", "scripts/build-release.sh", "--source", "malformed", "--target", "release-malformed"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 1
    assert "selected package.json is invalid" in result.stderr
    assert subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/release-malformed"], cwd=clone
    ).returncode == 1
    assert not subprocess.run(
        ["git", "tag", "--list", "dist/release-malformed/*"], cwd=clone, capture_output=True, text=True
    ).stdout


def test_raw_vault_bundle_has_package_profile_manifest_agreement(tmp_path: Path) -> None:
    clone = _clone_repo(tmp_path, "raw-vault-bundle")
    for relative_path in RELEASE_BUILD_INPUTS:
        destination = clone / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative_path, destination)
    # Prove the builder regenerates the declaration rather than copying stale bytes.
    (clone / "System/.release-evidence-profile.json").write_text(
        json.dumps({"profile": "legacy-v1", "release_version": "0.0.1", "schema_version": 1}, indent=2) + "\n"
    )
    output = tmp_path / "bundle-output"
    subprocess.run(
        ["bash", "scripts/build-vault-bundle.sh", str(output)],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    archive_path = next(output.glob("dex-vault-bundle-v*.tar.gz"))
    with tarfile.open(archive_path, "r:gz") as archive:
        package = json.load(archive.extractfile("./package.json"))
        profile = json.load(archive.extractfile("./System/.release-evidence-profile.json"))
        manifest = archive.extractfile("./System/.installed-files.manifest").read().decode().splitlines()
        shipped = {
            member.name.removeprefix("./")
            for member in archive.getmembers()
            if member.isfile() or member.issym()
            if not member.name.removeprefix("./").startswith("node_modules/")
        }
    assert package["version"] == profile["release_version"]
    assert profile["profile"] == "legacy-v1"
    assert manifest == sorted(set(manifest))
    assert set(manifest) == shipped


def test_release_script_regenerates_profile_for_bumped_version(tmp_path: Path) -> None:
    clone = _clone_repo(tmp_path, "release-script-profile")
    for relative_path in (
        "scripts/release.sh",
        "scripts/generate-manifest.sh",
        "core/utils/manifest.py",
        "core/utils/update_verifier.py",
    ):
        shutil.copy2(REPO_ROOT / relative_path, clone / relative_path)
    subprocess.run(["git", "add", "--", "scripts", "core/utils"], cwd=clone, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "--allow-empty", "-m", "test: current release scripts"],
        cwd=clone,
        check=True,
    )

    subprocess.run(
        ["bash", "scripts/release.sh", "patch"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    package = _git_json(clone, "HEAD:package.json")
    profile = _git_json(clone, "HEAD:System/.release-evidence-profile.json")
    assert package["version"] == "1.61.1"
    assert profile == {"profile": "legacy-v1", "release_version": "1.61.1", "schema_version": 1}
    assert "System/.release-evidence-profile.json" in _release_manifest(clone, "HEAD")
    assert subprocess.run(
        ["git", "rev-parse", "v1.61.1^{}"], cwd=clone, check=True, capture_output=True, text=True
    ).stdout.strip() == subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=clone, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_every_release_path_invokes_legacy_profile_generation() -> None:
    expected = {
        "scripts/build-release.sh": (
            "--write-legacy-profile \"$PROFILE\"",
            "--release-version \"$PKG_VERSION\"",
        ),
        "scripts/build-vault-bundle.sh": (
            '--write-legacy-profile "$STAGING_DIR/System/.release-evidence-profile.json"',
            '--release-version "$VERSION"',
        ),
        "scripts/release.sh": (
            "--write-legacy-profile System/.release-evidence-profile.json",
            '--release-version "$NEW_VERSION"',
        ),
    }
    for relative_path, required_lines in expected.items():
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        for required_line in required_lines:
            assert source.count(required_line) == 1, (relative_path, required_line)
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


def test_release_build_creates_immutable_versioned_tags(tmp_path: Path) -> None:
    clone, _ = _build_release_in_clone(tmp_path, name="immutable-release-tags")
    version = json.loads((clone / "package.json").read_text(encoding="utf-8"))["version"]
    first_release_sha = subprocess.run(
        ["git", "rev-parse", "release"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    first_short_sha = subprocess.run(
        ["git", "rev-parse", "--short", "release"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    first_tag = f"dist/release/v{version}-{first_short_sha}"

    assert subprocess.run(
        ["git", "cat-file", "-t", first_tag],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "tag"
    assert subprocess.run(
        ["git", "rev-parse", f"{first_tag}^{{}}"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == first_release_sha
    assert _release_manifest(clone, first_tag)

    package_path = clone / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["version"] = "99.0.0"
    package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "package.json"], cwd=clone, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test: bump release version"],
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

    second_short_sha = subprocess.run(
        ["git", "rev-parse", "--short", "release"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    second_tag = f"dist/release/v99.0.0-{second_short_sha}"
    assert second_tag != first_tag
    assert subprocess.run(
        ["git", "rev-parse", f"{first_tag}^{{}}"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == first_release_sha
    assert subprocess.run(
        ["git", "rev-parse", f"{second_tag}^{{}}"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() != first_release_sha


def test_beta_release_ci_builds_branch_and_tag_without_github_release() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    beta_job = workflow["jobs"]["build-release-beta"]
    beta_commands = "\n".join(step.get("run", "") for step in beta_job["steps"])

    assert beta_job["if"] == "github.ref == 'refs/heads/beta' && github.event_name == 'push'"
    assert beta_job["permissions"] == {"contents": "write"}
    assert "bash scripts/build-release.sh --source beta --target release-beta" in beta_commands
    assert "git push origin release-beta --force" in beta_commands
    assert "git push origin \"${{ steps.release_build.outputs.release_tag }}\"" in beta_commands
    assert "gh release" not in beta_commands


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
