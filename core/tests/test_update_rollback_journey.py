"""Integration coverage for update manifests and rollback preservation."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from core.migrations import preserve_local_only_paths as preservation
from core.utils.manifest import DEFAULT_MANIFEST, generate_manifest, write_manifest
from core.utils.tracked_ignored import RETIRED_FOUNDER_PATHS, load_exact_policy, load_transition

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


def test_update_and_duplicated_rollback_flows_recognize_the_v2_boundary() -> None:
    update = UPDATE_SKILL.read_text(encoding="utf-8")
    rollback = ROLLBACK_SKILL.read_text(encoding="utf-8")

    assert "untrack-v1|untrack-v2)" in update
    assert update.count("bootstrap-v1|bootstrap-v2|bootstrap-legacy)") == 2
    assert update.count("untrack-v1|untrack-v2|untrack-legacy)") == 2
    assert rollback.count("bootstrap-v2:bootstrap-v1") == 2
    assert rollback.count("untrack-v2:bootstrap-v1") == 2

    matrix_marker = 'case "$DEX_CURRENT_LOCAL_ONLY_PHASE:$DEX_TARGET_LOCAL_ONLY_PHASE" in\n'
    matrices = [
        section.split("esac", 1)[0]
        for section in rollback.split(matrix_marker)[1:]
    ]
    assert len(matrices) == 2
    assert matrices[0] == matrices[1]


def test_v162_parser_refuses_this_release_before_any_update_mutation(tmp_path: Path) -> None:
    legacy_source = subprocess.run(
        ["git", "show", "v1.62.0:core/utils/tracked_ignored.py"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    legacy_module = tmp_path / "legacy_v162_tracked_ignored.py"
    legacy_module.write_bytes(legacy_source)
    program = """
import importlib.util
import pathlib
import sys

spec = importlib.util.spec_from_file_location("legacy_v162_tracked_ignored", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
try:
    module.load_transition_pair(pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]))
except module.TrackedIgnoredError as error:
    print(error)
    raise SystemExit(0)
