"""Tests for pure helpers in .scripts/email-triage-mcp/server.py.

business_days_since powers the unanswered-email detection behind /service-pulse
— overcounting flags healthy accounts, undercounting hides at-risk ones.
"""

from datetime import date, datetime, timedelta, timezone

from conftest import load_tool_module

triage = load_tool_module("email_triage_server", "email-triage-mcp/server.py")


# ---------------------------------------------------------------------------
# HTML stripping
# ---------------------------------------------------------------------------


def test_strip_html_removes_tags_and_collapses_whitespace():
    html = "<div><p>Hello <b>Chris</b>,</p>\n<p>Quote   attached.</p></div>"
    assert triage.strip_html(html) == "Hello Chris, Quote attached."


def test_strip_html_passes_plain_text_through():
    assert triage.strip_html("no tags here") == "no tags here"
    assert triage.strip_html("") == ""
    assert triage.strip_html(None) is None


def test_clean_email_strips_bodies_and_caps_full_body():
    row = {
        "subject": "RE: Quote",
        "body_preview": "<p>preview</p>",
        "full_body": "<div>" + ("long text " * 500) + "</div>",
    }
    cleaned = triage.clean_email(row)
    assert cleaned["body_preview"] == "preview"
    assert len(cleaned["full_body"]) <= 2000
    assert "<div>" not in cleaned["full_body"]
    # original dict untouched
    assert row["body_preview"] == "<p>preview</p>"


def test_clean_email_leaves_missing_fields_alone():
    assert triage.clean_email({"subject": "x"}) == {"subject": "x"}


# ---------------------------------------------------------------------------
# Business days since
# ---------------------------------------------------------------------------


def _expected_business_days(start: date, end: date) -> int:
    """Independent count using the module's own holiday table."""
    holidays = triage._us_federal_holidays(start.year) | triage._us_federal_holidays(end.year)
    d, count = start, 0
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in holidays:
            count += 1
    return count


def test_business_days_since_two_weeks_back():
    sent = datetime.now(timezone.utc) - timedelta(days=14)
    result = triage.business_days_since(sent.isoformat().replace("+00:00", "Z"))
    assert result == _expected_business_days(sent.date(), datetime.now(timezone.utc).date())
    assert 8 <= result <= 10  # 14 calendar days is always ~10 weekdays minus holidays


def test_business_days_since_today_is_zero():
    now = datetime.now(timezone.utc)
    assert triage.business_days_since(now.isoformat().replace("+00:00", "Z")) == 0


def test_business_days_since_invalid_input_returns_zero():
    assert triage.business_days_since(None) == 0
    assert triage.business_days_since("not-a-timestamp") == 0
    assert triage.business_days_since("") == 0
