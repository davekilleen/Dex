#!/bin/bash
# Calendar helper script - gets events with attendee details
# Usage: calendar_get_events_with_attendees.sh <calendar_name> <days_offset_start> <days_offset_end>

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
        set eventInfo to "TITLE:" & (summary of e)
        set eventInfo to eventInfo & "|START:" & (start date of e as string)
        set eventInfo to eventInfo & "|END:" & (end date of e as string)
        
        -- Get location
        try
            set loc to location of e
            if loc is not missing value then
                set eventInfo to eventInfo & "|LOC:" & loc
            end if
        end try
        
        -- Get attendees with full details
        try
            set attendeeList to every attendee of e
            set attendeeData to {}
            repeat with a in attendeeList
                set aName to display name of a
                set aEmail to email of a
                set aStatus to participation status of a as string
                -- Format: name<email>[status]
                set end of attendeeData to aName & "<" & aEmail & ">[" & aStatus & "]"
            end repeat
            set AppleScript's text item delimiters to ";"
            set eventInfo to eventInfo & "|ATTENDEES:" & (attendeeData as string)
        on error
            set eventInfo to eventInfo & "|ATTENDEES:"
        end try
        
        -- Get organizer
        try
            set org to organizer of e
            if org is not missing value then
                set eventInfo to eventInfo & "|ORGANIZER:" & (email of org)
            end if
        end try
        
        set end of eventList to eventInfo
    end repeat
    
    set AppleScript's text item delimiters to "
"
    return eventList as string
end tell
EOF
