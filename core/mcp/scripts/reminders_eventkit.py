#!/usr/bin/env python3
"""
Apple Reminders access using native EventKit framework.
Companion to calendar_eventkit.py — same framework, different entity type.

Usage:
    reminders_eventkit.py list_lists
    reminders_eventkit.py list_items <list_name>
    reminders_eventkit.py list_completed <list_name>
    reminders_eventkit.py complete <reminder_id>
    reminders_eventkit.py create <list_name> <title> [notes] [due_date]
    reminders_eventkit.py find_and_complete <list_name> <title_query>
    reminders_eventkit.py clear_completed <list_name>
    reminders_eventkit.py ensure_lists
"""

import sys
import json
import time
from datetime import datetime, timedelta
import EventKit
from Foundation import NSDate, NSRunLoop


def get_store():
    """Get an authorized EKEventStore for Reminders."""
    store = EventKit.EKEventStore.alloc().init()
    return store


def find_reminder_list(store, list_name: str):
    """Find a Reminders list (calendar) by name."""
    calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)
    for cal in calendars:
        if cal.title() == list_name:
            return cal
    return None


def list_lists():
    """List all Reminders lists."""
    store = get_store()
    calendars = store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)

    result = []
    for cal in calendars:
        result.append({
            "title": cal.title(),
            "identifier": cal.calendarIdentifier(),
            "color": str(cal.color()) if cal.color() else None,
        })

    print(json.dumps(result, indent=2))


def fetch_reminders_sync(store, predicate):
    """Fetch reminders synchronously using a run loop.

    EventKit's fetchRemindersMatchingPredicate is async — we spin the
    run loop until the completion handler fires.
    """
    results = [None]
    done = [False]

    def completion(reminders):
        results[0] = reminders
        done[0] = True

    store.fetchRemindersMatchingPredicate_completion_(predicate, completion)

    # Spin run loop until callback fires (max 10 seconds)
    deadline = time.time() + 10
    while not done[0] and time.time() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.05)
        )

    return results[0] or []


def list_items(list_name: str):
    """Get incomplete reminders from a specific list."""
    store = get_store()
    target = find_reminder_list(store, list_name)

    if not target:
        print(json.dumps({"error": f"Reminders list not found: {list_name}"}))
        sys.exit(1)

    # Predicate for incomplete reminders in this list
    predicate = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
        None,  # no start date filter
        None,  # no end date filter
        [target],
    )

    reminders = fetch_reminders_sync(store, predicate)

    result = []
    for rem in reminders:
        item = {
            "title": rem.title() or "",
            "notes": rem.notes() or "",
            "reminder_id": rem.calendarItemIdentifier() or "",
            "creation_date": rem.creationDate().description() if rem.creationDate() else "",
            "completed": bool(rem.isCompleted()),
        }
        if rem.dueDateComponents():
            dc = rem.dueDateComponents()
            try:
                item["due_date"] = f"{dc.year():04d}-{dc.month():02d}-{dc.day():02d}"
            except Exception:
                item["due_date"] = ""
        else:
            item["due_date"] = ""
        result.append(item)

    # Sort by creation date (newest first)
    result.sort(key=lambda x: x.get("creation_date", ""), reverse=True)

    print(json.dumps(result, indent=2))


def complete_item(reminder_id: str):
    """Mark a reminder as complete by its calendarItemIdentifier."""
    store = get_store()

    # Fetch all incomplete reminders across all lists to find the one
    predicate = store.predicateForRemindersInCalendars_(None)
    reminders = fetch_reminders_sync(store, predicate)

    target_reminder = None
    for rem in reminders:
        if rem.calendarItemIdentifier() == reminder_id:
            target_reminder = rem
            break

    if not target_reminder:
        print(json.dumps({"error": f"Reminder not found: {reminder_id}"}))
        sys.exit(1)

    target_reminder.setCompleted_(True)
    target_reminder.setCompletionDate_(NSDate.date())

    error = None
    success = store.saveReminder_commit_error_(target_reminder, True, error)

    if success:
        print(json.dumps({"success": True, "reminder_id": reminder_id, "status": "completed"}))
    else:
        print(json.dumps({"error": f"Failed to save reminder: {error}"}))
        sys.exit(1)


