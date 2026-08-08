#!/usr/bin/env python3
"""Add public release headlines to an available-update session notice.

The garnish is fail-open: every feed, cache, or parsing failure returns the
caller's base notice unchanged. Set ``DEX_RELEASE_FEED_DEBUG=1`` to re-raise a
``ReleaseFeedError`` while developing or diagnosing the hook.
"""

from __future__ import annotations

import json
import os
import queue
import re
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

RELEASES_FEED_URL = "https://heydex.ai/releases/releases.md"
RELEASES_PAGE_URL = "https://heydex.ai/releases/"
CACHE_PATH = Path("System/.dex/releases-feed-cache.json")
CACHE_TTL_SECONDS = 24 * 60 * 60
# Leave scheduling margin while keeping the caller's hard total under 2 seconds.
FETCH_BUDGET_SECONDS = 1.9
MAX_FEED_BYTES = 1024 * 1024
MAX_HEADLINE_LENGTH = 500
MAX_HEADLINES_SHOWN = 3

_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_HEADING_RE = re.compile(
    r"^## \[(?P<version>\d+\.\d+\.\d+)\]\s+—\s*(?P<headline>.*?)\s*\(\d{4}-\d{2}-\d{2}\)\s*$",
    re.MULTILINE,
)


class ReleaseFeedError(RuntimeError):
    """The optional release-feed garnish could not be produced."""


class _FetchBudgetExceeded(RuntimeError):
    """The public feed did not finish inside its total wall-clock budget."""


@dataclass(frozen=True)
class ReleaseHeadline:
    version: str
    headline: str


def _version_key(version: str) -> tuple[int, int, int]:
    match = _SEMVER_RE.fullmatch(version)
    if match is None:
        raise ValueError("release feed version is not canonical semantic versioning")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _validated_headline(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("release headline is not a string")
    headline = value.strip()
    if (
        not headline
        or len(headline) > MAX_HEADLINE_LENGTH
        or any(ord(character) < 32 for character in headline)
    ):
        raise ValueError("release headline is empty or malformed")
    return headline


def _sorted_headlines(headlines: list[ReleaseHeadline]) -> tuple[ReleaseHeadline, ...]:
    seen_versions: set[str] = set()
    for headline in headlines:
        _version_key(headline.version)
        _validated_headline(headline.headline)
        if headline.version in seen_versions:
            raise ValueError("release feed contains a duplicate version")
        seen_versions.add(headline.version)
    return tuple(sorted(headlines, key=lambda item: _version_key(item.version), reverse=True))


def extract_release_headlines(markdown: str) -> tuple[ReleaseHeadline, ...]:
    """Extract and semantically order release heading headlines."""
    headlines = [
        ReleaseHeadline(match.group("version"), _validated_headline(match.group("headline")))
        for match in _HEADING_RE.finditer(markdown)
    ]
    if not headlines:
        raise ValueError("release feed contains no parseable headings")
    return _sorted_headlines(headlines)


def select_release_headlines(
    headlines: tuple[ReleaseHeadline, ...],
    *,
    installed_version: str,
    available_version: str,
) -> tuple[ReleaseHeadline, ...]:
    """Select entries after the install and no later than the proved candidate."""
    installed = _version_key(installed_version)
    available = _version_key(available_version)
    return tuple(
        headline
        for headline in _sorted_headlines(list(headlines))
        if installed < _version_key(headline.version) <= available
    )


def format_notice(base_notice: str, headlines: tuple[ReleaseHeadline, ...]) -> str:
    """Append up to three headline bullets and a public full-story link."""
    visible = headlines[:MAX_HEADLINES_SHOWN]
    lines = [base_notice, "New since your version:"]
    lines.extend(f"• {item.headline}" for item in visible)
    remaining = len(headlines) - len(visible)
    if remaining:
        lines.append(f"…and {remaining} more — full story: {RELEASES_PAGE_URL}")
    else:
        lines.append(f"Full story: {RELEASES_PAGE_URL}")
    return "\n".join(lines)


def _decode_cached_headlines(value: object) -> tuple[ReleaseHeadline, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("release feed cache contains no headlines")
    headlines: list[ReleaseHeadline] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"headline", "version"}:
            raise ValueError("release feed cache headline is malformed")
        version = item["version"]
        if not isinstance(version, str):
            raise ValueError("release feed cache version is malformed")
        headlines.append(ReleaseHeadline(version, _validated_headline(item["headline"])))
    return _sorted_headlines(headlines)


def _load_fresh_cache(vault: Path, now: float) -> tuple[ReleaseHeadline, ...] | None:
    path = vault / CACHE_PATH
    try:
        if path.stat().st_size > MAX_FEED_BYTES:
            return None
        cached = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(cached, dict) or cached.get("schema_version") != 1:
        return None
    fetched_at = cached.get("fetched_at")
    if isinstance(fetched_at, bool) or not isinstance(fetched_at, (int, float)):
        return None
    age = now - float(fetched_at)
    if age < 0 or age > CACHE_TTL_SECONDS:
        return None
    try:
        return _decode_cached_headlines(cached.get("headlines"))
    except ValueError:
        return None


def _write_cache(vault: Path, headlines: tuple[ReleaseHeadline, ...], fetched_at: float) -> None:
    path = vault / CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "fetched_at": fetched_at,
        "headlines": [
            {"headline": headline.headline, "version": headline.version}
            for headline in headlines
        ],
        "schema_version": 1,
    }
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _download_feed(deadline: float) -> str:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _FetchBudgetExceeded("release feed budget expired before the request")
    request = urllib.request.Request(
        RELEASES_FEED_URL,
        headers={"Accept": "text/markdown", "User-Agent": "Dex release awareness"},
    )
    with urllib.request.urlopen(request, timeout=remaining) as response:
        if getattr(response, "status", 200) != 200:
            raise OSError("release feed returned a non-success response")
        raw = response.read(MAX_FEED_BYTES + 1)
    if time.monotonic() >= deadline:
        raise _FetchBudgetExceeded("release feed exceeded its total wall-clock budget")
    if len(raw) > MAX_FEED_BYTES:
        raise ValueError("release feed exceeded its size bound")
    return raw.decode("utf-8")


