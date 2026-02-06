#!/usr/bin/env python3
"""
Fast calendar queries using native EventKit framework.
Replaces slow AppleScript queries with proper database access.

Performance: 30s → <1s for typical queries

Usage:
    calendar_eventkit.py list
    calendar_eventkit.py events <calendar_name> <start_offset> <end_offset>
    calendar_eventkit.py search <calendar_name> <query> <days_back> <days_forward>
    calendar_eventkit.py next <calendar_name>
    calendar_eventkit.py attendees <calendar_name> <start_offset> <end_offset>
"""

import sys
import json
from datetime import datetime, timedelta
import EventKit


def list_calendars():
    """List all available calendars."""
    store = EventKit.EKEventStore.alloc().init()
    calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)
    
    result = []
    for cal in calendars:
        result.append({
            "title": cal.title(),
            "type": cal.type(),
            "color": str(cal.color()) if cal.color() else None,
            "identifier": cal.calendarIdentifier()
        })
    
    print(json.dumps(result, indent=2))


def find_calendar(store, calendar_name: str):
    """Find a calendar by name or identifier."""
    calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)
    
    for cal in calendars:
        if cal.title() == calendar_name or cal.calendarIdentifier() == calendar_name:
            return cal
    
    return None


def format_event(event) -> dict:
    """Format an EKEvent into a consistent dict structure."""
    return {
        "title": event.title() or "",
        "start": event.startDate().description(),
        "end": event.endDate().description(),
        "location": event.location() or "",
        "url": event.URL().absoluteString() if event.URL() else "",
        "notes": event.notes() or "",
        "all_day": event.isAllDay()
    }


def format_event_with_attendees(event) -> dict:
    """Format an EKEvent with full attendee details."""
    event_data = format_event(event)
    
    # Add attendees
    attendees = []
    if event.attendees():
        for attendee in event.attendees():
            att_data = {
                "name": attendee.name() or "",
                "email": attendee.emailAddress() or "",
                "status": {
                    0: "Unknown",
                    1: "Pending",
                    2: "Accepted",
                    3: "Declined",
                    4: "Tentative",
                    5: "Delegated",
                    6: "Completed",
                    7: "In Process"
                }.get(attendee.participantStatus(), "Unknown"),
                "type": {
                    0: "Unknown",
                    1: "Person",
                    2: "Room",
                    3: "Resource",
                    4: "Group"
                }.get(attendee.participantType(), "Unknown"),
                "is_organizer": attendee.isCurrentUser()
            }
            attendees.append(att_data)
    
    event_data["attendees"] = attendees
    return event_data


def get_events(calendar_name: str, start_offset_days: int, end_offset_days: int, with_attendees: bool = False):
    """Get events for a date range.
    
    Args:
        calendar_name: Calendar name or email
        start_offset_days: Days offset from today (0 = today)
        end_offset_days: Days offset from today (1 = tomorrow)
        with_attendees: Include full attendee details
    """
    store = EventKit.EKEventStore.alloc().init()
    
    # Find the calendar
    target_calendar = find_calendar(store, calendar_name)
    if not target_calendar:
        print(json.dumps({"error": f"Calendar not found: {calendar_name}"}))
        sys.exit(1)
    
    # Calculate date range
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = today + timedelta(days=start_offset_days)
    end_date = today + timedelta(days=end_offset_days)
    
    # Create predicate for date range (database query - FAST!)
    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        start_date,
        end_date,
        [target_calendar]
    )
    
    # Fetch events
    events = store.eventsMatchingPredicate_(predicate)
    
    # Format output
    result = []
    for event in events:
        if with_attendees:
            result.append(format_event_with_attendees(event))
        else:
            result.append(format_event(event))
    
    # Sort by start time
    result.sort(key=lambda x: x["start"])
    
    print(json.dumps(result, indent=2))


