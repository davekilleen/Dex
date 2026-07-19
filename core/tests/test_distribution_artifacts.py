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

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

RELEASE_BUILD_INPUTS = (
    ".distignore",
    ".gitattributes",
    ".gitignore",
    ".github/workflows/ci.yml",
    ".scripts/lib/tests/entity-pages.test.cjs",
    "06-Resources/Dex_System/Dex_Technical_Guide.md",
    "package.json",
    "requirements.txt",
    "requirements-dev.txt",
    "core/utils/manifest.py",
    "core/utils/smoke.py",
    "scripts/build-release.sh",
    "scripts/build-vault-bundle.sh",
    "scripts/check-tau-removal.py",
    "scripts/generate-manifest.sh",
    "scripts/security-gate.sh",
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


def _sync_release_inputs(clone: Path) -> None:
    """Copy changed build inputs for pre-commit test runs."""
    for relative_path in RELEASE_BUILD_INPUTS:
        file_source = REPO_ROOT / relative_path
        destination = clone / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_source, destination)


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
    _sync_release_inputs(clone)

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


def _run_tau_check(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/check-tau-removal.py", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _build_git_archive(repo: Path, treeish: str, output: Path) -> set[str]:
    with output.open("wb") as archive_file:
        subprocess.run(
            ["git", "archive", "--format=tar", treeish],
            cwd=repo,
            check=True,
            stdout=archive_file,
        )
    with tarfile.open(output, mode="r:") as archive:
        return set(archive.getnames())


def _assert_tau_absent(paths: set[str] | list[str]) -> None:
    normalized = [path.lower().removeprefix("./") for path in paths]
    assert not any("tau-mirror" in path or "tau_mirror" in path for path in normalized)


def _assert_tau_absent_from_release_artifacts(
    clone: Path, treeish: str, archive_path: Path
) -> None:
    tree_members = set(
        subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", treeish],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    _assert_tau_absent(tree_members)
    tree_check = _run_tau_check(
        clone, "--repo-root", str(clone), "--git-tree", treeish
    )
    assert tree_check.returncode == 0, tree_check.stdout + tree_check.stderr

    archive_members = _build_git_archive(clone, treeish, archive_path)
    _assert_tau_absent(archive_members)
    archive_check = _run_tau_check(clone, "--archive", str(archive_path))
    assert archive_check.returncode == 0, archive_check.stdout + archive_check.stderr


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
    _assert_tau_absent_from_release_artifacts(
        clone, "release", tmp_path / "stable-release.tar"
    )

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
    _assert_tau_absent_from_release_artifacts(
        clone, "release-beta", tmp_path / "beta-release.tar"
    )
    beta_version = json.loads((clone / "package.json").read_text(encoding="utf-8"))["version"]
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


def test_tau_removal_source_package_lock_reference_and_quarantine_contract() -> None:
    result = _run_tau_check(REPO_ROOT, "--source-root", str(REPO_ROOT))
    assert result.returncode == 0, result.stdout + result.stderr

    distignore = (REPO_ROOT / ".distignore").read_text(encoding="utf-8").splitlines()
    assert "extensions/tau-mirror/" in distignore
    assert not any((REPO_ROOT / "extensions/tau-mirror").glob("**/*"))


def test_git_archive_contains_no_tau_release_member() -> None:
    members = _archive_members()
    _assert_tau_absent(members)


def test_vault_bundle_tree_manifest_and_archive_contain_no_tau(tmp_path: Path) -> None:
    clone = _clone_repo(tmp_path, "vault-bundle-build")
    _sync_release_inputs(clone)
    subprocess.run(["git", "add", "--", *RELEASE_BUILD_INPUTS], cwd=clone, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=clone).returncode != 0:
        subprocess.run(
            ["git", "commit", "--quiet", "-m", "test: prepare vault bundle fixture"],
            cwd=clone,
            check=True,
        )
    output_dir = tmp_path / "bundle-output"
    environment = os.environ.copy()
    environment["npm_config_offline"] = "true"
    build_result = subprocess.run(
        ["bash", "scripts/build-vault-bundle.sh", str(output_dir)],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )
    assert build_result.returncode == 0, build_result.stdout + build_result.stderr

    archive_path = next(output_dir.glob("dex-vault-bundle-v*.tar.gz"))
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getnames()
        _assert_tau_absent(members)
        manifest_member = archive.extractfile("./System/.installed-files.manifest")
        assert manifest_member is not None
        manifest = manifest_member.read().decode("utf-8").splitlines()
    _assert_tau_absent(manifest)
    tau_check = _run_tau_check(clone, "--archive", str(archive_path))
    assert tau_check.returncode == 0, tau_check.stdout + tau_check.stderr


def _prepare_tau_mutation_clone(tmp_path: Path, name: str) -> Path:
    clone = _clone_repo(tmp_path, name)
    _sync_release_inputs(clone)
    subprocess.run(["git", "add", "--", *RELEASE_BUILD_INPUTS], cwd=clone, check=True)
    return clone


def test_tau_gate_rejects_missing_distignore_quarantine(tmp_path: Path) -> None:
    clone = _prepare_tau_mutation_clone(tmp_path, "tau-distignore-mutation")
    distignore = clone / ".distignore"
    distignore.write_text(
        distignore.read_text(encoding="utf-8").replace("extensions/tau-mirror/\n", ""),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", ".distignore"], cwd=clone, check=True)

    result = _run_tau_check(clone, "--source-root", str(clone))
    assert result.returncode == 1
    assert "missing exact quarantine entry" in result.stdout


def test_tau_gate_rejects_reintroduced_source_path_and_release_build_input(tmp_path: Path) -> None:
    clone = _prepare_tau_mutation_clone(tmp_path, "tau-source-mutation")
    fixture = clone / "extensions/tau-mirror/loader.ts"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("export default {};\n", encoding="utf-8")
    subprocess.run(["git", "add", str(fixture.relative_to(clone))], cwd=clone, check=True)

    gate = _run_tau_check(clone, "--source-root", str(clone))
    build = subprocess.run(
        ["bash", "scripts/build-release.sh"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert gate.returncode == 1
    assert "removed Tau path" in gate.stdout
    assert build.returncode == 1
    assert "removed Tau path" in build.stdout
    assert subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/release"], cwd=clone
    ).returncode == 1


@pytest.mark.parametrize(
    ("filename", "content"),
    (
        ("npx-loader.ts", "spawn('npx', ['tau-mirror', '--port', '3001']);\n"),
        ("qr-loader.ts", "import qr from 'qrcode-terminal';\n"),
        (
            "pi-loader.ts",
            "import type { ExtensionAPI } from '@mariozechner/pi-coding-agent';\n",
        ),
        ("wildcard-bind.ts", "server.listen(3001, '0.0.0.0');\n"),
        ("lan-url.ts", "const interfaces = os.networkInterfaces();\n"),
        ("no-auth.md", "Authentication disabled for local access.\n"),
    ),
    ids=("npx-loader", "qr-dependency", "pi-dependency", "wildcard-bind", "lan-url", "no-auth"),
)
def test_tau_gate_rejects_loader_dependency_lan_and_auth_mutations(
    tmp_path: Path, filename: str, content: str
) -> None:
    clone = _prepare_tau_mutation_clone(tmp_path, f"tau-reference-mutation-{filename}")
    fixture = clone / "core/runtime-loaders" / filename
    fixture.parent.mkdir(parents=True)
    fixture.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", str(fixture.relative_to(clone))], cwd=clone, check=True)

    result = _run_tau_check(clone, "--source-root", str(clone))
    assert result.returncode == 1


@pytest.mark.parametrize(
    "dependency",
    ("tau-mirror", "qrcode-terminal", "@mariozechner/pi-coding-agent"),
    ids=("tau-mirror", "qrcode-terminal", "pi-coding-agent"),
)
def test_tau_gate_rejects_package_and_lock_dependencies(
    tmp_path: Path, dependency: str
) -> None:
    clone = _prepare_tau_mutation_clone(
        tmp_path, f"tau-dependency-mutation-{dependency.replace('/', '-')}"
    )
    package_path = clone / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package.setdefault("dependencies", {})[dependency] = "1.0.0"
    package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    lock_path = clone / "package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock.setdefault("packages", {})[f"node_modules/{dependency}"] = {"version": "1.0.0"}
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "package.json", "package-lock.json"], cwd=clone, check=True)

    result = _run_tau_check(clone, "--source-root", str(clone))
    assert result.returncode == 1
    assert "forbidden dependency" in result.stdout


def test_tau_gate_rejects_legacy_manifest_and_archive_members(tmp_path: Path) -> None:
    clone = _prepare_tau_mutation_clone(tmp_path, "tau-manifest-mutation")
    manifest = clone / "System/.installed-files.manifest"
    manifest.write_text("extensions/tau-mirror/loader.ts\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", str(manifest.relative_to(clone))], cwd=clone, check=True)
    manifest_result = _run_tau_check(clone, "--source-root", str(clone))
    assert manifest_result.returncode == 1

    archive_path = tmp_path / "tau-release.tar.gz"
    payload = b"unsafe release member\n"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        member = tarfile.TarInfo("extensions/tau-mirror/loader.ts")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    archive_result = _run_tau_check(clone, "--archive", str(archive_path))
    assert archive_result.returncode == 1
    assert "removed Tau path" in archive_result.stdout


def test_security_gate_rejects_tau_loader_before_execution(tmp_path: Path) -> None:
    clone = _prepare_tau_mutation_clone(tmp_path, "tau-security-mutation")
    sentinel = clone / "tau-executed"
    fixture = clone / "core/runtime-loaders/unsafe.ts"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        "spawn('npx', ['tau-mirror']);\n" f"require('fs').writeFileSync('{sentinel}', 'bad');\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(fixture.relative_to(clone))], cwd=clone, check=True)

    result = subprocess.run(
        ["bash", "scripts/security-gate.sh"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "Tau Mirror npx loader" in result.stdout
    assert not sentinel.exists()
