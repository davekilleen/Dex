#!/bin/bash
# Create a calendar event
# Usage: calendar_create_event.sh <calendar_name> <title> <start_datetime> <duration_minutes> [description] [location]

CALENDAR_NAME="$1"
TITLE="$2"
START_DATETIME="$3"  # Format: "YYYY-MM-DD HH:MM"
DURATION_MINUTES="${4:-30}"
DESCRIPTION="${5:-}"
LOCATION="${6:-}"

# Parse the datetime
YEAR=$(echo "$START_DATETIME" | cut -d'-' -f1)
MONTH=$(echo "$START_DATETIME" | cut -d'-' -f2)
DAY=$(echo "$START_DATETIME" | cut -d'-' -f3 | cut -d' ' -f1)
HOUR=$(echo "$START_DATETIME" | cut -d' ' -f2 | cut -d':' -f1)
MINUTE=$(echo "$START_DATETIME" | cut -d':' -f2)

osascript << EOF
tell application "Calendar"
    set targetCal to calendar "$CALENDAR_NAME"
    
    -- Build the date
    set startDate to current date
    set year of startDate to $YEAR
    set month of startDate to $MONTH
    set day of startDate to $DAY
    set hours of startDate to $HOUR
    set minutes of startDate to $MINUTE
    set seconds of startDate to 0
    
    set endDate to startDate + ($DURATION_MINUTES * minutes)
    
    set eventProps to {summary:"$TITLE", start date:startDate, end date:endDate}
    
    set newEvent to make new event at end of events of targetCal with properties eventProps
    
    -- Add optional properties
    if "$DESCRIPTION" is not "" then
        set description of newEvent to "$DESCRIPTION"
    end if
    
    if "$LOCATION" is not "" then
        set location of newEvent to "$LOCATION"
    end if
    
    return "Created: " & (summary of newEvent) & " at " & (start date of newEvent as string)
end tell
EOF