def create_item(list_name: str, title: str, notes: str = "", due_date: str = ""):
    """Create a new reminder in the specified list."""
    store = get_store()
    target = find_reminder_list(store, list_name)

    if not target:
        print(json.dumps({"error": f"Reminders list not found: {list_name}. Run 'ensure_lists' first."}))
        sys.exit(1)

    reminder = EventKit.EKReminder.reminderWithEventStore_(store)
    reminder.setTitle_(title)
    reminder.setCalendar_(target)

    if notes:
        reminder.setNotes_(notes)

    if due_date:
        try:
            dt = datetime.strptime(due_date, "%Y-%m-%d")
            components = EventKit.NSDateComponents.alloc().init()
            components.setYear_(dt.year)
            components.setMonth_(dt.month)
            components.setDay_(dt.day)
            components.setHour_(9)  # Default 9am
            components.setMinute_(0)
            reminder.setDueDateComponents_(components)
        except ValueError:
            pass  # Skip invalid date, create without due date

    error = None
    success = store.saveReminder_commit_error_(reminder, True, error)

    if success:
        print(json.dumps({
            "success": True,
            "reminder_id": reminder.calendarItemIdentifier(),
            "title": title,
            "list": list_name,
        }))
    else:
        print(json.dumps({"error": f"Failed to create reminder: {error}"}))
        sys.exit(1)


def list_completed_items(list_name: str):
    """Get completed reminders from a specific list (for sync checking).

    Used to detect items the user marked done on their phone so Dex can
    sync the completion back to Tasks.md.
    """
    store = get_store()
    target = find_reminder_list(store, list_name)

    if not target:
        print(json.dumps({"error": f"Reminders list not found: {list_name}"}))
        sys.exit(1)

    predicate = store.predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars_(
        NSDate.dateWithTimeIntervalSinceNow_(-86400 * 2),  # last 2 days
        NSDate.date(),
        [target],
    )

    reminders = fetch_reminders_sync(store, predicate)

    result = []
    for rem in reminders:
        item = {
            "title": rem.title() or "",
            "notes": rem.notes() or "",
            "reminder_id": rem.calendarItemIdentifier() or "",
            "completed": True,
            "completion_date": rem.completionDate().description() if rem.completionDate() else "",
        }
        result.append(item)

    print(json.dumps(result, indent=2))


def find_and_complete(list_name: str, title_query: str):
    """Find a reminder by title match and mark it complete.

    Used for Dex → Reminders sync: when a task is marked done in Dex,
    clear the matching Reminder in 'Dex Today' to prevent stale notifications.
    """
    store = get_store()
    target = find_reminder_list(store, list_name)

    if not target:
        print(json.dumps({"error": f"Reminders list not found: {list_name}"}))
        sys.exit(1)

    predicate = store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
        None, None, [target],
    )
    reminders = fetch_reminders_sync(store, predicate)

    query_lower = title_query.lower()
    matched = None
    for rem in reminders:
        rem_title = (rem.title() or "").lower()
        if query_lower in rem_title or rem_title in query_lower:
            matched = rem
            break

    if not matched:
        print(json.dumps({"found": False, "message": f"No matching reminder for: {title_query}"}))
        return

    matched.setCompleted_(True)
    matched.setCompletionDate_(NSDate.date())

    error = None
    success = store.saveReminder_commit_error_(matched, True, error)

    if success:
        print(json.dumps({
            "found": True,
            "completed": True,
            "reminder_id": matched.calendarItemIdentifier(),
            "title": matched.title(),
        }))
    else:
        print(json.dumps({"error": f"Failed to save: {error}"}))
        sys.exit(1)


