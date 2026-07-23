"""Tests for the live Dex Core shipped/local/planned state ledger."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import dex_state

REPO_ROOT = Path(__file__).resolve().parents[2]
PLANNED_START = "<!-- PLANNED:START -->"
PLANNED_END = "<!-- PLANNED:END -->"


def _state_document(planned: str) -> str:
    return (
        "# Dex Core State\n\n"
        "Purpose.\n\n"
        "<!-- GENERATED:START -->\n"
        "stale generated content\n"
        "<!-- GENERATED:END -->\n\n"
        f"{PLANNED_START}{planned}{PLANNED_END}\n"
    )


def _planned_region(document: str) -> str:
    start = document.index(PLANNED_START)
    end = document.index(PLANNED_END) + len(PLANNED_END)
    return document[start:end]


def test_two_write_runs_are_deterministic(tmp_path: Path) -> None:
    state_path = tmp_path / "STATE.md"
    state_path.write_text(_state_document("\n- Keep this exactly.  \n"), encoding="utf-8")

    assert dex_state.main(["--write"], repo_root=REPO_ROOT, state_path=state_path) == 0
    first = state_path.read_bytes()
    assert dex_state.main(["--write"], repo_root=REPO_ROOT, state_path=state_path) == 0

    assert state_path.read_bytes() == first


def test_live_repo_release_and_pull_request_subject_parsing() -> None:
    expected_tags = subprocess.run(
        ["git", "tag", "--sort=-v:refname", "--list", "v[0-9]*"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    expected_subjects = subprocess.run(
        ["git", "log", "--format=%s", f"{expected_tags[0]}..HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    release = dex_state.find_latest_release(REPO_ROOT)
    unreleased = dex_state.find_unreleased(REPO_ROOT, expected_tags[0])
    parsed = dex_state.parse_unreleased_subject(
        "docs(architecture): add DEX-CORE-MAP grounding narrative (#181)"
    )

    assert release is not None
    assert release.tag == expected_tags[0]
    assert release.commit_date
    assert unreleased is not None
    assert [commit.subject for commit in unreleased] == expected_subjects
    assert parsed.subject == "docs(architecture): add DEX-CORE-MAP grounding narrative (#181)"
    assert parsed.pr_number == 181


def test_write_preserves_hand_maintained_planned_block_verbatim(tmp_path: Path) -> None:
    planned = "\n- First item.  \n\n  Indented continuation.\n- Final item.\n"
    state_path = tmp_path / "STATE.md"
    before = _state_document(planned)
    state_path.write_text(before, encoding="utf-8")

    assert dex_state.main(["--write"], repo_root=REPO_ROOT, state_path=state_path) == 0

    after = state_path.read_text(encoding="utf-8")
    assert _planned_region(after) == _planned_region(before)
    assert "stale generated content" not in after


def test_no_tag_degrades_to_minimal_success_output(monkeypatch, capsys) -> None:
    monkeypatch.setattr(dex_state, "find_latest_release", lambda _repo_root: None)

    assert dex_state.main(["--digest"], repo_root=REPO_ROOT) == 0

    output = capsys.readouterr().out
    assert "Released: unknown (no version tag found)" in output
    assert "On main, not yet released" not in output


def test_detached_head_skips_the_unavailable_delta(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        dex_state,
        "find_latest_release",
        lambda _repo_root: dex_state.Release("v1.68.0", "2026-07-22"),
    )
    monkeypatch.setattr(dex_state, "_git", lambda _repo_root, *_args: None)

    state = dex_state.collect_state(REPO_ROOT, tmp_path / "missing-state.md")

    assert "Released: v1.68.0 (2026-07-22)" in dex_state.render_digest(state)
    assert "On main, not yet released" not in dex_state.render_digest(state)
