"""Product .gitignore must whitelist hook files without un-ignoring the tree.

The Feb-era rules ignored ``.claude/hooks/`` and then immediately wrote
``!.claude/hooks/``. That second line un-ignores the directory itself, so Git
never applies the later named whitelist. A copied local hook then shows up in
``git status`` and can be committed by accident.

The shipped-seed gate (``scripts/check-tracked-ignored.py``) already fails CI
when a tracked path is also ignored and is not a declared seed. These tests
lock the hooks contract specifically: the three-step form, no blanket
directory un-ignore, chassis-tracked hooks stay addable, and unlisted copies
stay ignored.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from core.utils.tracked_ignored import query_tracked_ignored

REPO_ROOT = Path(__file__).resolve().parents[2]
GITIGNORE = REPO_ROOT / ".gitignore"

# The original named whitelist. Remaining tracked product hooks follow in
# .gitignore so the chassis files already in the index do not become
# tracked-despite-ignored (which the shipped-seed gate rejects).
CORE_HOOK_WHITELIST = (
    ".claude/hooks/dex-safety-guard.sh",
    ".claude/hooks/person-context-injector.cjs",
    ".claude/hooks/company-context-injector.cjs",
    ".claude/hooks/paths.cjs",
    ".claude/hooks/tests/hook-harness.test.cjs",
)

CANARY_HOOKS = (
    ".claude/hooks/copied-local-hook.cjs",
    ".claude/hooks/scratch.md",
    ".claude/hooks/tests/helper.cjs",
    ".claude/hooks/tests/notes.md",
)


def _gitignore_lines() -> list[str]:
    return GITIGNORE.read_text(encoding="utf-8").splitlines()


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def test_hooks_gitignore_uses_three_step_form_without_blanket_unignore() -> None:
    lines = _gitignore_lines()
    assert ".claude/hooks/**" in lines
    assert "!.claude/hooks/**/" in lines
    assert "!.claude/hooks/" not in lines
    for relative in CORE_HOOK_WHITELIST:
        if relative.endswith(".test.cjs"):
            assert "!.claude/hooks/tests/*.test.cjs" in lines
        else:
            assert f"!{relative}" in lines


def test_no_tracked_hook_is_ignored() -> None:
    ignored = [
        path
        for path in query_tracked_ignored(REPO_ROOT)
        if path.startswith(".claude/hooks/")
    ]
    assert ignored == [], ignored


def test_unlisted_hook_copies_are_ignored_and_core_files_stay_addable(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "hooks-gitignore"
    repo.mkdir()
    (repo / ".gitignore").write_bytes(GITIGNORE.read_bytes())
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Dex Gitignore Tests")
    _git(repo, "config", "user.email", "gitignore@example.com")

    for relative in (*CORE_HOOK_WHITELIST, *CANARY_HOOKS):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n", encoding="utf-8")

    _git(repo, "add", "-A")
    staged = set(
        _git(repo, "diff", "--cached", "--name-only").stdout.splitlines()
    )

    for relative in CORE_HOOK_WHITELIST:
        assert relative in staged, relative
    for relative in CANARY_HOOKS:
        assert relative not in staged, relative

    ignored = set(
        _git(repo, "check-ignore", "--", *CANARY_HOOKS).stdout.splitlines()
    )
    assert ignored == set(CANARY_HOOKS)
