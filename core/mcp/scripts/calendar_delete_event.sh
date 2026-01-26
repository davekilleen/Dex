#!/bin/bash
# Delete a calendar event by title and date
# Usage: calendar_delete_event.sh <calendar_name> <title> <day_offset>

CALENDAR_NAME="$1"
TITLE="$2"
DAY_OFFSET="${3:-0}"

osascript << EOF
tell application "Calendar"
    set targetCal to calendar "$CALENDAR_NAME"
    set today to current date
    set hours of today to 0
    set minutes of today to 0
    set seconds of today to 0
    set targetDate to today + ($DAY_OFFSET * days)
    set endDate to targetDate + (1 * days)
    
    set matchingEvents to (every event of targetCal whose summary is "$TITLE" and start date >= targetDate and start date < endDate)
    
    if (count of matchingEvents) > 0 then
        delete (item 1 of matchingEvents)
        return "Deleted event: $TITLE"
    else
        return "No event found matching: $TITLE"
    end if
end tell
EOF
