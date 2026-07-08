"""Tests for the pure business logic in .scripts/salesforce-mcp/server.py.

These helpers drive real sales decisions: task due dates (business-day math),
lease-expiry urgency (the Q4 "clear all CRITICAL/HIGH" goal), and the 54/60-month
replacement window behind replacement-due outreach.
"""

from datetime import date, timedelta

import pytest
from conftest import load_tool_module

sf = load_tool_module("salesforce_mcp_server", "salesforce-mcp/server.py")


# ---------------------------------------------------------------------------
# US federal holidays / business days
# ---------------------------------------------------------------------------


def test_us_federal_holidays_2026_known_dates():
    holidays = sf._us_federal_holidays(2026)
    assert date(2026, 1, 1) in holidays        # New Year's (Thursday)
    assert date(2026, 1, 19) in holidays       # MLK Day (3rd Monday)
    assert date(2026, 5, 25) in holidays       # Memorial Day (last Monday of May)
    assert date(2026, 6, 19) in holidays       # Juneteenth (Friday)
    assert date(2026, 7, 3) in holidays        # July 4 falls on Saturday -> observed Friday
    assert date(2026, 7, 4) not in holidays
    assert date(2026, 11, 26) in holidays      # Thanksgiving (4th Thursday)
    assert date(2026, 12, 25) in holidays      # Christmas (Friday)
    assert len(holidays) == 11


def test_next_business_day_weekend_rolls_to_monday():
    saturday = date(2026, 7, 11)
    sunday = date(2026, 7, 12)
    assert sf.next_business_day(saturday) == date(2026, 7, 13)
    assert sf.next_business_day(sunday) == date(2026, 7, 13)


def test_next_business_day_skips_observed_holiday():
    # Friday 2026-07-03 is the observed Independence Day -> lands Monday 07-06
    assert sf.next_business_day(date(2026, 7, 3)) == date(2026, 7, 6)


def test_next_business_day_keeps_regular_weekday():
    wednesday = date(2026, 7, 8)
    assert sf.next_business_day(wednesday) == wednesday


def test_next_business_day_year_boundary():
    # Thu Dec 31 2027 -> Fri Jan 1 2028 is a holiday? 2028-01-01 is Saturday,
    # observed Friday 2027-12-31. So Dec 31 2027 itself is a holiday -> advance.
    result = sf.next_business_day(date(2027, 12, 31))
    assert result.weekday() < 5
    assert result not in sf._us_federal_holidays(result.year)
    assert result > date(2027, 12, 30)


# ---------------------------------------------------------------------------
# Asset lease-expiry urgency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "days_out,expected",
    [
        (-5, "LAPSED"),
        (0, "LAPSED"),
        (30, "CRITICAL"),
        (90, "CRITICAL"),
        (91, "HIGH"),
        (180, "HIGH"),
        (181, "MEDIUM"),
        (365, "MEDIUM"),
        (366, "LOW"),
    ],
)
def test_asset_expiry_status_buckets(days_out, expected):
    end = (date.today() + timedelta(days=days_out)).isoformat()
    days, urgency = sf._asset_expiry_status(end)
    assert days == days_out
    assert urgency == expected


def test_asset_expiry_status_handles_missing_and_garbage():
    assert sf._asset_expiry_status(None) == (None, None)
    assert sf._asset_expiry_status("") == (None, None)
    assert sf._asset_expiry_status("not-a-date") == (None, None)


def test_asset_expiry_accepts_datetime_strings():
    end = (date.today() + timedelta(days=60)).isoformat() + "T00:00:00.000+0000"
    days, urgency = sf._asset_expiry_status(end)
    assert days == 60
    assert urgency == "CRITICAL"


# ---------------------------------------------------------------------------
# Asset record parsing
# ---------------------------------------------------------------------------


def test_parse_asset_record_full():
    end = (date.today() + timedelta(days=45)).isoformat()
    record = {
        "Id": "02iXXX",
        "Name": "TruLaser 3030",
        "Machine_Type_New__c": "Laser",
        "ModelName__c": "TruLaser 3030",
        "Builder__c": "TRUMPF",
        "SerialNumber": "SN-123",
        "UsageEndDate": end,
        "Sale_or_Lease__c": "Lease",
        "IsCompetitorProduct": True,
        "Account": {"Id": "001YYY", "Name": "Acme Corp"},
        "Contact": {"Name": "Jane Roe"},
    }

    parsed = sf._parse_asset_record(record)

    assert parsed["id"] == "02iXXX"
    assert parsed["machine_type"] == "Laser"
    assert parsed["builder"] == "TRUMPF"
    assert parsed["days_to_expiry"] == 45
    assert parsed["urgency"] == "CRITICAL"
    assert parsed["is_competitor"] is True
    assert parsed["account"] == "Acme Corp"
    assert parsed["account_id"] == "001YYY"
    assert parsed["contact"] == "Jane Roe"


def test_parse_asset_record_minimal():
    parsed = sf._parse_asset_record({"Id": "02iZZZ"})
    assert parsed["id"] == "02iZZZ"
    assert parsed["urgency"] is None
    assert parsed["account"] is None
    assert parsed["is_competitor"] is False


# ---------------------------------------------------------------------------
# 54/60-month replacement window
# ---------------------------------------------------------------------------


def _months_ago(n: int) -> str:
    """First-of-month date exactly n calendar months before today."""
    today = date.today()
    total = today.year * 12 + (today.month - 1) - n
    return date(total // 12, total % 12 + 1, 1).isoformat()


def test_replacement_window_past_60_months_is_past_window():
    win = sf._replacement_window(_months_ago(62))
    assert win["status"] == "PAST_WINDOW"
    assert win["urgency"] == "CRITICAL"
    assert win["months_elapsed"] >= 60


def test_replacement_window_between_54_and_60_is_in_window():
    win = sf._replacement_window(_months_ago(56))
    assert win["status"] == "IN_WINDOW"
    assert win["urgency"] == "CRITICAL"


def test_replacement_window_upcoming_and_active():
    upcoming = sf._replacement_window(_months_ago(50))
    assert upcoming["status"] in ("UPCOMING", "APPROACHING")
    assert upcoming["urgency"] in ("MEDIUM", "HIGH")

    active = sf._replacement_window(_months_ago(24))
    assert active["status"] == "ACTIVE"
    assert active["urgency"] == "LOW"


def test_replacement_window_dates_are_consistent():
    close = _months_ago(30)
    win = sf._replacement_window(close)
    close_d = date.fromisoformat(close)
    assert win["early_end_date"] == (close_d + timedelta(days=54 * 30)).isoformat()
    assert win["std_end_date"] == (close_d + timedelta(days=60 * 30)).isoformat()
    assert win["days_to_std_end"] == (close_d + timedelta(days=60 * 30) - date.today()).days


def test_replacement_window_invalid_input():
    assert sf._replacement_window(None) is None
    assert sf._replacement_window("garbage") is None
