#!/bin/bash
# Calendar helper script - runs AppleScript for calendar queries
# Usage: calendar_get_events.sh <calendar_name> <days_offset_start> <days_offset_end>

CALENDAR_NAME="${1:-Calendar}"
START_OFFSET="${2:-0}"
END_OFFSET="${3:-1}"

osascript << EOF
tell application "Calendar"
    set targetCal to calendar "$CALENDAR_NAME"
    set today to current date
    set hours of today to 0
    set minutes of today to 0
    set seconds of today to 0
    set startDate to today + ($START_OFFSET * days)
    set endDate to today + ($END_OFFSET * days)
    
    set matchingEvents to (every event of targetCal whose start date >= startDate and start date < endDate)
    set eventList to {}
    
    repeat with e in matchingEvents
        set eventInfo to "TITLE:" & (summary of e) & "|START:" & (start date of e as string) & "|END:" & (end date of e as string)
        try
            set eventInfo to eventInfo & "|LOC:" & (location of e)
        end try
        set end of eventList to eventInfo
    end repeat
    
    set AppleScript's text item delimiters to "
"
    return eventList as string
end tell
EOF
