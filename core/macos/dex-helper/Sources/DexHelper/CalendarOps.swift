import EventKit
import Foundation

func findCalendar(named name: String, in store: EKEventStore) -> EKCalendar? {
    store.calendars(for: .event).first {
        $0.title == name || $0.calendarIdentifier == name
    }
}

func calendarsForQuery(name: String, store: EKEventStore) throws -> [EKCalendar] {
    if name.lowercased() == "all" {
        let calendars = store.calendars(for: .event)
        if calendars.isEmpty {
            throw HelperError.notFound("No calendars found.")
        }
        return calendars
    }
    guard let calendar = findCalendar(named: name, in: store) else {
        throw HelperError.notFound("Calendar not found: \(name)")
    }
    return [calendar]
}

func events(
    calendarName: String,
    startOffset: Int,
    endOffset: Int,
    withAttendees: Bool
) throws -> [[String: Any]] {
    let store = try requireCalendarStore()
    let calendars = try calendarsForQuery(name: calendarName, store: store)
    let start = dateByAddingDays(startOffset)
    let end = dateByAddingDays(endOffset)
    let predicate = store.predicateForEvents(withStart: start, end: end, calendars: calendars)
    return store.events(matching: predicate)
        .map { formatEvent($0, withAttendees: withAttendees) }
        .sorted { ($0["start"] as? String ?? "") < ($1["start"] as? String ?? "") }
}

func parseInt(_ raw: String, label: String) throws -> Int {
    guard let value = Int(raw) else {
        throw HelperError.invalidArgs("\(label) must be a whole number.")
    }
    return value
}

public func handleCalendarList() throws -> HelperResult {
    let store = try requireCalendarStore()
    let rows = store.calendars(for: .event).map { calendar -> [String: Any] in
        [
            "title": calendar.title,
            "type": calendar.type.rawValue,
            "color": calendarColorDescription(calendar),
            "identifier": calendar.calendarIdentifier,
        ]
    }
    return .json(rows, exitCode: 0)
}

public func handleCalendarEvents(_ args: [String], withAttendees: Bool) throws -> HelperResult {
    guard args.count == 3 else {
        throw HelperError.invalidArgs(
            withAttendees
                ? "calendar.attendees needs a calendar name, start offset, and end offset."
                : "calendar.events needs a calendar name, start offset, and end offset."
        )
    }
    let start = try parseInt(args[1], label: "start offset")
    let end = try parseInt(args[2], label: "end offset")
    let rows = try events(
        calendarName: args[0],
        startOffset: start,
        endOffset: end,
        withAttendees: withAttendees
    )
    return .json(rows, exitCode: 0)
}

public func handleCalendarSearch(_ args: [String]) throws -> HelperResult {
    guard args.count == 4 else {
        throw HelperError.invalidArgs(
            "calendar.search needs a calendar name, query, days back, and days forward."
        )
    }
    let daysBack = try parseInt(args[2], label: "days back")
    let daysForward = try parseInt(args[3], label: "days forward")
    let store = try requireCalendarStore()
    let calendars = try calendarsForQuery(name: args[0], store: store)
    let start = dateByAddingDays(-daysBack)
    let end = dateByAddingDays(daysForward)
    let predicate = store.predicateForEvents(withStart: start, end: end, calendars: calendars)
    let query = args[1].lowercased()
    let matches = store.events(matching: predicate)
        .filter { ($0.title ?? "").lowercased().contains(query) }
        .map { formatEvent($0, withAttendees: false) }
        .sorted { ($0["start"] as? String ?? "") < ($1["start"] as? String ?? "") }
    return .json(matches, exitCode: 0)
}

public func handleCalendarNext(_ args: [String]) throws -> HelperResult {
    guard args.count == 1 else {
        throw HelperError.invalidArgs("calendar.next needs a calendar name.")
    }
    let store = try requireCalendarStore()
    let calendars = try calendarsForQuery(name: args[0], store: store)
    let now = Date()
    let end = dateByAddingDays(90, to: now)
    let predicate = store.predicateForEvents(withStart: now, end: end, calendars: calendars)
    let upcoming = store.events(matching: predicate).sorted { $0.startDate < $1.startDate }
    guard let next = upcoming.first else {
        return .json(["message": "No upcoming events found"], exitCode: 0)
    }
    return .json(formatEvent(next, withAttendees: false), exitCode: 0)
}

public func handleCalendarDelete(_ args: [String]) throws -> HelperResult {
    guard args.count == 3 else {
        throw HelperError.invalidArgs("calendar.delete needs a calendar name, title, and day offset.")
    }
    let offset = try parseInt(args[2], label: "day offset")
    let store = try requireCalendarStore()
    guard let calendar = findCalendar(named: args[0], in: store) else {
        throw HelperError.notFound("Calendar not found: \(args[0])")
    }
    let start = dateByAddingDays(offset)
    let end = dateByAddingDays(1, to: start)
    let predicate = store.predicateForEvents(withStart: start, end: end, calendars: [calendar])
    let matching = store.events(matching: predicate)
        .filter { ($0.title ?? "") == args[1] }
        .sorted { $0.startDate < $1.startDate }
    guard let event = matching.first else {
        return .text("No event found matching: \(args[1])", exitCode: 0)
    }
    do {
        try store.remove(event, span: .thisEvent, commit: true)
        return .text("Deleted event: \(args[1])", exitCode: 0)
    } catch {
        throw HelperError.saveFailed("Failed to delete event: \(args[1])")
    }
}

public func handleCalendarCreate(_ args: [String]) throws -> HelperResult {
    guard args.count >= 4 else {
        throw HelperError.invalidArgs(
            "calendar.create needs a calendar name, title, start time, and duration in minutes."
        )
    }
    let store = try requireCalendarStore()
    guard let calendar = findCalendar(named: args[0], in: store) else {
        throw HelperError.notFound("Calendar not found: \(args[0])")
    }
    let start = try parseLocalDateTime(args[2])
    let duration = try parseInt(args[3], label: "duration")
    let end = start.addingTimeInterval(TimeInterval(duration * 60))
    let event = EKEvent(eventStore: store)
    event.calendar = calendar
    event.title = args[1]
    event.startDate = start
    event.endDate = end
    if args.count > 4, !args[4].isEmpty {
        event.notes = args[4]
    }
    if args.count > 5, !args[5].isEmpty {
        event.location = args[5]
    }
    do {
        try store.save(event, span: .thisEvent, commit: true)
        let shown = DateFormatter()
        shown.dateStyle = .medium
        shown.timeStyle = .short
        shown.locale = Locale.current
        shown.timeZone = TimeZone.current
        return .text("Created: \(args[1]) at \(shown.string(from: start))", exitCode: 0)
    } catch {
        throw HelperError.saveFailed("Failed to create event: \(args[1])")
    }
}
