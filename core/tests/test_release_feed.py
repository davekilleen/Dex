"""Tests for the fail-open public release-headline garnish."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.utils import release_feed, update_verifier

FIXTURE = Path(__file__).parent / "fixtures" / "releases-feed.md"
BASE_NOTICE = "\n".join(
    (
        "A newer version of Dex is available: v1.82.0",
        "Release notes: https://github.com/davekilleen/Dex/releases/tag/v1.82.0",
        "Run /dex-update when you're ready — Dex never updates itself without you.",
    )
)


def _fixture_headlines() -> tuple[release_feed.ReleaseHeadline, ...]:
    return release_feed.extract_release_headlines(FIXTURE.read_text(encoding="utf-8"))


def test_extracts_headlines_from_releases_markdown_fixture_newest_first():
    assert _fixture_headlines() == (
        release_feed.ReleaseHeadline(
            "1.83.0",
            "A newer headline even when the feed is out of order",
        ),
        release_feed.ReleaseHeadline(
            "1.82.0",
            "💬 Found a bug? Dex reports it for you — and tells you when it's fixed",
        ),
        release_feed.ReleaseHeadline(
            "1.81.19",
            "The update before feedback awareness",
        ),
    )


def test_filters_strictly_newer_than_installed_and_not_beyond_available():
    selected = release_feed.select_release_headlines(
        _fixture_headlines(),
        installed_version="1.81.19",
        available_version="1.82.0",
    )

    assert selected == (
        release_feed.ReleaseHeadline(
            "1.82.0",
            "💬 Found a bug? Dex reports it for you — and tells you when it's fixed",
        ),
    )


def test_notice_shows_at_most_three_headlines_and_counts_the_rest():
    headlines = tuple(
        release_feed.ReleaseHeadline(f"1.82.{patch}", f"Headline {patch}")
        for patch in range(5, 0, -1)
    )

    assert release_feed.format_notice(BASE_NOTICE, headlines) == (
        f"{BASE_NOTICE}\n"
        "New since your version:\n"
        "• Headline 5\n"
        "• Headline 4\n"
        "• Headline 3\n"
        "…and 2 more — full story: https://heydex.ai/releases/"
    )


def test_fresh_cache_is_reused_without_network(tmp_path, monkeypatch):
    cache_path = tmp_path / release_feed.CACHE_PATH
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text(
        json.dumps(
            {
                "fetched_at": 1_000_000.0,
                "headlines": [
                    {
                        "headline": headline.headline,
                        "version": headline.version,
                    }
                    for headline in _fixture_headlines()
                ],
                "schema_version": 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(release_feed.time, "time", lambda: 1_000_000.0 + (23 * 60 * 60))

    def unexpected_fetch():
        raise AssertionError("fresh cache should prevent a network fetch")

    monkeypatch.setattr(release_feed, "_fetch_release_headlines", unexpected_fetch)

    assert release_feed.enrich_available_notice(
        tmp_path,
        installed_version="1.81.19",
        available_version="1.82.0",
        base_notice=BASE_NOTICE,
    ) == (
        f"{BASE_NOTICE}\n"
        "New since your version:\n"
        "• 💬 Found a bug? Dex reports it for you — and tells you when it's fixed\n"
        "Full story: https://heydex.ai/releases/"
    )


def test_network_failure_leaves_the_current_notice_byte_for_byte(tmp_path, monkeypatch):
    def fail_fetch():
        raise OSError("network unavailable")

    monkeypatch.setattr(release_feed, "_fetch_release_headlines", fail_fetch)

    assert (
        release_feed.enrich_available_notice(
            tmp_path,
            installed_version="1.81.19",
            available_version="1.82.0",
            base_notice=BASE_NOTICE,
        )
        == BASE_NOTICE
    )


def test_feed_parse_miss_leaves_the_current_notice_byte_for_byte(tmp_path, monkeypatch):
    monkeypatch.setattr(
        release_feed,
        "_fetch_release_headlines",
        lambda: release_feed.extract_release_headlines("# No release headings here"),
    )

    assert (
        release_feed.enrich_available_notice(
            tmp_path,
            installed_version="1.81.19",
            available_version="1.82.0",
            base_notice=BASE_NOTICE,
        )
        == BASE_NOTICE
    )


def test_empty_newer_range_leaves_the_current_notice_byte_for_byte(tmp_path, monkeypatch):
    monkeypatch.setattr(
        release_feed,
        "_fetch_release_headlines",
        lambda: (release_feed.ReleaseHeadline("1.81.19", "Already installed"),),
    )

    assert (
        release_feed.enrich_available_notice(
            tmp_path,
            installed_version="1.81.19",
            available_version="1.82.0",
            base_notice=BASE_NOTICE,
        )
        == BASE_NOTICE
    )


def test_hard_fetch_budget_fails_open_without_sleeping(tmp_path, monkeypatch):
    joined_for: list[float] = []

    class HungFetchThread:
        def start(self) -> None:
            pass

        def join(self, timeout: float) -> None:
            joined_for.append(timeout)

        def is_alive(self) -> bool:
            return True

    monkeypatch.setattr(release_feed, "_new_fetch_thread", lambda _target: HungFetchThread())

    assert (
        release_feed.enrich_available_notice(
            tmp_path,
            installed_version="1.81.19",
            available_version="1.82.0",
            base_notice=BASE_NOTICE,
        )
        == BASE_NOTICE
    )
    assert len(joined_for) == 1
    assert 0 < joined_for[0] <= 2.0


def test_debug_mode_reraises_feed_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("DEX_RELEASE_FEED_DEBUG", "1")
    monkeypatch.setattr(
        release_feed,
        "_fetch_release_headlines",
        lambda: (_ for _ in ()).throw(OSError("network unavailable")),
    )

    with pytest.raises(release_feed.ReleaseFeedError, match="release feed garnish failed"):
        release_feed.enrich_available_notice(
            tmp_path,
            installed_version="1.81.19",
            available_version="1.82.0",
            base_notice=BASE_NOTICE,
        )


def test_session_start_output_uses_the_release_feed_garnish(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        release_feed,
        "enrich_available_notice",
        lambda _vault, *, installed_version, available_version, base_notice: (
            f"{base_notice}\nNew since {installed_version}: {available_version}"
        ),
    )
    result = {
        "status": update_verifier.STATUS_RELEASE,
        "should_notify": True,
        "current_version": "1.81.19",
        "version": "1.82.0",
        "notice": BASE_NOTICE,
    }

    update_verifier._session_start_output(result, tmp_path)

    decoded = json.loads(capsys.readouterr().out)
    assert decoded["hookSpecificOutput"]["additionalContext"] == (
        f"\n{BASE_NOTICE}\nNew since 1.81.19: 1.82.0\n"
    )
