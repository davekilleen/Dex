#!/bin/bash
# Get the next upcoming event
# Usage: calendar_next_event.sh <calendar_name>

CALENDAR_NAME="${1:-Calendar}"

osascript << EOF
tell application "Calendar"
    set targetCal to calendar "$CALENDAR_NAME"
    set rightNow to current date
    set tomorrow to rightNow + (1 * days)
    
    set upcomingEvents to (every event of targetCal whose start date >= rightNow and start date <= tomorrow)
    
    if (count of upcomingEvents) > 0 then
        set nextEvent to item 1 of upcomingEvents
        repeat with e in upcomingEvents
            if (start date of e) < (start date of nextEvent) and (start date of e) >= rightNow then
                set nextEvent to e
            end if
        end repeat
        
        return "TITLE:" & (summary of nextEvent) & "|START:" & (start date of nextEvent as string) & "|END:" & (end date of nextEvent as string)
    else
        return "No upcoming events in the next 24 hours"
    end if
end tell
EOF
