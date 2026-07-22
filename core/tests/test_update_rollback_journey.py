"""Integration coverage for update manifests and rollback preservation."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import yaml

from core.lifecycle import engine as lifecycle_engine
from core.lifecycle import service as lifecycle_service
from core.lifecycle.bridge import ACTIVATION_RELATIVE
from core.migrations import preserve_local_only_paths as preservation
from core.tests.test_adoption_transaction import _setup as setup_adoption_release
from core.tests.test_lifecycle_bridge import _write_bridge_release
from core.utils.manifest import DEFAULT_MANIFEST, generate_manifest, write_manifest
from core.utils.tracked_ignored import load_exact_policy, load_transition

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLLBACK_SKILL = REPO_ROOT / ".claude/skills/dex-rollback/SKILL.md"
UPDATE_SKILL = REPO_ROOT / ".claude/skills/dex-update/SKILL.md"
POLICY = REPO_ROOT / "core/migrations/tracked-ignored-policy.yaml"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_update_runs_credential_migration_before_status_and_safe_autosave():
    instructions = UPDATE_SKILL.read_text(encoding="utf-8")
    migration = instructions.index("python3 -m core.utils.credential_workflow migrate")
    status = instructions.index("git status --porcelain", migration)
    autosave = instructions.index("python3 -m core.utils.safe_autosave", status)
    assert migration < status < autosave


def test_update_skill_routes_split_topology_to_transaction_updater_without_merge() -> None:
    update = UPDATE_SKILL.read_text(encoding="utf-8")
    start = update.index("### Split-topology route")
    end = update.index("### Step 3: Pre-Update Safety Check")
    split = update[start:end]

    assert "core.update.apply_update" in split
    assert "dist/release/v" in split
    assert "--tag-object" in split
    assert "--commit" in split
    assert "--tree" in split
    assert "release-beta" in split
    assert "System/.dex/mutation.lock" in split
    assert "git merge" not in split
    assert "Combined topology continues to Step 3" in split


def test_legacy_updater_can_deliver_bridge_release_then_hand_off_without_invoking_engine(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "release-fixture").mkdir()
    release, _document, _catalog, _inventory, _plan, _loader = setup_adoption_release(
        tmp_path / "release-fixture", item_ids=("alpha",)
    )
    _write_bridge_release(release)
    vault = tmp_path / "old-updated-vault"
    delivered = (
        "System/.installed-files.manifest",
        "System/.release-catalog.json",
        ".claude/skills/alpha/SKILL.md",
        "core/lifecycle/catalog/bridge-release.json",
    )
    calls: list[str] = []

    def forbidden_execute(*_args, **_kwargs):
        calls.append("execute_adoption")
        raise AssertionError("the legacy delivery phase invoked the lifecycle engine")

    monkeypatch.setattr(lifecycle_engine, "execute_adoption", forbidden_execute)
    for relative in delivered:
        destination = vault / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(release / relative, destination)

    assert calls == []
    assert not (vault / ACTIVATION_RELATIVE).exists()

    response = lifecycle_service.build_inventory_and_plan(vault)

    assert response["api_version"] == lifecycle_service.api_version
    assert (vault / ACTIVATION_RELATIVE).is_file()
    assert calls == []


def test_update_and_duplicated_rollback_flows_recognize_both_baselines() -> None:
    update = UPDATE_SKILL.read_text(encoding="utf-8")
    rollback = ROLLBACK_SKILL.read_text(encoding="utf-8")

    assert "untrack-v1|untrack-v2)" in update
    assert update.count("bootstrap-v1|bootstrap-v2|bootstrap-legacy)") == 2
    assert update.count("untrack-v1|untrack-v2|untrack-legacy)") == 2
    assert rollback.count("untrack-v2:bootstrap-v1") == 2
    assert rollback.count("bootstrap-v2:*") == 2


def test_release_cut_stamps_transition_metadata_from_the_bumped_package(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "release-cut"
    _write(repo, "package.json", json.dumps({"version": "1.63.0"}) + "\n")
    _write(
        repo,
        "System/.local-only-preservation-transition.json",
        json.dumps({"schema_version": 1, "phase": "untrack-v1", "release_version": "1.62.0"})
        + "\n",
    )

    assert preservation.main(["stamp-transition", "--repo", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "phase": "untrack-v1",
        "release_version": "1.63.0",
    }
    assert json.loads(
        (repo / "System/.local-only-preservation-transition.json").read_text(encoding="utf-8")
    ) == {"schema_version": 1, "phase": "untrack-v1", "release_version": "1.63.0"}

    release_script = (REPO_ROOT / "scripts/release.sh").read_text(encoding="utf-8")
    stamp = release_script.index("core.migrations.preserve_local_only_paths stamp-transition")
    manifest = release_script.index("bash scripts/generate-manifest.sh")
    assert stamp < manifest
    assert "System/.local-only-preservation-transition.json" in release_script.split("git add", 1)[1]


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Dex Tests")
    _git(repo, "config", "user.email", "tests@example.com")


def _write(repo: Path, relative: str, content: str) -> None:
    destination = repo / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")


def _commit_manifest(repo: Path, message: str) -> None:
    manifest = repo / DEFAULT_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.touch()
    _git(repo, "add", "--", str(DEFAULT_MANIFEST))
    staged_tree = _git(repo, "write-tree")
    write_manifest(repo, staged_tree)
    _git(repo, "add", "--", str(DEFAULT_MANIFEST))
    _git(repo, "commit", "--quiet", "-m", message)


PINNED_RUNTIME_PATHS = (
    ".gitignore",
    ".claude/skills/dex-update/SKILL.md",
    "package.json",
    "System/.local-only-preservation-transition.json",
    "core/migrations/preserve_local_only_paths.py",
    "core/migrations/tracked-ignored-policy.yaml",
    "core/utils/tracked_ignored.py",
    "core/paths.py",
)


def _git_show(revision: str, relative: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{revision}:{relative}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _git_show_or_fixture(revision: str, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{revision}:{relative}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else f"fixture for {relative}\n".encode()


def _write_bytes(repo: Path, relative: str, content: bytes) -> None:
    destination = repo / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)


def _policy_paths(policy_bytes: bytes) -> tuple[str, ...]:
    payload = yaml.safe_load(policy_bytes)
    if payload["schema_version"] == 1:
        rows = payload["paths"]
    else:
        active = payload["active_baseline_version"]
        rows = next(
            baseline["paths"]
            for baseline in payload["baselines"]
            if baseline["baseline_version"] == active
        )
    return tuple(row["path"] for row in rows)


def _seed_pinned_install(repo: Path, release: str) -> tuple[str, tuple[str, ...]]:
    _init_repo(repo)
    pinned = {relative: _git_show(release, relative) for relative in PINNED_RUNTIME_PATHS}
    policy_paths = _policy_paths(pinned["core/migrations/tracked-ignored-policy.yaml"])
    for relative, content in pinned.items():
        _write_bytes(repo, relative, content)
    for relative in policy_paths:
        _write_bytes(repo, relative, _git_show_or_fixture(release, relative))
    _git(repo, "add", "--", *PINNED_RUNTIME_PATHS)
    _git(repo, "add", "-f", "--", *policy_paths)
    _git(repo, "commit", "--quiet", "-m", f"installed {release}")
    return _git(repo, "rev-parse", "HEAD"), policy_paths


def _create_untrack_target(repo: Path, installed_commit: str) -> str:
    _git(repo, "checkout", "--quiet", "-b", "release-target", installed_commit)
    _git(repo, "rm", "-f", "--", *preservation.LOCAL_ONLY_PATHS)
    _write_bytes(repo, preservation.POLICY_RELATIVE.as_posix(), POLICY.read_bytes())
    package = json.loads((repo / "package.json").read_text(encoding="utf-8"))
    package["version"] = "1.64.0"
    _write(repo, "package.json", json.dumps(package, indent=2) + "\n")
    _write(
        repo,
        "System/.local-only-preservation-transition.json",
        json.dumps(
            {"schema_version": 1, "phase": "untrack-v1", "release_version": "1.64.0"},
            indent=2,
        )
        + "\n",
    )
    _git(
        repo,
        "add",
        "--",
        "package.json",
        "System/.local-only-preservation-transition.json",
        preservation.POLICY_RELATIVE.as_posix(),
    )
    _git(repo, "commit", "--quiet", "-m", "untrack-v1 target")
    target_commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "--quiet", "-b", "installed", installed_commit)
    _git(repo, "update-ref", "refs/remotes/upstream/release", target_commit)
    return target_commit


def _pinned_update_block(release: str, marker: str) -> str:
    document = _git_show(release, ".claude/skills/dex-update/SKILL.md").decode()
    section = document.split(marker, 1)[1]
    return section.split("```bash\n", 1)[1].split("\n```", 1)[0]


def _run_bash(repo: Path, block: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{environment['PATH']}"
    return subprocess.run(
        ["bash", "-c", block],
        cwd=repo,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _bash_block_containing(path: Path, marker: str) -> str:
    document = path.read_text(encoding="utf-8")
    for section in document.split("```bash\n")[1:]:
        block = section.split("\n```", 1)[0]
        if marker in block:
            return block
    raise AssertionError(f"No bash block contains {marker!r}")


def test_v162_skip_to_untrack_v1_stops_before_merge_or_mutation(tmp_path: Path) -> None:
    repo = tmp_path / "v162-vault"
    installed_commit, _ = _seed_pinned_install(repo, "v1.62.0")
    _create_untrack_target(repo, installed_commit)
    before = _git(repo, "status", "--porcelain=v1")

    capture_block = _pinned_update_block(
        "v1.62.0", "**A. Inspect the immutable target transition"
    )
    result = _run_bash(repo, capture_block)

    assert result.returncode != 0
    runtime = repo / "System/.dex/local-only-preservation/runtime"
    preview_env = os.environ.copy()
    preview_env["PYTHONPATH"] = str(runtime)
    preview = subprocess.run(
        [
            sys.executable,
            str(runtime / "core/migrations/preserve_local_only_paths.py"),
            "preview",
            "--repo",
            str(repo),
            "--policy",
            str(runtime / "tracked-ignored-policy.yaml"),
        ],
        cwd=repo,
        env=preview_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert preview.returncode != 0
    assert "version does not match package metadata" in preview.stdout
    assert not (repo / "System/.dex/local-only-preservation/journal/journal.json").exists()
    assert _git(repo, "rev-parse", "HEAD") == installed_commit
    assert _git(repo, "status", "--porcelain=v1") == before
    for relative in preservation.LOCAL_ONLY_PATHS:
        assert _git(repo, "ls-files", "--error-unmatch", "--", relative) == relative


def test_v163_shipped_update_captures_real_untrack_hop_and_rollback_restores_tracking(
    tmp_path: Path,
) -> None:
    target_policy = load_exact_policy(POLICY)
    target_transition = load_transition(REPO_ROOT)
    assert target_policy.baseline_version == 1
    assert target_transition.schema_version == 1
    assert target_transition.baseline_version == 1
    assert target_transition.phase == "untrack-v1"
    assert (REPO_ROOT / "System/Beta_Communications/2026-02-04_hardcoded_paths_fix.md").is_file()
    assert all(not (REPO_ROOT / relative).exists() for relative in preservation.LOCAL_ONLY_PATHS)

    repo = tmp_path / "v163-vault"
    installed_commit, policy_paths = _seed_pinned_install(repo, "v1.63.0")
    _create_untrack_target(repo, installed_commit)
    original_bytes = {
        preservation.LOCAL_ONLY_PATHS[0]: b"edited learning one\r\nwith\x00bytes",
        preservation.LOCAL_ONLY_PATHS[1]: b"edited learning two\n",
        preservation.LOCAL_ONLY_PATHS[2]: b"edited local Slack config\r\n",
    }
    original_modes = {
        preservation.LOCAL_ONLY_PATHS[0]: 0o600,
        preservation.LOCAL_ONLY_PATHS[1]: 0o640,
        preservation.LOCAL_ONLY_PATHS[2]: 0o600,
    }
    for relative, content in original_bytes.items():
        target = repo / relative
        target.write_bytes(content)
        target.chmod(original_modes[relative])
    _git(repo, "add", "-f", "--", *preservation.LOCAL_ONLY_PATHS)
    _git(repo, "commit", "--quiet", "-m", "user edits before update")
    rollback_commit = _git(repo, "rev-parse", "HEAD")

    capture_block = _pinned_update_block(
        "v1.63.0", "**A. Inspect the immutable target transition"
    )
    captured = _run_bash(repo, capture_block)
    assert captured.returncode == 0, captured.stdout + captured.stderr

    journal = repo / "System/.dex/local-only-preservation/journal"
    journal_payload = json.loads((journal / preservation.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert journal_payload["phase"] == "captured"
    assert [entry["path"] for entry in journal_payload["entries"]] == list(
        preservation.LOCAL_ONLY_PATHS
    )
    for ordinal, relative in enumerate(preservation.LOCAL_ONLY_PATHS):
        assert (journal / "payloads" / f"apply-{ordinal}.bin").read_bytes() == original_bytes[relative]

    merged = subprocess.run(
        ["git", "merge", "upstream/release", "--no-edit"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert merged.returncode != 0
    assert set(_git(repo, "diff", "--name-only", "--diff-filter=U").splitlines()) == set(
        preservation.LOCAL_ONLY_PATHS
    )

    apply_block = _pinned_update_block(
        "v1.63.0", "**D. Apply local-only preservation immediately after the merge**"
    )
    applied = _run_bash(repo, apply_block)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert _git(repo, "diff", "--name-only", "--diff-filter=U") == ""
    _git(repo, "commit", "--quiet", "--no-edit")

    assert json.loads(
        (journal / preservation.MANIFEST_NAME).read_text(encoding="utf-8")
    )["phase"] == "applied"
    for relative, content in original_bytes.items():
        target = repo / relative
        assert target.read_bytes() == content
        assert stat.S_IMODE(target.stat().st_mode) == original_modes[relative]
        assert subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=repo,
            capture_output=True,
        ).returncode != 0

    newest_bytes = {
        relative: content + b"\nnewest local bytes" for relative, content in original_bytes.items()
    }
    for relative, content in newest_bytes.items():
        (repo / relative).write_bytes(content)

    runtime = repo / "System/.dex/local-only-preservation/runtime"
    runtime_env = os.environ.copy()
    runtime_env["PYTHONPATH"] = str(runtime)
    capture_rewind = subprocess.run(
        [
            sys.executable,
            str(runtime / "core/migrations/preserve_local_only_paths.py"),
            "capture-rewind",
            "--repo",
            str(repo),
            "--journal",
            str(journal),
            "--policy",
            str(runtime / "tracked-ignored-policy.yaml"),
        ],
        cwd=repo,
        env=runtime_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert capture_rewind.returncode == 0, capture_rewind.stdout + capture_rewind.stderr
    _git(repo, "reset", "--hard", rollback_commit)
    rewind = subprocess.run(
        [
            sys.executable,
            str(runtime / "core/migrations/preserve_local_only_paths.py"),
            "rewind",
            "--repo",
            str(repo),
            "--journal",
            str(journal),
            "--policy",
            str(runtime / "tracked-ignored-policy.yaml"),
            "--target-phase",
            "bootstrap-v1",
        ],
        cwd=repo,
        env=runtime_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rewind.returncode == 0, rewind.stdout + rewind.stderr
    assert len(
        _git(repo, "ls-files", "-ci", "--exclude-standard").splitlines()
    ) == len(policy_paths)
    for relative, content in newest_bytes.items():
        assert (repo / relative).read_bytes() == content
        assert _git(repo, "ls-files", "--error-unmatch", "--", relative) == relative


def test_manifest_is_a_deterministic_newline_path_list(tmp_path: Path) -> None:
    repo = tmp_path / "manifest-repo"
    _init_repo(repo)
    _write(repo, "z-last.txt", "z\n")
    _write(repo, "a directory/first.txt", "a\n")
    _git(repo, "add", "--", "z-last.txt", "a directory/first.txt")
    _git(repo, "commit", "--quiet", "-m", "synthetic tree")

    assert generate_manifest(repo, "HEAD") == "a directory/first.txt\nz-last.txt\n"


def test_rollback_stops_when_autosave_commit_fails(tmp_path: Path) -> None:
    vault = tmp_path / "user-vault"
    _init_repo(vault)
    (vault / "core/utils").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "core/utils/safe_autosave.py", vault / "core/utils/safe_autosave.py")
    shutil.copy2(
        REPO_ROOT / "core/utils/integration_credentials.py",
        vault / "core/utils/integration_credentials.py",
    )

    tracked_file = "04-Projects/current-work.md"
    _write(vault, tracked_file, "release v1\n")
    _write(vault, "package.json", json.dumps({"version": "1.61.0"}) + "\n")
    _write(
        vault,
        "System/.local-only-preservation-transition.json",
        json.dumps({"schema_version": 1, "phase": "bootstrap-v1", "release_version": "1.61.0"}) + "\n",
    )
    _write(vault, ".claude/keep", "fixture\n")
    _git(
        vault,
        "add",
        "--",
        tracked_file,
        "package.json",
        "System/.local-only-preservation-transition.json",
        ".claude/keep",
    )
    _git(vault, "commit", "--quiet", "-m", "release v1")
    _git(vault, "tag", "backup-before-v1.3.0")

    _write(vault, tracked_file, "release v2\n")
    _git(vault, "add", "--", tracked_file)
    _git(vault, "commit", "--quiet", "-m", "release v2")
    release_v2_head = _git(vault, "rev-parse", "HEAD")

    edited_content = "release v2\nuser's uncommitted edit\n"
    staged_new_file = ".claude/skills/private-custom/SKILL.md"
    staged_new_content = "---\nname: private-custom\n---\n# User work\n"
    _write(vault, tracked_file, edited_content)
    _write(vault, staged_new_file, staged_new_content)
    _git(vault, "add", "--", staged_new_file)

    hooks_dir = tmp_path / "failing-hooks"
    hooks_dir.mkdir()
    pre_commit = hooks_dir / "pre-commit"
    pre_commit.write_text(
        "#!/bin/sh\necho 'forced pre-commit failure' >&2\nexit 1\n",
        encoding="utf-8",
    )
    pre_commit.chmod(0o755)
    _git(vault, "config", "core.hooksPath", str(hooks_dir))

    runtime = vault / "System/.dex/local-only-preservation/runtime"
    (runtime / "core/migrations").mkdir(parents=True)
    (runtime / "core/utils").mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT / "core/migrations/preserve_local_only_paths.py",
        runtime / "core/migrations/preserve_local_only_paths.py",
    )
    shutil.copy2(REPO_ROOT / "core/utils/tracked_ignored.py", runtime / "core/utils/tracked_ignored.py")
    shutil.copy2(REPO_ROOT / "core/paths.py", runtime / "core/paths.py")
    (runtime / "core/__init__.py").touch()
    (runtime / "core/migrations/__init__.py").touch()
    (runtime / "core/utils/__init__.py").touch()

    protected_rollback = _bash_block_containing(
        ROLLBACK_SKILL,
        'DEX_ROLLBACK_TARGET="backup-before-v1.3.0"',
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            protected_rollback,
        ],
        cwd=vault,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert _git(vault, "rev-parse", "HEAD") == release_v2_head
    assert (vault / tracked_file).read_text(encoding="utf-8") == edited_content
    assert (vault / staged_new_file).read_text(encoding="utf-8") == staged_new_content
    assert not any(tag.startswith("before-rollback-") for tag in _git(vault, "tag").splitlines())
    assert _git(vault, "diff", "--cached", "--name-only") == staged_new_file
    assert "Git could not prepare the current state" in result.stdout + result.stderr
    assert "dex-user-data-before-rollback" in _git(vault, "stash", "list")


def test_update_then_manifest_rollback_preserves_user_customizations(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    _init_repo(upstream)
    _write(upstream, "core/shipped.txt", "Dex v1\n")
    _write(upstream, "README.md", "Dex release v1\n")
    _write(
        upstream,
        "CLAUDE.md",
        "# Dex\n\n<!-- USER_EXTENSIONS_START -->\n<!-- USER_EXTENSIONS_END -->\n",
    )
    _write(
        upstream,
        ".mcp.json",
        json.dumps({"mcpServers": {"dex-work": {"command": "python3", "args": ["core.py"]}}}, indent=2)
        + "\n",
    )
    _write(upstream, ".claude/skills/daily-plan/SKILL.md", "---\nname: daily-plan\n---\n")
    _git(
        upstream,
        "add",
        "--",
        "core/shipped.txt",
        "README.md",
        "CLAUDE.md",
        ".mcp.json",
        ".claude/skills/daily-plan/SKILL.md",
    )
    _git(upstream, "commit", "--quiet", "-m", "release v1 files")
    _commit_manifest(upstream, "release v1 manifest")
    _git(upstream, "branch", "v1")

    _git(upstream, "checkout", "--quiet", "-b", "v2")
    _write(upstream, "README.md", "Dex release v2\n")
    _write(upstream, "core/v2-added.txt", "new in v2\n")
    _write(upstream, "core/future-collision.txt", "same user and release content\n")
    _write(upstream, "core/new-dir/sentinel.txt", "new nested release file\n")
    _git(
        upstream,
        "add",
        "--",
        "README.md",
        "core/v2-added.txt",
        "core/future-collision.txt",
        "core/new-dir/sentinel.txt",
    )
    _git(upstream, "commit", "--quiet", "-m", "release v2 files")
    _commit_manifest(upstream, "release v2 manifest")
    _git(upstream, "branch", "release")

    vault = tmp_path / "user-vault"
    subprocess.run(
        ["git", "clone", "--quiet", "--branch", "v1", str(upstream), str(vault)],
        check=True,
    )
    _git(vault, "config", "user.name", "Dex User")
    _git(vault, "config", "user.email", "user@example.com")

    custom_skill = ".claude/skills/my-workflow-custom/SKILL.md"
    _write(vault, custom_skill, "---\nname: my-workflow-custom\n---\n# Mine\n")
    collision = "core/future-collision.txt"
    _write(vault, collision, "same user and release content\n")
    mcp_config = json.loads((vault / ".mcp.json").read_text(encoding="utf-8"))
    mcp_config["mcpServers"]["custom-sentinel"] = {
        "command": "sentinel-command",
        "args": ["must-never-run"],
    }
    (vault / ".mcp.json").write_text(json.dumps(mcp_config, indent=2) + "\n", encoding="utf-8")
    (vault / "core/shipped.txt").write_text("Dex v1\nUser patch\n", encoding="utf-8")
    (vault / "CLAUDE.md").write_text(
        "# Dex\n\n<!-- USER_EXTENSIONS_START -->\nMy local extension\n<!-- USER_EXTENSIONS_END -->\n",
        encoding="utf-8",
    )
    _git(
        vault,
        "add",
        "--",
        custom_skill,
        collision,
        ".mcp.json",
        "core/shipped.txt",
        "CLAUDE.md",
    )
    _git(vault, "commit", "--quiet", "-m", "user customizations")
    _git(vault, "tag", "backup-before-v2")

    _git(vault, "merge", "--quiet", "--no-edit", "origin/release")

    assert (vault / custom_skill).is_file()
    assert "custom-sentinel" in json.loads((vault / ".mcp.json").read_text())["mcpServers"]
    assert "User patch" in (vault / "core/shipped.txt").read_text(encoding="utf-8")
    assert "My local extension" in (vault / "CLAUDE.md").read_text(encoding="utf-8")
    assert (vault / "core/v2-added.txt").is_file()
    assert (vault / collision).read_text(encoding="utf-8") == "same user and release content\n"

    # A user-owned merge commit must not be allowed to redefine the shipped manifest.
    manifest = vault / DEFAULT_MANIFEST
    manifest.write_text(manifest.read_text(encoding="utf-8") + "user-secret.txt\n", encoding="utf-8")
    _git(vault, "add", "--", str(DEFAULT_MANIFEST))
    _git(vault, "commit", "--quiet", "-m", "user tampers with installed manifest")

    newer_release = _git(vault, "merge-base", "HEAD", "origin/release")
    newer_manifest_snapshot = tmp_path / "newer-installed-files.manifest"
    newer_manifest_snapshot.write_text(
        _git(vault, "show", f"{newer_release}:{DEFAULT_MANIFEST.as_posix()}") + "\n",
        encoding="utf-8",
    )
    assert "user-secret.txt" not in newer_manifest_snapshot.read_text(encoding="utf-8")
    _git(vault, "reset", "--hard", "backup-before-v2")

    restored_release = _git(vault, "merge-base", "HEAD", "origin/release")
    newer_paths = set(newer_manifest_snapshot.read_text(encoding="utf-8").splitlines())
    restored_paths = set(
        _git(vault, "show", f"{restored_release}:{DEFAULT_MANIFEST.as_posix()}").splitlines()
    )
    update_added_paths = newer_paths - restored_paths
    assert "core/v2-added.txt" in update_added_paths
    assert collision in update_added_paths
    assert custom_skill not in newer_paths

    # Model an unchanged newer-release file left behind after reset so the
    # manifest cleanup, rather than reset itself, must remove it.
    _write(vault, "core/v2-added.txt", "new in v2\n")

    outside = tmp_path / "outside"
    outside.mkdir()
    outside_sentinel = outside / "sentinel.txt"
    outside_sentinel.write_text("new nested release file\n", encoding="utf-8")
    (vault / "core" / "new-dir").symlink_to(outside, target_is_directory=True)

    for relative in sorted(update_added_paths):
        candidate = vault / relative
        tracked_in_restored_state = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{relative}"],
            cwd=vault,
            check=False,
            capture_output=True,
        ).returncode == 0
        if tracked_in_restored_state:
            continue
        parts = Path(relative).parts
        if (
            not parts
            or Path(relative).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
        ):
            continue
        prefix = vault
        if any((prefix := prefix / part).is_symlink() for part in parts[:-1]):
            continue
        if candidate.is_symlink() or not candidate.is_file():
            continue
        expected_blob = _git(vault, "rev-parse", f"{newer_release}:{relative}")
        actual_blob = _git(vault, "hash-object", "--", relative)
        if actual_blob == expected_blob:
            candidate.unlink()

    assert (vault / custom_skill).is_file()
    assert "custom-sentinel" in json.loads((vault / ".mcp.json").read_text())["mcpServers"]
    assert "User patch" in (vault / "core/shipped.txt").read_text(encoding="utf-8")
    assert "My local extension" in (vault / "CLAUDE.md").read_text(encoding="utf-8")
    assert (vault / collision).read_text(encoding="utf-8") == "same user and release content\n"
    assert not (vault / "core/v2-added.txt").exists()
    assert outside_sentinel.read_text(encoding="utf-8") == "new nested release file\n"
