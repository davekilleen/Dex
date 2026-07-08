"""Date-accuracy coverage for core.utils.timezone.

CLAUDE.md's Date Accuracy Protocol treats wrong-day output as a critical
failure mode; these tests pin the timezone resolution chain that every
_tz_now()/_tz_today() call in the MCP servers depends on.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from core.utils import timezone as tz_module


@pytest.fixture(autouse=True)
def reset_timezone_cache():
    """Each test starts with a cold cache and restores it afterwards."""
    tz_module._cached_tz = None
    tz_module._cache_loaded = False
    yield
    tz_module._cached_tz = None
    tz_module._cache_loaded = False


def _write_profile(vault, content: str) -> None:
    (vault / "System").mkdir(parents=True, exist_ok=True)
    (vault / "System" / "user-profile.yaml").write_text(content)


def test_configured_timezone_is_used(tmp_path, monkeypatch):
    _write_profile(tmp_path, "timezone: Pacific/Kiritimati\n")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert tz_module.get_user_timezone() == ZoneInfo("Pacific/Kiritimati")
    assert tz_module.now().tzinfo == ZoneInfo("Pacific/Kiritimati")


def test_missing_profile_falls_back_to_system_local(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert tz_module.get_user_timezone() is None
    result = tz_module.now()
    assert result.tzinfo is not None
    assert abs(result - datetime.now().astimezone()) < timedelta(seconds=5)


def test_profile_without_timezone_key_falls_back(tmp_path, monkeypatch):
    _write_profile(tmp_path, "name: Test User\n")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert tz_module.get_user_timezone() is None


def test_invalid_timezone_string_falls_back(tmp_path, monkeypatch):
    _write_profile(tmp_path, "timezone: Not/A_Real_Zone\n")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert tz_module.get_user_timezone() is None
    assert tz_module.now().tzinfo is not None


def test_malformed_yaml_falls_back(tmp_path, monkeypatch):
    _write_profile(tmp_path, "timezone: [unclosed\n")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert tz_module.get_user_timezone() is None


def test_today_matches_date_in_configured_zone(tmp_path, monkeypatch):
    # Kiritimati (UTC+14) and Samoa (UTC-11) straddle the dateline; today()
    # must reflect the configured zone, not the machine's.
    _write_profile(tmp_path, "timezone: Pacific/Kiritimati\n")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    expected = datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
    assert tz_module.today() == expected


def test_timezone_is_cached_after_first_load(tmp_path, monkeypatch):
    _write_profile(tmp_path, "timezone: America/New_York\n")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    assert tz_module.get_user_timezone() == ZoneInfo("America/New_York")

    # Changing the profile after the first load must not change the answer
    _write_profile(tmp_path, "timezone: Asia/Tokyo\n")
    assert tz_module.get_user_timezone() == ZoneInfo("America/New_York")


def test_detect_system_timezone_returns_valid_iana_or_empty():
    detected = tz_module.detect_system_timezone()
    if detected:
        ZoneInfo(detected)  # raises if not a valid IANA name