def search_events(calendar_name: str, query: str, days_back: int, days_forward: int):
    """Search for events by title.
    
    Args:
        calendar_name: Calendar name
        query: Search term (case-insensitive)
        days_back: How many days back to search
        days_forward: How many days forward to search
    """
    store = EventKit.EKEventStore.alloc().init()
    
    # Find the calendar
    target_calendar = find_calendar(store, calendar_name)
    if not target_calendar:
        print(json.dumps({"error": f"Calendar not found: {calendar_name}"}))
        sys.exit(1)
    
    # Calculate date range
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = today - timedelta(days=days_back)
    end_date = today + timedelta(days=days_forward)
    
    # Create predicate
    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        start_date,
        end_date,
        [target_calendar]
    )
    
    # Fetch and filter events
    events = store.eventsMatchingPredicate_(predicate)
    query_lower = query.lower()
    
    matching_events = []
    for event in events:
        if query_lower in (event.title() or "").lower():
            matching_events.append(format_event(event))
    
    # Sort by start time
    matching_events.sort(key=lambda x: x["start"])
    
    print(json.dumps(matching_events, indent=2))


def get_next_event(calendar_name: str):
    """Get the next upcoming event from now.
    
    Args:
        calendar_name: Calendar name
    """
    store = EventKit.EKEventStore.alloc().init()
    
    # Find the calendar
    target_calendar = find_calendar(store, calendar_name)
    if not target_calendar:
        print(json.dumps({"error": f"Calendar not found: {calendar_name}"}))
        sys.exit(1)
    
    # Search from now to 90 days out
    now = datetime.now()
    end_date = now + timedelta(days=90)
    
    # Create predicate
    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        now,
        end_date,
        [target_calendar]
    )
    
    # Fetch events
    events = store.eventsMatchingPredicate_(predicate)
    
    if not events or len(events) == 0:
        print(json.dumps({"message": "No upcoming events found"}))
        return
    
    # Get the earliest event
    # Convert to list and sort by start date
    events_list = list(events)
    events_list.sort(key=lambda e: e.startDate())
    
    next_event = events_list[0]
    
    print(json.dumps(format_event(next_event), indent=2))


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  calendar_eventkit.py list")
        print("  calendar_eventkit.py events <calendar> <start_offset> <end_offset>")
        print("  calendar_eventkit.py search <calendar> <query> <days_back> <days_forward>")
        print("  calendar_eventkit.py next <calendar>")
        print("  calendar_eventkit.py attendees <calendar> <start_offset> <end_offset>")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "list":
        list_calendars()
    
    elif command == "events":
        if len(sys.argv) != 5:
            print("Usage: calendar_eventkit.py events <calendar> <start_offset> <end_offset>")
            sys.exit(1)
        calendar_name = sys.argv[2]
        start_offset = int(sys.argv[3])
        end_offset = int(sys.argv[4])
        get_events(calendar_name, start_offset, end_offset)
    
    elif command == "search":
        if len(sys.argv) != 6:
            print("Usage: calendar_eventkit.py search <calendar> <query> <days_back> <days_forward>")
            sys.exit(1)
        calendar_name = sys.argv[2]
        query = sys.argv[3]
        days_back = int(sys.argv[4])
        days_forward = int(sys.argv[5])
        search_events(calendar_name, query, days_back, days_forward)
    
    elif command == "next":
        if len(sys.argv) != 3:
            print("Usage: calendar_eventkit.py next <calendar>")
            sys.exit(1)
        calendar_name = sys.argv[2]
        get_next_event(calendar_name)
    
    elif command == "attendees":
        if len(sys.argv) != 5:
            print("Usage: calendar_eventkit.py attendees <calendar> <start_offset> <end_offset>")
            sys.exit(1)
        calendar_name = sys.argv[2]
        start_offset = int(sys.argv[3])
        end_offset = int(sys.argv[4])
        get_events(calendar_name, start_offset, end_offset, with_attendees=True)
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