raise SystemExit("v1.62 unexpectedly accepted the v2 release transition")
"""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(legacy_module),
            str(REPO_ROOT / "System/.local-only-preservation-transition.json"),
            str(REPO_ROOT / "package.json"),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "local-only preservation transition has unexpected fields"
    update = UPDATE_SKILL.read_text(encoding="utf-8")
    assert "Update to v1.63.0 first, then run /dex-update again" in update


def test_release_cut_stamps_transition_metadata_from_the_bumped_package(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "release-cut"
    _write(repo, "package.json", json.dumps({"version": "1.63.0"}) + "\n")
    _write(
        repo,
        "System/.local-only-preservation-transition.json",
        json.dumps({"schema_version": 1, "phase": "bootstrap-v1", "release_version": "1.62.0"})
        + "\n",
    )

    assert preservation.main(["stamp-transition", "--repo", str(repo)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "phase": "bootstrap-v1",
        "release_version": "1.63.0",
    }
    assert json.loads(
        (repo / "System/.local-only-preservation-transition.json").read_text(encoding="utf-8")
    ) == {"schema_version": 1, "phase": "bootstrap-v1", "release_version": "1.63.0"}

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


def _write_transition(repo: Path, phase: str, version: str = "1.62.0") -> None:
    schema_version = 2 if phase.endswith("-v2") else 1
    payload = {"schema_version": schema_version, "phase": phase, "release_version": version}
    if schema_version == 2:
        payload["baseline_version"] = 2
    _write(repo, "package.json", json.dumps({"version": version}) + "\n")
    _write(repo, "System/.local-only-preservation-transition.json", json.dumps(payload) + "\n")


def _dual_policy(active_baseline: int) -> bytes:
    payload = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    payload["active_baseline_version"] = active_baseline
    return yaml.safe_dump(payload, sort_keys=False).encode()


def _seed_bridge_baseline(repo: Path) -> tuple[str, str]:
    _init_repo(repo)
    policy = load_exact_policy(POLICY)
    rows = policy.rows_for(1)
    ignored = []
    for index, row in enumerate(rows):
        _write(repo, row.path, f"bridge-{index}\n")
        ignored.append(f"/{row.path}")
    fixture_policy = repo / preservation.POLICY_RELATIVE
    fixture_policy.parent.mkdir(parents=True, exist_ok=True)
    fixture_policy.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "baseline_count": len(rows),
                "paths": [
                    {"path": row.path, "classification": row.classification}
                    for row in rows
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _write_transition(repo, "bootstrap-v1", "1.62.0")
    _write(repo, ".gitignore", "\n".join(ignored) + "\n")
    _git(
        repo,
        "add",
        "--",
        ".gitignore",
        "package.json",
        "System/.local-only-preservation-transition.json",
        preservation.POLICY_RELATIVE.as_posix(),
    )
    _git(repo, "add", "-f", "--", *[row.path for row in rows])
    _git(repo, "commit", "--quiet", "-m", "v1.62 baseline")
    v162_commit = _git(repo, "rev-parse", "HEAD")

    fixture_policy.write_bytes(_dual_policy(1))
    _write_transition(repo, "bootstrap-v1", "1.63.0")
    _git(
        repo,
        "add",
        "--",
        "package.json",
        "System/.local-only-preservation-transition.json",
        preservation.POLICY_RELATIVE.as_posix(),
    )
    _git(repo, "commit", "--quiet", "-m", "v1.63 bridge baseline")
    return v162_commit, _git(repo, "rev-parse", "HEAD")


def _bash_block_after(path: Path, marker: str) -> str:
    section = path.read_text(encoding="utf-8").split(marker, 1)[1]
    return section.split("```bash\n", 1)[1].split("\n```", 1)[0]


def _bash_block_containing(path: Path, marker: str) -> str:
    document = path.read_text(encoding="utf-8")
    for section in document.split("```bash\n")[1:]:
        block = section.split("\n```", 1)[0]
        if marker in block:
            return block
    raise AssertionError(f"No bash block contains {marker!r}")


@pytest.mark.parametrize("rollback_release", ["v1.63.0", "v1.62.0"])
def test_bridge_update_into_real_v2_tree_and_cross_boundary_rollback_are_byte_exact(
    tmp_path: Path, rollback_release: str
) -> None:
    target_policy = load_exact_policy(POLICY)
    target_transition = load_transition(REPO_ROOT)
    assert target_policy.baseline_version == 2
    assert target_transition.schema_version == 2
    assert target_transition.baseline_version == 2
    assert target_transition.phase == "bootstrap-v2"
    assert not any((REPO_ROOT / relative).exists() for relative in RETIRED_FOUNDER_PATHS)

    repo = tmp_path / "bridge-vault"
    v162_commit, bridge_commit = _seed_bridge_baseline(repo)
    bridge_policy = tmp_path / "bridge-policy.yaml"
    bridge_policy.write_bytes(_dual_policy(1))
    rollback_commit = bridge_commit if rollback_release == "v1.63.0" else v162_commit
    first, second, slack = preservation.LOCAL_ONLY_PATHS
    first_target = repo / first
    second_target = repo / second
    slack_target = repo / slack
    first_target.write_bytes(b"user learning before deletion\r\nwith\x00bytes")
    first_target.chmod(0o600)
    second_target.unlink()
    slack_target.write_bytes(b"user Slack before the v2 baseline\n")
    slack_target.chmod(0o640)
    journal = tmp_path / "preservation-journal"

    captured = preservation.capture(repo, journal, bridge_policy)
    assert captured["schema_version"] == 1
    assert len(captured["entries"]) == 3

    _git(repo, "rm", "-f", "--", *sorted(RETIRED_FOUNDER_PATHS))
    (repo / preservation.POLICY_RELATIVE).write_bytes(POLICY.read_bytes())
    (repo / "System/.local-only-preservation-transition.json").write_bytes(
        (REPO_ROOT / "System/.local-only-preservation-transition.json").read_bytes()
    )
    (repo / "package.json").write_bytes((REPO_ROOT / "package.json").read_bytes())
    _git(
        repo,
        "add",
        "--",
        "package.json",
        "System/.local-only-preservation-transition.json",
        preservation.POLICY_RELATIVE.as_posix(),
    )
    _git(repo, "commit", "--quiet", "-m", "real v2 24-row baseline")

    assert preservation.preview(repo, bridge_policy) == {
        "ok": True,
        "state": "bootstrap-installed",
        "actual_count": 24,
    }
    assert preservation.apply(repo, journal, bridge_policy)["phase"] == "applied"
    assert first_target.read_bytes() == b"user learning before deletion\r\nwith\x00bytes"
    assert stat.S_IMODE(first_target.stat().st_mode) == 0o600
    assert not second_target.exists()

    first_target.write_bytes(b"newest learning after deletion\x00")
    first_target.chmod(0o640)
    slack_target.write_bytes(b"newest Slack after deletion\r\n")
    slack_target.chmod(0o600)
    preservation.capture_rewind(repo, journal, bridge_policy)
    _git(repo, "reset", "--hard", rollback_commit)

    expected_index = {
        row.path: _git(repo, "ls-files", "--stage", "--", row.path)
        for row in load_exact_policy(bridge_policy).rows_for(1)
    }

    assert preservation.rewind(repo, journal, bridge_policy)["phase"] == "rewound"
    assert first_target.read_bytes() == b"newest learning after deletion\x00"
    assert stat.S_IMODE(first_target.stat().st_mode) == 0o640
    assert not second_target.exists()
    assert slack_target.read_bytes() == b"newest Slack after deletion\r\n"
    assert stat.S_IMODE(slack_target.stat().st_mode) == 0o600
    assert len(preservation._query_tracked_ignored(repo)) == 27
    assert {
        path: _git(repo, "ls-files", "--stage", "--", path)
        for path in expected_index
    } == expected_index
    assert (repo / "System/Beta_Communications/2026-02-04_hardcoded_paths_fix.md").is_file()


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