def _new_fetch_thread(target: Callable[[], None]) -> threading.Thread:
    return threading.Thread(target=target, name="dex-release-feed", daemon=True)


def _fetch_release_headlines() -> tuple[ReleaseHeadline, ...]:
    deadline = time.monotonic() + FETCH_BUDGET_SECONDS
    outcome: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def fetch() -> None:
        try:
            outcome.put((True, _download_feed(deadline)))
        except Exception as error:
            outcome.put((False, error))

    thread = _new_fetch_thread(fetch)
    thread.start()
    thread.join(max(0.0, deadline - time.monotonic()))
    if thread.is_alive() or time.monotonic() >= deadline:
        raise _FetchBudgetExceeded("release feed exceeded its total wall-clock budget")
    try:
        succeeded, result = outcome.get_nowait()
    except queue.Empty as error:
        raise RuntimeError("release feed worker returned no result") from error
    if not succeeded:
        if isinstance(result, Exception):
            raise result
        raise RuntimeError("release feed worker returned an invalid failure")
    if not isinstance(result, str):
        raise RuntimeError("release feed worker returned an invalid response")
    return extract_release_headlines(result)


def _headlines(vault: Path) -> tuple[ReleaseHeadline, ...]:
    now = time.time()
    cached = _load_fresh_cache(vault, now)
    if cached is not None:
        return cached
    fetched = _fetch_release_headlines()
    _write_cache(vault, fetched, now)
    return fetched


def enrich_available_notice(
    vault: Path,
    *,
    installed_version: str,
    available_version: str,
    base_notice: str,
) -> str:
    """Return the garnished notice, or the exact base notice on any failure."""
    try:
        selected = select_release_headlines(
            _headlines(vault),
            installed_version=installed_version,
            available_version=available_version,
        )
        if not selected:
            raise ValueError("release feed has no headlines for the available update")
        return format_notice(base_notice, selected)
    except Exception as error:
        if os.environ.get("DEX_RELEASE_FEED_DEBUG") == "1":
            raise ReleaseFeedError("release feed garnish failed") from error
        return base_notice
