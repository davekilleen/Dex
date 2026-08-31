"""Regression: calendar events must not land a month late at month end.

calendar_create_event.sh builds its start date by mutating `current date`.
AppleScript dates overflow rather than clamp, so setting the month while the day
is still today's can roll past the month asked for: on the 31st, setting the
month to September gives 1 October, and the following `set day` lands in
October. Asked for 2026-09-02 on 31 August, the event was created on 2 October,
and the call still reported success.

The fix is ordering: set the day to 1 before the year and month, so the later
`set day` has a month that can hold it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "core" / "mcp" / "scripts" / "calendar_create_event.sh"


def test_day_is_reset_before_the_month_is_set():
    """The ordering is the fix. Without the reset, a month-end run overflows."""
    body = SCRIPT.read_text()
    assert "set day of startDate to 1\n" in body, (
        "the day is never reset to 1 before the month is set, so a run on the "
        "29th to 31st will create the event in the month after the one asked for"
    )
    reset = body.index("set day of startDate to 1\n")
    month = body.index("set month of startDate to")
    day = body.index("set day of startDate to $DAY")
    assert reset < month, (
        "the day must be reset to 1 before the month is set, or a run on the "
        "29th to 31st rolls into the month after the one requested"
    )
    assert month < day, "the real day must be set after the month"


@pytest.mark.skipif(sys.platform != "darwin", reason="AppleScript is macOS only")
def test_applescript_overflows_without_the_reset():
    """Prove the mechanic the ordering defends against, so the guard above is
    not mistaken for style."""
    script = """
    set d to current date
    set day of d to 31
    set year of d to 2026
    set month of d to September
    return month of d as string
    """
    out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "October", (
        "AppleScript no longer overflows when the day exceeds the target month; "
        "if so, this guard can be relaxed"
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="AppleScript is macOS only")
def test_reset_prevents_the_overflow():
    script = """
    set d to current date
    set day of d to 31
    set day of d to 1
    set year of d to 2026
    set month of d to September
    set day of d to 2
    return (month of d as string) & " " & (day of d as string)
    """
    out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "September 2"
