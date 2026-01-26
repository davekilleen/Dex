#!/bin/bash
# Search calendar events by title
# Usage: calendar_search.sh <calendar_name> <query> <days_back> <days_forward>

CALENDAR_NAME="$1"
QUERY="$2"
DAYS_BACK="${3:-30}"
DAYS_FORWARD="${4:-30}"

osascript << EOF
tell application "Calendar"
    set targetCal to calendar "$CALENDAR_NAME"
    set today to current date
    set hours of today to 0
    set minutes of today to 0
    set seconds of today to 0
    set startDate to today - ($DAYS_BACK * days)
    set endDate to today + ($DAYS_FORWARD * days)
    
    set allEvents to (every event of targetCal whose start date >= startDate and start date <= endDate)
    set matchingEvents to {}
    
    repeat with e in allEvents
        set eventTitle to summary of e
        if eventTitle contains "$QUERY" then
            set eventInfo to "TITLE:" & eventTitle & "|START:" & (start date of e as string) & "|END:" & (end date of e as string)
            set end of matchingEvents to eventInfo
        end if
    end repeat
    
    set AppleScript's text item delimiters to "
"
    return matchingEvents as string
end tell
EOF
