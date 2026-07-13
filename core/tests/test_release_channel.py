"""Contract tests for the per-machine release-channel resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.utils.release_channel import read_channel, release_branch, release_ref_candidates


def _write_profile(vault_root: Path, content: str) -> None:
    profile = vault_root / "System" / "user-profile.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("name: Test User\n", "stable"),
        ("updates: {}\n", "stable"),
        ("updates:\n  channel: stable\n", "stable"),
        ("updates:\n  channel: beta\n", "beta"),
        ("updates:\n  channel: Stable\n", "invalid"),
        ("updates:\n  channel: nightly\n", "invalid"),
        ("updates:\n  channel: null\n", "invalid"),
        ("updates:\n  channel: 1\n", "invalid"),
    ],
)
def test_read_channel_resolves_present_and_absent_values(
    tmp_path: Path,
    content: str,
    expected: str,
) -> None:
    _write_profile(tmp_path, content)

    assert read_channel(tmp_path) == expected


def test_read_channel_defaults_to_stable_when_profile_is_missing(tmp_path: Path) -> None:
    assert read_channel(tmp_path) == "stable"


def test_read_channel_returns_invalid_when_profile_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_profile(tmp_path, "updates:\n  channel: beta\n")

    def refuse_read(_path: Path, *_args: object, **_kwargs: object) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", refuse_read)

    assert read_channel(tmp_path) == "invalid"


def test_read_channel_returns_invalid_when_profile_yaml_cannot_be_parsed(tmp_path: Path) -> None:
    _write_profile(tmp_path, "updates:\n  channel: [beta\n")

    assert read_channel(tmp_path) == "invalid"


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        ("stable", ("upstream/release", "origin/release")),
        ("beta", ("upstream/release-beta", "origin/release-beta")),
        ("invalid", ()),
        ("nightly", ()),
    ],
)
def test_release_ref_candidates_are_channel_specific(
    channel: str,
    expected: tuple[str, ...],
) -> None:
    assert release_ref_candidates(channel) == expected


@pytest.mark.parametrize(
    ("channel", "expected"),
    [("stable", "release"), ("beta", "release-beta"), ("invalid", None), ("nightly", None)],
)
def test_release_branch_is_channel_specific(channel: str, expected: str | None) -> None:
    assert release_branch(channel) == expected
