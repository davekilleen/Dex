from datetime import datetime

from core.utils.flexible_datetime import parse_flexible_datetime


def test_parse_flexible_datetime_accepts_date_only() -> None:
    assert parse_flexible_datetime("2026-08-27") == datetime(2026, 8, 27)


def test_parse_flexible_datetime_accepts_trailing_z() -> None:
    parsed = parse_flexible_datetime("2026-08-27T10:30:00Z")
    assert parsed.year == 2026
    assert parsed.hour == 10
