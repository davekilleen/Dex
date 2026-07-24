"""Regression tests for artifacts produced from the public repository."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

DOCS_BRIDGE_PATHS = tuple(
    f"docs/Dex_System/{filename}"
    for filename in (
        "Background_Processing_Guide.md",
        "Calendar_Setup.md",
        "Dex_Jobs_to_Be_Done.md",
        "Dex_System_Guide.md",
        "Dex_Technical_Guide.md",
        "Distribution_Checklist.md",
        "Distribution_Strategy.md",
        "Folder_Structure.md",
        "Memory_Ownership.md",
        "Named_Sessions_Guide.md",
        "Obsidian_Guide.md",
        "README.md",
        "Updating_Dex.md",
    )
)

RELEASE_BUILD_INPUTS = (
    ".distignore",
    ".gitattributes",
    ".gitignore",
    ".github/workflows/ci.yml",
    ".scripts/lib/tests/entity-pages.test.cjs",
    "06-Resources/Dex_System/Dex_Technical_Guide.md",
    *DOCS_BRIDGE_PATHS,
    "package.json",
    "requirements.txt",
    "requirements-dev.txt",
    ".claude/skills/dex-level-up/SKILL.md",
    ".claude/skills/dex-update/SKILL.md",
    ".claude/skills/dex-rollback/SKILL.md",
    "System/.local-only-preservation-transition.json",
    "System/Beta_Communications/2026-02-04_hardcoded_paths_fix.md",
    "core/migrations/preserve_local_only_paths.py",
    "core/migrations/tracked-ignored-policy.yaml",
    "core/lifecycle/catalog/README.md",
    "core/lifecycle/catalog/bridge-release.json",
    "core/lifecycle/catalog/official-capabilities.json",
    "core/lifecycle/bridge.py",
    "core/lifecycle/catalog.py",
    "core/lifecycle/customizations.py",
    "core/lifecycle/contracts/api.schema.json",
    "core/lifecycle/service.py",
    "core/lifecycle/schemas/release-catalog-v1.schema.json",
    "core/portable_contract.py",
    "core/provision.cjs",
    "core/transaction/engine.py",
    "core/transaction/journal.py",
    "core/utils/tracked_ignored.py",
    "core/utils/manifest.py",
    "core/utils/update_verifier.py",
    "core/utils/smoke.py",
    "packages/dex-contracts/dist/release-catalog-v1.schema.json",
    "packages/dex-contracts/dist/portable-vault.contract.json",
    "scripts/build-release.sh",
    "scripts/build-vault-bundle.sh",
    "scripts/check-catalog-coverage.py",
    "scripts/check-tau-removal.py",
    "scripts/generate-manifest.sh",
    "scripts/generate-release-catalog.py",
    "scripts/resolve-distignore-files.sh",
    "scripts/security-gate.sh",
    "scripts/verify-distribution.sh",
)

RELEASE_BUILD_ABSENT = (
    "System/Session_Learnings/2026-01-29.md",
    "System/Session_Learnings/2026-01-30.md",
    "System/integrations/slack.yaml",
)


def _load_tau_checker() -> ModuleType:
    path = REPO_ROOT / "scripts/check-tau-removal.py"
    spec = importlib.util.spec_from_file_location("check_tau_removal", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

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


def test_release_builders_gate_frozen_lifecycle_contract_artifacts() -> None:
    from core.utils.manifest import REQUIRED_LIFECYCLE_RELEASE_PATHS

    assert REQUIRED_LIFECYCLE_RELEASE_PATHS == (
        "core/lifecycle/bridge.py",
        "core/lifecycle/catalog/bridge-release.json",
        "core/lifecycle/contracts/api.schema.json",
        "core/lifecycle/service.py",
        "core/portable_contract.py",
        "packages/dex-contracts/dist/portable-vault.contract.json",
    )
    for script_name in ("build-release.sh", "build-vault-bundle.sh"):
        script = (REPO_ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        assert "--require-lifecycle-contracts" in script


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
    for relative_path in RELEASE_BUILD_ABSENT:
        (clone / relative_path).unlink(missing_ok=True)
    tracked_absent = [
        relative_path
        for relative_path in RELEASE_BUILD_ABSENT
        if subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative_path],
            cwd=clone,
            capture_output=True,
        ).returncode
        == 0
    ]
    if tracked_absent:
        subprocess.run(["git", "add", "-u", "--", *tracked_absent], cwd=clone, check=True)


def _commit_release_inputs_if_changed(clone: Path) -> None:
    _sync_release_inputs(clone)
    subprocess.run(["git", "add", "-f", "--", *RELEASE_BUILD_INPUTS], cwd=clone, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=clone).returncode != 0:
        subprocess.run(
            ["git", "commit", "--quiet", "-m", "test: sync release build inputs"],
            cwd=clone,
            check=True,
        )


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
        ["git", "add", "-f", "--", *RELEASE_BUILD_INPUTS, str(spaced_fixture.relative_to(clone))],
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
        timeout=120,
    )


def _write_tar(
    archive_path: Path, members: list[tuple[tarfile.TarInfo, bytes]]
) -> None:
    with tarfile.open(archive_path, mode="w") as archive:
        for member, payload in members:
            member.size = len(payload) if member.isfile() else 0
            archive.addfile(member, io.BytesIO(payload) if member.isfile() else None)


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


def _git_tree_files(repo: Path, treeish: str) -> list[tuple[str, bytes]]:
    checker = _load_tau_checker()
    files, violations = checker._git_tree(repo, treeish)
    assert violations == []
    return files


def _tar_files(archive_path: Path) -> list[tuple[str, bytes]]:
    checker = _load_tau_checker()
    files, violations = checker._archive_tree(archive_path)
    assert violations == []
    return files


def _assert_tau_absent_from_files(files: list[tuple[str, bytes]]) -> None:
    checker = _load_tau_checker()
    assert checker._check_files(files, source=False) == []
    assert all(not checker._contains_tau_identity(path) for path, _ in files)
    for _, content in files:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        assert not checker._contains_tau_identity(text)


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
    tree_files = _git_tree_files(clone, treeish)
    _assert_tau_absent_from_files(tree_files)
    assert ".gitattributes" not in {path for path, _ in tree_files}
    tree_check = _run_tau_check(
        clone, "--repo-root", str(clone), "--git-tree", treeish
    )
    assert tree_check.returncode == 0, tree_check.stdout + tree_check.stderr

    archive_members = _build_git_archive(clone, treeish, archive_path)
    _assert_tau_absent(archive_members)
    _assert_tau_absent_from_files(_tar_files(archive_path))
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


def test_release_branch_strips_dev_files_and_untracks_v1_local_only_files(tmp_path: Path) -> None:
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
    assert ".claude/skills/dex-rollback/SKILL.md" in members
    assert ".claude/skills/anthropic-docx/scripts/document.py" in members
    assert "System/.installed-files.manifest" in members
    assert "System/.release-catalog.json" in members
    assert "System/.release-evidence-profile.json" in members
    assert "core/lifecycle/catalog/bridge-release.json" in members
    assert "core/lifecycle/contracts/api.schema.json" in members
    assert "core/lifecycle/service.py" in members
    assert "core/lifecycle/bridge.py" in members
    assert "System/.dex/lifecycle/activation.json" not in members
    assert "System/.local-only-preservation-transition.json" in members
    assert "core/migrations/preserve_local_only_paths.py" in members
    assert "core/migrations/tracked-ignored-policy.yaml" in members
    assert "core/utils/tracked_ignored.py" in members
    assert "System/Beta_Communications/2026-02-04_hardcoded_paths_fix.md" in members
    assert "System/Session_Learnings/2026-01-29.md" not in members
    assert "System/Session_Learnings/2026-01-30.md" not in members
    assert "System/integrations/slack.yaml" not in members
    for bridge_path in DOCS_BRIDGE_PATHS:
        assert bridge_path in members
    _assert_tau_absent_from_release_artifacts(
        clone, "release", tmp_path / "stable-release.tar"
    )

    manifest = _release_manifest(clone, "release")
    assert manifest == sorted(manifest)
    assert set(manifest) == members
    assert "core/tests/test_distribution_artifacts.py" not in manifest
    assert "core/lifecycle/catalog/bridge-release.json" in manifest
    assert "core/lifecycle/contracts/api.schema.json" in manifest
    assert "System/.dex/lifecycle/activation.json" not in manifest
    catalog = _git_json(clone, "release:System/.release-catalog.json")
    package = _git_json(clone, "release:package.json")
    bridge_release = _git_json(
        clone, "release:core/lifecycle/catalog/bridge-release.json"
    )
    source_commit = subprocess.run(
        ["git", "rev-parse", "release^"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest_bytes = subprocess.run(
        ["git", "show", "release:System/.installed-files.manifest"],
        cwd=clone,
        check=True,
        capture_output=True,
    ).stdout
    assert catalog["catalog_version"] == 1
    official_registry = json.loads(
        (REPO_ROOT / "core/lifecycle/catalog/official-capabilities.json").read_text(
            encoding="utf-8"
        )
    )
    expected_item_ids = sorted(item["id"] for item in official_registry["items"])
    assert sorted(item["id"] for item in catalog["items"]) == expected_item_ids
    assert catalog["release"]["version"] == package["version"]
    assert bridge_release == json.loads(
        (REPO_ROOT / "core/lifecycle/catalog/bridge-release.json").read_text(
            encoding="utf-8"
        )
    )
    assert catalog["release"]["source_commit"] == source_commit
    assert catalog["release"]["manifest"]["sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    profile = json.loads(
        subprocess.run(
            ["git", "show", "release:System/.release-evidence-profile.json"],
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    # The release tree carries the source's own version — derive it rather than
    # hardcoding, so cutting a release doesn't break this test.
    source_version = _git_json(clone, "main:package.json")["version"]
    assert profile == {
        "schema_version": 1,
        "profile": "legacy-v1",
        "release_version": source_version,
    }

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
    _assert_tau_absent_from_release_artifacts(
        clone, "release-beta", tmp_path / "beta-release.tar"
    )
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
    _sync_release_inputs(clone)
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
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
    _sync_release_inputs(clone)
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
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
    _sync_release_inputs(clone)
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
    _sync_release_inputs(clone)
    for relative_path in (
        "scripts/release.sh",
        "scripts/generate-manifest.sh",
        "core/migrations/preserve_local_only_paths.py",
        "core/utils/tracked_ignored.py",
        "core/paths.py",
        "core/utils/manifest.py",
        "core/utils/update_verifier.py",
    ):
        shutil.copy2(REPO_ROOT / relative_path, clone / relative_path)
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "--allow-empty", "-m", "test: current release scripts"],
        cwd=clone,
        check=True,
    )

    # Derive the expected bump from the clone's current version rather than
    # hardcoding it — a hardcoded number breaks this test on every release cut.
    before = _git_json(clone, "HEAD:package.json")["version"]
    major, minor, patch = (int(part) for part in before.split("."))
    bumped = f"{major}.{minor}.{patch + 1}"

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
    transition = _git_json(clone, "HEAD:System/.local-only-preservation-transition.json")
    assert package["version"] == bumped
    assert profile == {"profile": "legacy-v1", "release_version": bumped, "schema_version": 1}
    assert transition == {"schema_version": 1, "phase": "untrack-v1", "release_version": bumped}
    assert "System/.release-evidence-profile.json" in _release_manifest(clone, "HEAD")
    assert subprocess.run(
        ["git", "rev-parse", f"v{bumped}^{{}}"], cwd=clone, check=True, capture_output=True, text=True
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


def test_release_build_rejects_unsafe_selected_source_before_creating_ref(
    tmp_path: Path,
) -> None:
    clone = _clone_repo(tmp_path, "unsafe-selected-source")
    subprocess.run(["git", "checkout", "-B", "main", "HEAD"], cwd=clone, check=True)
    _commit_release_inputs_if_changed(clone)
    subprocess.run(["git", "checkout", "-b", "unsafe-source"], cwd=clone, check=True)
    unsafe = clone / ".github/unsafe-selected-source.md"
    unsafe.write_text("load tau-mirror here\n", encoding="utf-8")
    subprocess.run(["git", "add", str(unsafe.relative_to(clone))], cwd=clone, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test: unsafe selected source"],
        cwd=clone,
        check=True,
    )
    subprocess.run(["git", "checkout", "main"], cwd=clone, check=True)

    result = subprocess.run(
        [
            "bash",
            "scripts/build-release.sh",
            "--source",
            "unsafe-source",
            "--target",
            "release-unsafe",
        ],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 1
    assert "Tau Mirror reference" in result.stdout
    assert subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/release-unsafe"],
        cwd=clone,
    ).returncode == 1
    assert subprocess.run(
        ["git", "tag", "--list", "dist/release-unsafe/*"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""


def test_release_build_uses_safe_selected_source_despite_unsafe_current_checkout(
    tmp_path: Path,
) -> None:
    clone = _clone_repo(tmp_path, "safe-selected-source")
    subprocess.run(["git", "checkout", "-B", "main", "HEAD"], cwd=clone, check=True)
    _commit_release_inputs_if_changed(clone)
    subprocess.run(["git", "branch", "safe-source", "HEAD"], cwd=clone, check=True)
    subprocess.run(["git", "checkout", "-b", "unsafe-current"], cwd=clone, check=True)
    unsafe = clone / "docs/unsafe-current.md"
    unsafe.write_text("load tau-mirror here\n", encoding="utf-8")
    subprocess.run(["git", "add", str(unsafe.relative_to(clone))], cwd=clone, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test: unrelated unsafe checkout"],
        cwd=clone,
        check=True,
    )

    result = subprocess.run(
        [
            "bash",
            "scripts/build-release.sh",
            "--source",
            "safe-source",
            "--target",
            "release-safe",
        ],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/release-safe"],
        cwd=clone,
    ).returncode == 0
    release_members = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "release-safe"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert "docs/unsafe-current.md" not in release_members


def test_release_build_uses_selected_source_distignore_contract(tmp_path: Path) -> None:
    clone = _clone_repo(tmp_path, "selected-source-distignore")
    subprocess.run(["git", "checkout", "-B", "main", "HEAD"], cwd=clone, check=True)
    _commit_release_inputs_if_changed(clone)
    subprocess.run(["git", "checkout", "-b", "unsafe-distignore"], cwd=clone, check=True)
    distignore = clone / ".distignore"
    distignore.write_text(
        distignore.read_text(encoding="utf-8").replace("extensions/tau-mirror/\n", ""),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", ".distignore"], cwd=clone, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test: unsafe selected distignore"],
        cwd=clone,
        check=True,
    )
    subprocess.run(["git", "checkout", "main"], cwd=clone, check=True)

    result = subprocess.run(
        [
            "bash",
            "scripts/build-release.sh",
            "--source",
            "unsafe-distignore",
            "--target",
            "release-distignore",
        ],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 1
    assert "missing exact quarantine entry" in result.stdout
    assert subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", "refs/heads/release-distignore"],
        cwd=clone,
    ).returncode == 1


def test_manifest_accepts_safe_head_source_tree(tmp_path: Path) -> None:
    clone = _clone_repo(tmp_path, "safe-manifest-treeish")
    subprocess.run(["git", "checkout", "-B", "main", "HEAD"], cwd=clone, check=True)
    _commit_release_inputs_if_changed(clone)

    result = subprocess.run(
        ["bash", "scripts/generate-manifest.sh", "HEAD"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    manifest = (clone / "System/.installed-files.manifest").read_text(
        encoding="utf-8"
    ).splitlines()
    expected = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
        cwd=clone,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert manifest == sorted(expected)


@pytest.mark.parametrize("mutation", ("path", "dependency"))
def test_manifest_rejects_unsafe_requested_tree_without_output_or_ref_mutation(
    tmp_path: Path, mutation: str
) -> None:
    clone = _clone_repo(tmp_path, f"unsafe-manifest-treeish-{mutation}")
    subprocess.run(["git", "checkout", "-B", "main", "HEAD"], cwd=clone, check=True)
    _commit_release_inputs_if_changed(clone)
    subprocess.run(["git", "checkout", "-b", "unsafe-manifest"], cwd=clone, check=True)
    if mutation == "path":
        unsafe = clone / "extensions/tau-mirror-loader.bin"
        unsafe.parent.mkdir(parents=True, exist_ok=True)
        unsafe.write_bytes(b"safe payload\n")
        subprocess.run(["git", "add", str(unsafe.relative_to(clone))], cwd=clone, check=True)
        expected_violation = "removed Tau path"
    else:
        package_path = clone / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package.setdefault("dependencies", {})["qrcode-terminal"] = "1.0.0"
        package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
        subprocess.run(["git", "add", "package.json"], cwd=clone, check=True)
        expected_violation = "forbidden dependency qrcode-terminal"
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test: unsafe manifest tree"],
        cwd=clone,
        check=True,
    )
    subprocess.run(["git", "checkout", "main"], cwd=clone, check=True)
    manifest = clone / "System/.installed-files.manifest"
    manifest.write_bytes(b"preserve-existing-output\n")
    before_manifest = manifest.read_bytes()
    before_refs = subprocess.run(
        ["git", "show-ref"], cwd=clone, check=True, capture_output=True
    ).stdout

    result = subprocess.run(
        ["bash", "scripts/generate-manifest.sh", "unsafe-manifest"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 1
    assert expected_violation in result.stdout
    assert manifest.read_bytes() == before_manifest
    assert subprocess.run(
        ["git", "show-ref"], cwd=clone, check=True, capture_output=True
    ).stdout == before_refs


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


def test_beta_release_ci_builds_branch_and_tag() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    beta_job = workflow["jobs"]["build-release-beta"]
    beta_commands = "\n".join(step.get("run", "") for step in beta_job["steps"])

    assert beta_job["if"] == "github.ref == 'refs/heads/beta' && github.event_name == 'push'"
    assert beta_job["permissions"] == {"contents": "write"}
    assert "bash scripts/build-release.sh --source beta --target release-beta" in beta_commands
    assert "git push origin release-beta --force" in beta_commands
    assert "git push origin \"${{ steps.release_build.outputs.release_tag }}\"" in beta_commands


def test_beta_release_ci_publishes_vault_bundle_only_as_prerelease() -> None:
    """The beta lane may publish a GitHub release, but only ever as a --prerelease,
    and must never be able to clobber a stable (non-prerelease) release asset."""
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    beta_job = workflow["jobs"]["build-release-beta"]
    beta_commands = "\n".join(step.get("run", "") for step in beta_job["steps"])

    # It builds the same self-contained bundle the stable lane ships.
    assert "bash scripts/build-vault-bundle.sh" in beta_commands
    assert "dist/dex-vault-bundle-v$VERSION.tar.gz" in beta_commands

    # Every release creation from the beta lane is a prerelease (keeps it off "latest").
    assert "gh release create" in beta_commands
    assert "--prerelease" in beta_commands

    # Guard 1: refuse a non-prerelease (bare X.Y.Z) version so the beta lane can never
    # target a stable release tag.
    assert "X.Y.Z-<pre>" in beta_commands or "is not a prerelease" in beta_commands
    # Guard 2: before clobbering an existing tag, assert it is already a prerelease.
    assert "isPrerelease" in beta_commands
    assert "will not clobber it" in beta_commands

    # And the stable lane's own publish must remain a normal (non-prerelease) release.
    stable_job = workflow["jobs"]["build-release"]
    stable_commands = "\n".join(step.get("run", "") for step in stable_job["steps"])
    assert "gh release create" in stable_commands
    assert "--prerelease" not in stable_commands


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
            "--ignore-unmatch",
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


def test_connection_manager_tests_are_distignored() -> None:
    distignore = (REPO_ROOT / ".distignore").read_text(encoding="utf-8").splitlines()

    assert "core/integrations/connection-manager/*.test.cjs" in distignore
    assert "core/integrations/connection-manager/hardening.child.cjs" in distignore


@pytest.mark.parametrize(
    "path",
    (
        "extensions/tau-mirror/loader.ts",
        "extensions/tau-mirror-loader.ts",
        "extensions/loader-tau_mirror.bin",
    ),
    ids=("exact-directory", "loader-suffix", "loader-prefix"),
)
def test_tau_path_rule_has_an_isolated_inverse(path: str) -> None:
    checker = _load_tau_checker()
    fixture = [(path, b"")]

    assert checker._check_files(
        fixture, source=False, text_rules=(), forbidden_dependencies=set()
    )
    assert checker._check_files(
        fixture,
        source=False,
        identity_checker=None,
        text_rules=(),
        forbidden_dependencies=set(),
    ) == []


@pytest.mark.parametrize(
    "reference",
    ("tau-mirror", "tau_mirror", "tauMirror"),
    ids=("kebab", "snake", "camel"),
)
def test_tau_reference_formats_use_canonical_identity_with_inverse(reference: str) -> None:
    checker = _load_tau_checker()
    fixture = [("runtime/safe-name.txt", reference.encode())]

    assert checker._check_files(
        fixture, source=False, text_rules=(), forbidden_dependencies=set()
    ) == ["runtime/safe-name.txt: Tau Mirror reference"]
    assert checker._check_files(
        fixture,
        source=False,
        identity_checker=None,
        text_rules=(),
        forbidden_dependencies=set(),
    ) == []


@pytest.mark.parametrize("value", ("taumirror", "tau-mirroring", "taut-mirror"))
def test_tau_identity_avoids_substring_false_positives(value: str) -> None:
    checker = _load_tau_checker()

    assert not checker._contains_tau_identity(value)


@pytest.mark.parametrize(
    ("rule_name", "content"),
    (
        ("Tau Mirror npx loader", "spawn('npx', ['tau-mirror']);\n"),
        ("removed QR dependency", "import 'qrcode-terminal';\n"),
        (
            "removed Pi coding-agent dependency",
            "import '@mariozechner/pi-coding-agent';\n",
        ),
        ("wildcard network bind", "server.listen(3001, '0.0.0.0');\n"),
        ("wildcard host argument", "serve --host=0.0.0.0\n"),
        ("LAN address discovery", "os.networkInterfaces();\n"),
        ("unsupported no-authentication claim", "Authentication disabled.\n"),
    ),
    ids=(
        "npx-loader",
        "qr-reference",
        "pi-reference",
        "wildcard-bind",
        "wildcard-host",
        "lan-discovery",
        "auth-claim",
    ),
)
def test_each_text_rule_has_an_isolated_inverse(rule_name: str, content: str) -> None:
    checker = _load_tau_checker()
    rule = next(rule for rule in checker.TEXT_RULES if rule[0] == rule_name)
    fixture = [("runtime/safe-name.txt", content.encode())]

    assert checker._check_files(
        fixture,
        source=False,
        identity_checker=None,
        text_rules=(rule,),
        forbidden_dependencies=set(),
    )
    assert checker._check_files(
        fixture,
        source=False,
        identity_checker=None,
        text_rules=(),
        forbidden_dependencies=set(),
    ) == []


@pytest.mark.parametrize(
    ("manifest_path", "document"),
    (
        ("package.json", {"dependencies": {"tau-mirror": "1.0.0"}}),
        (
            "package-lock.json",
            {"packages": {"node_modules/tau-mirror": {"version": "1.0.0"}}},
        ),
    ),
    ids=("package-json", "package-lock"),
)
def test_package_and_lock_dependency_guards_have_separate_inverses(
    manifest_path: str, document: dict[str, object]
) -> None:
    checker = _load_tau_checker()
    fixture = [(manifest_path, json.dumps(document).encode())]

    assert checker._check_files(
        fixture,
        source=False,
        identity_checker=None,
        text_rules=(),
        forbidden_dependencies={"tau-mirror"},
    )
    assert checker._check_files(
        fixture,
        source=False,
        identity_checker=None,
        text_rules=(),
        forbidden_dependencies=set(),
    ) == []


def test_git_archive_contains_no_tau_release_member() -> None:
    members = _archive_members()
    _assert_tau_absent(members)


def test_vault_distignore_directory_rules_resolve_before_staging(tmp_path: Path) -> None:
    all_files = tmp_path / "all-files"
    excluded_files = tmp_path / "excluded-files"
    included_files = tmp_path / "included-files"
    distignore = tmp_path / ".distignore"
    all_files.write_text(
        "core/tests/test_distribution_artifacts.py\n"
        "core/testsuite/retained.py\n"
        "safe.txt\n"
        "scripts-extra/retained.sh\n"
        "scripts/check-tau-removal.py\n",
        encoding="utf-8",
    )
    distignore.write_text("core/tests/\nscripts/\n", encoding="utf-8")
    shim_dir = tmp_path / "git-must-not-expand-directories"
    shim_dir.mkdir()
    git_shim = shim_dir / "git"
    git_shim.write_text("#!/bin/sh\nexit 97\n", encoding="utf-8")
    git_shim.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{shim_dir}{os.pathsep}{environment['PATH']}"

    result = subprocess.run(
        [
            "sh",
            "scripts/resolve-distignore-files.sh",
            str(distignore),
            str(all_files),
            str(excluded_files),
            str(included_files),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert excluded_files.read_text(encoding="utf-8").splitlines() == [
        "core/tests/test_distribution_artifacts.py",
        "scripts/check-tau-removal.py",
    ]
    assert included_files.read_text(encoding="utf-8").splitlines() == [
        "core/testsuite/retained.py",
        "safe.txt",
        "scripts-extra/retained.sh",
    ]


def test_vault_bundle_tree_manifest_and_archive_contain_no_tau(tmp_path: Path) -> None:
    clone = _clone_repo(tmp_path, "vault-bundle-build")
    _sync_release_inputs(clone)
    subprocess.run(["git", "add", "-f", "--", *RELEASE_BUILD_INPUTS], cwd=clone, check=True)
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
        assert "core/lifecycle/catalog/bridge-release.json" in {
            member.removeprefix("./") for member in members
        }
        assert "core/lifecycle/contracts/api.schema.json" in {
            member.removeprefix("./") for member in members
        }
        assert "System/.dex/lifecycle/activation.json" not in {
            member.removeprefix("./") for member in members
        }
        assert "core/lifecycle/catalog/bridge-release.json" in manifest
        assert "core/lifecycle/contracts/api.schema.json" in manifest
        assert "System/.dex/lifecycle/activation.json" not in manifest
        bridge_member = archive.extractfile(
            "./core/lifecycle/catalog/bridge-release.json"
        )
        assert bridge_member is not None
        bridge_release = json.loads(bridge_member.read())
    _assert_tau_absent(manifest)
    archive_files = _tar_files(archive_path)
    _assert_tau_absent_from_files(archive_files)
    archive_paths = {path.removeprefix("./") for path, _ in archive_files}
    assert ".gitattributes" not in archive_paths
    assert bridge_release == json.loads(
        (REPO_ROOT / "core/lifecycle/catalog/bridge-release.json").read_text(
            encoding="utf-8"
        )
    )
    assert not any(path.startswith("core/tests/") for path in archive_paths)
    assert not any(path.startswith("scripts/") for path in archive_paths)
    tau_check = _run_tau_check(clone, "--archive", str(archive_path))
    assert tau_check.returncode == 0, tau_check.stdout + tau_check.stderr


def test_tree_mode_rejects_tau_member_independently(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    fixture = tree / "extensions/tau-mirror/loader.ts"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("safe content\n", encoding="utf-8")

    result = _run_tau_check(REPO_ROOT, "--tree", str(tree))

    assert result.returncode == 1
    assert "removed Tau path" in result.stdout


def test_tree_mode_allows_trusted_symlink_above_controlled_root(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    tree = real_parent / "tree"
    tree.mkdir(parents=True)
    (tree / "safe.txt").write_text("safe\n", encoding="utf-8")
    alias_parent = tmp_path / "alias-parent"
    alias_parent.symlink_to(real_parent, target_is_directory=True)

    result = _run_tau_check(REPO_ROOT, "--tree", str(alias_parent / "tree"))

    assert result.returncode == 0, result.stdout + result.stderr


def test_tree_mode_rejects_internal_symlink_and_rule_inverse(tmp_path: Path) -> None:
    checker = _load_tau_checker()
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "target.txt").write_text("safe\n", encoding="utf-8")
    (tree / "internal-link").symlink_to("target.txt")

    _, violations = checker._filesystem_tree(tree)
    _, without_symlink_rule = checker._filesystem_files(tree, reject_symlinks=False)

    assert any("distribution symlink is forbidden" in item for item in violations)
    assert without_symlink_rule == []


def test_tree_mode_rejects_escaping_symlink_with_canonical_containment(
    tmp_path: Path,
) -> None:
    checker = _load_tau_checker()
    tree = tmp_path / "tree"
    tree.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("controlled fixture\n", encoding="utf-8")
    (tree / "escape").symlink_to(outside)

    _, violations = checker._filesystem_files(tree, reject_symlinks=False)
    _, without_containment = checker._filesystem_files(
        tree, reject_symlinks=False, enforce_canonical=False
    )

    assert any("escaping or unresolved" in item for item in violations)
    assert without_containment == []


def test_tree_mode_rejects_special_file(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    os.mkfifo(tree / "pipe")

    result = _run_tau_check(REPO_ROOT, "--tree", str(tree))

    assert result.returncode == 1
    assert "unsafe tree special-file type" in result.stdout


@pytest.mark.parametrize(
    ("case_name", "members", "expected"),
    (
        (
            "absolute-member",
            ((tarfile.TarInfo("/absolute.txt"), b"safe\n"),),
            "absolute path",
        ),
        (
            "traversal-member",
            ((tarfile.TarInfo("../../outside.txt"), b"safe\n"),),
            "traversal component",
        ),
        (
            "duplicate-normalization",
            (
                (tarfile.TarInfo("safe/file.txt"), b"one\n"),
                (tarfile.TarInfo("./safe/file.txt"), b"two\n"),
            ),
            "duplicate normalized archive path",
        ),
        (
            "absolute-link-name",
            ((tarfile.TarInfo("/link"), b""),),
            "absolute path",
        ),
        (
            "special-file",
            ((tarfile.TarInfo("pipe"), b""),),
            "unsafe archive special-file type",
        ),
    ),
    ids=(
        "absolute-member",
        "traversal-member",
        "duplicate-normalization",
        "absolute-link-name",
        "special-file",
    ),
)
def test_archive_mode_rejects_hostile_members(
    tmp_path: Path,
    case_name: str,
    members: tuple[tuple[tarfile.TarInfo, bytes], ...],
    expected: str,
) -> None:
    archive_path = tmp_path / f"{case_name}.tar"
    if case_name == "absolute-link-name":
        members[0][0].type = tarfile.SYMTYPE
        members[0][0].linkname = "safe-target"
    elif case_name == "special-file":
        members[0][0].type = tarfile.FIFOTYPE
    _write_tar(archive_path, list(members))

    result = _run_tau_check(REPO_ROOT, "--archive", str(archive_path))

    assert result.returncode == 1
    assert expected in result.stdout


@pytest.mark.parametrize(
    ("linkname", "expected"),
    (("/etc/passwd", "absolute path"), ("../../outside", "traversal component")),
    ids=("absolute-target", "traversal-target"),
)
def test_archive_mode_rejects_unsafe_link_targets(
    tmp_path: Path, linkname: str, expected: str
) -> None:
    link = tarfile.TarInfo("safe-link")
    link.type = tarfile.SYMTYPE
    link.linkname = linkname
    archive_path = tmp_path / "unsafe-link.tar"
    _write_tar(archive_path, [(link, b"")])

    result = _run_tau_check(REPO_ROOT, "--archive", str(archive_path))

    assert result.returncode == 1
    assert "distribution archive link is forbidden" in result.stdout
    assert expected in result.stdout


def test_archive_mode_rejects_internal_symlink_and_rule_inverse(tmp_path: Path) -> None:
    checker = _load_tau_checker()
    target = tarfile.TarInfo("target.txt")
    link = tarfile.TarInfo("internal-link")
    link.type = tarfile.SYMTYPE
    link.linkname = "target.txt"
    archive_path = tmp_path / "internal-link.tar"
    _write_tar(archive_path, [(target, b"safe\n"), (link, b"")])

    _, violations = checker._archive_tree(archive_path)
    _, without_link_rule = checker._archive_tree(archive_path, reject_links=False)

    assert any("distribution archive link is forbidden" in item for item in violations)
    assert without_link_rule == []


def test_archive_path_containment_guard_has_an_inverse(tmp_path: Path) -> None:
    checker = _load_tau_checker()
    member = tarfile.TarInfo("../../outside.txt")
    archive_path = tmp_path / "path-containment-inverse.tar"
    _write_tar(archive_path, [(member, b"controlled fixture\n")])

    _, violations = checker._archive_tree(archive_path)

    def permissive_normalizer(raw_path: str, *, allow_root: bool = False) -> str:
        del allow_root
        return raw_path.replace("../", "").lstrip("/")

    _, without_containment = checker._archive_tree(
        archive_path, normalize_path=permissive_normalizer
    )

    assert any("unsafe archive path" in item for item in violations)
    assert without_containment == []


def test_archive_duplicate_and_special_guards_have_inverses(tmp_path: Path) -> None:
    checker = _load_tau_checker()
    first = tarfile.TarInfo("safe/file.txt")
    duplicate = tarfile.TarInfo("./safe/file.txt")
    special = tarfile.TarInfo("pipe")
    special.type = tarfile.FIFOTYPE
    archive_path = tmp_path / "guard-inverses.tar"
    _write_tar(
        archive_path,
        [(first, b"one\n"), (duplicate, b"two\n"), (special, b"")],
    )

    _, violations = checker._archive_tree(archive_path)
    _, without_guards = checker._archive_tree(
        archive_path, reject_duplicates=False, reject_special=False
    )

    assert any("duplicate normalized archive path" in item for item in violations)
    assert any("unsafe archive special-file type" in item for item in violations)
    assert without_guards == []


def _prepare_tau_mutation_clone(tmp_path: Path, name: str) -> Path:
    clone = _clone_repo(tmp_path, name)
    subprocess.run(["git", "checkout", "-B", "main", "HEAD"], cwd=clone, check=True)
    _sync_release_inputs(clone)
    subprocess.run(["git", "add", "-f", "--", *RELEASE_BUILD_INPUTS], cwd=clone, check=True)
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
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "test: reintroduce unsafe Tau source"],
        cwd=clone,
        check=True,
    )

    gate = _run_tau_check(clone, "--source-root", str(clone))
    build = subprocess.run(
        ["bash", "scripts/build-release.sh"],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=120,
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
    ("manifest_path", "dependency"),
    tuple(
        (manifest_path, dependency)
        for manifest_path in ("package.json", "package-lock.json")
        for dependency in (
            "tau-mirror",
            "qrcode-terminal",
            "@mariozechner/pi-coding-agent",
        )
    ),
    ids=(
        "package-tau-mirror",
        "package-qrcode-terminal",
        "package-pi-coding-agent",
        "lock-tau-mirror",
        "lock-qrcode-terminal",
        "lock-pi-coding-agent",
    ),
)
def test_tau_gate_rejects_package_and_lock_dependencies(
    tmp_path: Path, manifest_path: str, dependency: str
) -> None:
    clone = _prepare_tau_mutation_clone(
        tmp_path,
        f"tau-dependency-mutation-{manifest_path}-{dependency.replace('/', '-')}",
    )
    manifest = clone / manifest_path
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if manifest_path == "package.json":
        document.setdefault("dependencies", {})[dependency] = "1.0.0"
    else:
        document.setdefault("packages", {})[f"node_modules/{dependency}"] = {
            "version": "1.0.0"
        }
    manifest.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", manifest_path], cwd=clone, check=True)

    result = _run_tau_check(clone, "--source-root", str(clone))
    assert result.returncode == 1
    assert "forbidden dependency" in result.stdout


def test_tau_gate_rejects_legacy_manifest_member(tmp_path: Path) -> None:
    clone = _prepare_tau_mutation_clone(tmp_path, "tau-manifest-mutation")
    manifest = clone / "System/.installed-files.manifest"
    manifest.write_text("extensions/tau-mirror/loader.ts\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", str(manifest.relative_to(clone))], cwd=clone, check=True)
    manifest_result = _run_tau_check(clone, "--source-root", str(clone))
    assert manifest_result.returncode == 1


@pytest.mark.parametrize(
    "member_name",
    (
        "extensions/tau-mirror/loader.ts",
        "extensions/tau-mirror-loader.bin",
        "extensions/loader-tau_mirror.bin",
    ),
    ids=("exact-directory", "loader-suffix", "loader-prefix"),
)
def test_tau_gate_rejects_archive_member(tmp_path: Path, member_name: str) -> None:
    clone = _prepare_tau_mutation_clone(
        tmp_path, f"tau-archive-mutation-{Path(member_name).name}"
    )
    archive_path = tmp_path / "tau-release.tar.gz"
    payload = b"unsafe release member\n"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        member = tarfile.TarInfo(member_name)
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    archive_result = _run_tau_check(clone, "--archive", str(archive_path))
    assert archive_result.returncode == 1
    assert "removed Tau path" in archive_result.stdout


def test_vault_build_rejects_tau_before_build_package_or_archive_commands(
    tmp_path: Path,
) -> None:
    clone = _prepare_tau_mutation_clone(tmp_path, "tau-build-order-mutation")
    fixture = clone / "core/runtime-loaders/unsafe.ts"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("spawn('npx', ['tau-mirror']);\n", encoding="utf-8")
    subprocess.run(["git", "add", str(fixture.relative_to(clone))], cwd=clone, check=True)

    spy_dir = tmp_path / "command-spies"
    spy_dir.mkdir()
    sentinel = tmp_path / "build-command-ran"
    for command in ("node", "rsync", "npm", "tar"):
        spy = spy_dir / command
        spy.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 99\n", encoding="utf-8")
        spy.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{spy_dir}{os.pathsep}{environment['PATH']}"
    output_dir = tmp_path / "blocked-output"

    result = subprocess.run(
        ["bash", "scripts/build-vault-bundle.sh", str(output_dir)],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )
    assert result.returncode == 1
    assert "Tau Mirror npx loader" in result.stdout
    assert not sentinel.exists()
    assert not output_dir.exists()
