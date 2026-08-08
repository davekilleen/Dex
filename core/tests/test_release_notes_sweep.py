"""Tests for the one-time release notes sweep (core/utils/release_notes_sweep.py)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core.utils import release_notes_sweep


def _write_install(vault: Path, version: str, changelog: str = "") -> None:
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "package.json").write_text(
        json.dumps({"name": "dex-pkm", "version": version}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    profile = vault / "System" / ".release-evidence-profile.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        json.dumps(
            {"profile": "legacy-v1", "release_version": version, "schema_version": 1},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (vault / "CHANGELOG.md").write_text(changelog, encoding="utf-8")


def _state_path(vault: Path) -> Path:
    return vault / "System" / ".dex" / "release-notes-state.json"


def _write_state(vault: Path, version: str) -> None:
    path = _state_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_announced_version": version}), encoding="utf-8")


def test_first_run_seeds_current_version_without_notice(tmp_path):
    _write_install(tmp_path, "1.82.0")

    assert release_notes_sweep.sweep(tmp_path) is None
    assert json.loads(_state_path(tmp_path).read_text(encoding="utf-8")) == {
        "last_announced_version": "1.82.0"
    }


def test_update_announces_once_then_stays_silent(tmp_path):
    _write_install(
        tmp_path,
        "1.82.0",
        """# Changelog

## [1.82.0] — 💬 Found a bug? Dex reports it for you (2026-08-08)

**What this fixes for you:**

* **Report a bug with zero homework.** Dex writes the report.
* **Nothing private ever leaves your machine.** Your notes stay local.
* **You choose how involved to be.** Review it or automate it.
* **You hear back.** Dex tells you when it is fixed.
""",
    )
    _write_state(tmp_path, "1.81.19")

    assert release_notes_sweep.sweep(tmp_path) == (
        "◆ Dex updated to v1.82.0\n"
        "💬 Found a bug? Dex reports it for you\n"
        "• Report a bug with zero homework\n"
        "• Nothing private ever leaves your machine\n"
        "• You choose how involved to be\n"
        "Full story: https://heydex.ai/releases/"
    )
    assert release_notes_sweep.sweep(tmp_path) is None


def test_concurrent_session_starts_still_announce_version_once(tmp_path):
    _write_install(
        tmp_path,
        "1.82.0",
        """## [1.82.0] — One update (2026-08-08)

* **One change.** More detail.
""",
    )
    _write_state(tmp_path, "1.81.19")

    with ThreadPoolExecutor(max_workers=8) as pool:
        notices = list(pool.map(lambda _: release_notes_sweep.sweep(tmp_path), range(8)))

    assert sum(notice is not None for notice in notices) == 1


def test_skipped_versions_are_counted_but_only_newest_is_announced(tmp_path):
    _write_install(
        tmp_path,
        "1.82.2",
        """# Changelog

## [1.82.2] — The newest story (2026-08-10)

* **Newest capability.** This is the one to announce.

## [1.82.1] — An intermediate story (2026-08-09)

* **Intermediate capability.** Do not include this detail.

## [1.82.0] — The first skipped story (2026-08-08)

* **First skipped capability.** Do not include this detail.

## [1.81.19] — The last announced story (2026-08-07)
""",
    )
    _write_state(tmp_path, "1.81.19")

    notice = release_notes_sweep.sweep(tmp_path)

    assert notice == (
        "◆ Dex updated to v1.82.2 (…and 2 earlier updates)\n"
        "The newest story\n"
        "• Newest capability\n"
        "Full story: https://heydex.ai/releases/"
    )
    assert "Intermediate capability" not in notice
    assert "First skipped capability" not in notice


def test_missing_changelog_section_falls_back_to_version_and_url(tmp_path):
    _write_install(
        tmp_path,
        "1.82.1",
        """# Changelog

## [1.82.0] — An older story (2026-08-08)

* **An older capability.** Not part of this release.
""",
    )
    _write_state(tmp_path, "1.82.0")

    assert release_notes_sweep.sweep(tmp_path) == (
        "◆ Dex updated to v1.82.1\nFull story: https://heydex.ai/releases/"
    )


def test_malformed_state_fails_open_and_reseeds_without_notice(tmp_path):
    _write_install(tmp_path, "1.82.0")
    path = _state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    assert release_notes_sweep.sweep(tmp_path) is None
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "last_announced_version": "1.82.0"
    }


def test_main_emits_session_start_hook_json(tmp_path, capsys):
    _write_install(
        tmp_path,
        "1.82.0",
        """## [1.82.0] — A visible update (2026-08-08)

* **One useful change.** More detail.
""",
    )
    _write_state(tmp_path, "1.81.19")

    assert release_notes_sweep.main(["--vault", str(tmp_path), "--session-start"]) == 0

    decoded = json.loads(capsys.readouterr().out)
    assert decoded == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "\n◆ Dex updated to v1.82.0\n"
                "A visible update\n"
                "• One useful change\n"
                "Full story: https://heydex.ai/releases/\n"
            ),
        }
    }


def test_main_is_fail_open_but_debug_mode_reraises(tmp_path, monkeypatch, capsys):
    def crash(_vault):
        raise RuntimeError("broken hook")

    monkeypatch.setattr(release_notes_sweep, "sweep", crash)
    assert release_notes_sweep.main(["--vault", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""

    monkeypatch.setenv("DEX_RELEASE_NOTES_DEBUG", "1")
    with pytest.raises(RuntimeError, match="broken hook"):
        release_notes_sweep.main(["--vault", str(tmp_path)])
