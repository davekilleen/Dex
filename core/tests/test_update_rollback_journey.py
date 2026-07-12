"""Integration coverage for update manifests and rollback preservation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core.utils.manifest import DEFAULT_MANIFEST, generate_manifest, write_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLLBACK_SKILL = REPO_ROOT / ".claude/skills/dex-rollback/SKILL.md"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


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

    tracked_file = "04-Projects/current-work.md"
    _write(vault, tracked_file, "release v1\n")
    _git(vault, "add", "--", tracked_file)
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
    assert _git(vault, "diff", "--cached", "--name-only") == ""
    assert "Git could not save the current state" in result.stdout + result.stderr
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