def clear_completed(list_name: str):
    """Remove all completed reminders from a list.

    Used to clean up 'Dex Today' at the start of a new day so yesterday's
    completed items don't clutter the list.
    """
    store = get_store()
    target = find_reminder_list(store, list_name)

    if not target:
        print(json.dumps({"error": f"Reminders list not found: {list_name}"}))
        sys.exit(1)

    predicate = store.predicateForCompletedRemindersWithCompletionDateStarting_ending_calendars_(
        NSDate.dateWithTimeIntervalSinceNow_(-86400 * 7),  # last 7 days
        NSDate.date(),
        [target],
    )
    reminders = fetch_reminders_sync(store, predicate)

    removed = 0
    for rem in reminders:
        error = None
        success = store.removeReminder_commit_error_(rem, True, error)
        if success:
            removed += 1

    print(json.dumps({"success": True, "removed": removed, "list": list_name}))


def ensure_lists():
    """Create 'Dex Inbox' and 'Dex Today' lists if they don't exist."""
    store = get_store()
    created = []
    existing = []

    for list_name in ["Dex Inbox", "Dex Today"]:
        if find_reminder_list(store, list_name):
            existing.append(list_name)
            continue

        # Create new Reminders list
        source = store.defaultCalendarForNewReminders().source()
        new_cal = EventKit.EKCalendar.calendarForEntityType_eventStore_(
            EventKit.EKEntityTypeReminder, store
        )
        new_cal.setTitle_(list_name)
        new_cal.setSource_(source)

        error = None
        success = store.saveCalendar_commit_error_(new_cal, True, error)

        if success:
            created.append(list_name)
        else:
            print(json.dumps({"error": f"Failed to create list '{list_name}': {error}"}))
            sys.exit(1)

    print(json.dumps({
        "success": True,
        "created": created,
        "existing": existing,
        "message": f"Created {len(created)}, already existed {len(existing)}",
    }))


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  reminders_eventkit.py list_lists")
        print("  reminders_eventkit.py list_items <list_name>")
        print("  reminders_eventkit.py complete <reminder_id>")
        print("  reminders_eventkit.py create <list_name> <title> [notes] [due_date]")
        print("  reminders_eventkit.py ensure_lists")
        sys.exit(1)

    command = sys.argv[1]

    if command == "list_lists":
        list_lists()

    elif command == "list_items":
        if len(sys.argv) != 3:
            print("Usage: reminders_eventkit.py list_items <list_name>")
            sys.exit(1)
        list_items(sys.argv[2])

    elif command == "complete":
        if len(sys.argv) != 3:
            print("Usage: reminders_eventkit.py complete <reminder_id>")
            sys.exit(1)
        complete_item(sys.argv[2])

    elif command == "create":
        if len(sys.argv) < 4:
            print("Usage: reminders_eventkit.py create <list_name> <title> [notes] [due_date]")
            sys.exit(1)
        list_name = sys.argv[2]
        title = sys.argv[3]
        notes = sys.argv[4] if len(sys.argv) > 4 else ""
        due_date = sys.argv[5] if len(sys.argv) > 5 else ""
        create_item(list_name, title, notes, due_date)

    elif command == "ensure_lists":
        ensure_lists()

    elif command == "list_completed":
        if len(sys.argv) != 3:
            print("Usage: reminders_eventkit.py list_completed <list_name>")
            sys.exit(1)
        list_completed_items(sys.argv[2])

    elif command == "find_and_complete":
        if len(sys.argv) != 4:
            print("Usage: reminders_eventkit.py find_and_complete <list_name> <title_query>")
            sys.exit(1)
        find_and_complete(sys.argv[2], sys.argv[3])

    elif command == "clear_completed":
        if len(sys.argv) != 3:
            print("Usage: reminders_eventkit.py clear_completed <list_name>")
            sys.exit(1)
        clear_completed(sys.argv[2])

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
