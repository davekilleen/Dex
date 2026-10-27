import EventKit
import Foundation

let helperVersion = "1.0.0"

enum HelperError: Error, CustomStringConvertible {
    case usage(String)
    case failed(String)

    var description: String {
        switch self {
        case .usage(let message), .failed(let message):
            return message
        }
    }
}

func emitJSON(_ value: Any, pretty: Bool = true) {
    let options: JSONSerialization.WritingOptions = pretty ? [.prettyPrinted] : []
    guard JSONSerialization.isValidJSONObject(value),
          let data = try? JSONSerialization.data(withJSONObject: value, options: options),
          let text = String(data: data, encoding: .utf8) else {
        fputs("{\"error\":\"Failed to encode JSON\"}\n", stderr)
        exit(1)
    }
    print(text)
}

func emitError(_ message: String) -> Never {
    emitJSON(["error": message])
    exit(1)
}

func waitForCallback(timeout: TimeInterval, work: (@escaping () -> Void) -> Void) {
    var done = false
    work { done = true }
    let deadline = Date().addingTimeInterval(timeout)
    while !done && Date() < deadline {
        RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.05))
    }
}

func isoString(from date: Date?) -> String? {
    guard let date else { return nil }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    formatter.timeZone = TimeZone.current
    return formatter.string(from: date)
}

func startOfToday() -> Date {
    Calendar.current.startOfDay(for: Date())
}

func dateByAddingDays(_ days: Int, to date: Date = startOfToday()) -> Date {
    Calendar.current.date(byAdding: .day, value: days, to: date) ?? date
}

func parseStartDateTime(_ raw: String) throws -> Date {
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.dateFormat = "yyyy-MM-dd HH:mm"
    formatter.timeZone = TimeZone.current
    guard let date = formatter.date(from: raw) else {
        throw HelperError.failed("Invalid start time. Use YYYY-MM-DD HH:MM.")
    }
    return date
}

func authorizationName(for status: EKAuthorizationStatus) -> String {
    switch status {
    case .notDetermined: return "notDetermined"
    case .restricted: return "restricted"
    case .denied: return "denied"
    case .authorized: return "authorized"
    case .fullAccess: return "fullAccess"
    case .writeOnly: return "writeOnly"
    @unknown default: return "unknown"
    }
}

func requestCalendarAccess(_ store: EKEventStore) -> Bool {
    var granted = false
    waitForCallback(timeout: 60) { finish in
        let completion: (Bool, Error?) -> Void = { ok, _ in
            granted = ok
            finish()
        }
        if #available(macOS 14.0, *) {
            store.requestFullAccessToEvents(completion: completion)
        } else {
            store.requestAccess(to: .event, completion: completion)
        }
    }
    return granted
}

func requestRemindersAccess(_ store: EKEventStore) -> Bool {
    var granted = false
    waitForCallback(timeout: 60) { finish in
        let completion: (Bool, Error?) -> Void = { ok, _ in
            granted = ok
            finish()
        }
        if #available(macOS 14.0, *) {
            store.requestFullAccessToReminders(completion: completion)
        } else {
            store.requestAccess(to: .reminder, completion: completion)
        }
    }
    return granted
}

func hasCalendarAccess(_ store: EKEventStore) -> Bool {
    let status = EKEventStore.authorizationStatus(for: .event)
    if status == .fullAccess || status == .authorized {
        return true
    }
    if status == .denied {
        return false
    }
    if status == .writeOnly {
        if requestCalendarAccess(store) {
            return true
        }
        emitError(
            "Calendar access is set to Add Events Only. Dex needs Full Access to read events. "
                + "In System Settings → Privacy & Security → Calendars, change Dex Helper to Full Access."
        )
    }
    return requestCalendarAccess(store)
}

func hasRemindersAccess(_ store: EKEventStore) -> Bool {
    let status = EKEventStore.authorizationStatus(for: .reminder)
    if status == .fullAccess || status == .authorized {
        return true
    }
    if status == .denied || status == .restricted {
        return false
    }
    return requestRemindersAccess(store)
}

func requireCalendarStore() -> EKEventStore {
    let store = EKEventStore()
    guard hasCalendarAccess(store) else {
        emitError(
            "Calendar access denied. Enable it in System Settings → Privacy & Security → Calendars for Dex Helper."
        )
    }
    return store
}

func requireRemindersStore() -> EKEventStore {
    let store = EKEventStore()
    guard hasRemindersAccess(store) else {
        emitError(
            "Reminders access denied. Enable it in System Settings → Privacy & Security → Reminders for Dex Helper."
        )
    }
    return store
}

func findCalendar(named name: String, in store: EKEventStore) -> EKCalendar? {
    store.calendars(for: .event).first {
        $0.title == name || $0.calendarIdentifier == name
    }
}

func findReminderList(named name: String, in store: EKEventStore) -> EKCalendar? {
    store.calendars(for: .reminder).first { $0.title == name }
}

func participantStatusName(_ status: EKParticipantStatus) -> String {
    switch status {
    case .unknown: return "Unknown"
    case .pending: return "Pending"
    case .accepted: return "Accepted"
    case .declined: return "Declined"
    case .tentative: return "Tentative"
    case .delegated: return "Delegated"
    case .completed: return "Completed"
    case .inProcess: return "In Process"
    @unknown default: return "Unknown"
    }
}

func participantTypeName(_ type: EKParticipantType) -> String {
    switch type {
    case .unknown: return "Unknown"
    case .person: return "Person"
    case .room: return "Room"
    case .resource: return "Resource"
    case .group: return "Group"
    @unknown default: return "Unknown"
    }
}

func formatEvent(_ event: EKEvent, withAttendees: Bool) -> [String: Any] {
    var currentUserStatus: String?
    if let attendees = event.attendees {
        if let me = attendees.first(where: { $0.isCurrentUser }) {
            currentUserStatus = participantStatusName(me.participantStatus)
        }
    }

    var payload: [String: Any] = [
        "provider": "eventkit",
        "provider_event_id": event.eventIdentifier ?? event.calendarItemIdentifier ?? "",
        "provider_series_id": event.calendarItemIdentifier ?? event.calendarItemExternalIdentifier ?? "",
        "title": event.title ?? "",
        "start": isoString(from: event.startDate) ?? "",
        "end": isoString(from: event.endDate) ?? "",
        "location": event.location ?? "",
        "url": event.url?.absoluteString ?? "",
        "notes": event.notes ?? "",
        "all_day": event.isAllDay,
        "calendar_identifier": event.calendar?.calendarIdentifier as Any,
        "calendar_name": event.calendar?.title as Any,
        "state": "scheduled",
        "current_user_status": currentUserStatus as Any,
        "last_modified": isoString(from: event.lastModifiedDate) as Any,
    ]

    guard withAttendees else { return payload }

    var organizerInfo: [String: String]?
    if let organizer = event.organizer {
        organizerInfo = [
            "name": organizer.name ?? "",
            "email": organizer.url.absoluteString.replacingOccurrences(of: "mailto:", with: ""),
        ]
        payload["organizer"] = organizerInfo as Any
    }

    var attendees: [[String: Any]] = []
    for attendee in event.attendees ?? [] {
        let email = attendee.url.absoluteString.replacingOccurrences(of: "mailto:", with: "")
        let organizerEmail = organizerInfo?["email"] ?? ""
        let isOrganizer = (!organizerEmail.isEmpty && email == organizerEmail)
            || attendee.participantRole == .chair
        attendees.append([
            "name": attendee.name ?? "",
            "email": email,
            "status": participantStatusName(attendee.participantStatus),
            "type": participantTypeName(attendee.participantType),
            "is_organizer": isOrganizer,
            "is_current_user": attendee.isCurrentUser,
            "is_non_responder": attendee.participantStatus == .unknown
                || attendee.participantStatus == .pending,
        ])
    }
    payload["attendees"] = attendees
    return payload
}

func calendarsForQuery(name: String, store: EKEventStore) -> [EKCalendar] {
    if name.lowercased() == "all" {
        let calendars = store.calendars(for: .event)
        if calendars.isEmpty {
            emitError("No calendars found.")
        }
        return calendars
    }
    guard let calendar = findCalendar(named: name, in: store) else {
        emitError("Calendar not found: \(name)")
    }
    return [calendar]
}

func events(
    calendarName: String,
    startOffset: Int,
    endOffset: Int,
    withAttendees: Bool
) -> [[String: Any]] {
    let store = requireCalendarStore()
    let calendars = calendarsForQuery(name: calendarName, store: store)
    let start = dateByAddingDays(startOffset)
    let end = dateByAddingDays(endOffset)
    let predicate = store.predicateForEvents(withStart: start, end: end, calendars: calendars)
    let matches = store.events(matching: predicate).map {
        formatEvent($0, withAttendees: withAttendees)
    }
    return matches.sorted { lhs, rhs in
        (lhs["start"] as? String ?? "") < (rhs["start"] as? String ?? "")
    }
}

func fetchReminders(store: EKEventStore, predicate: NSPredicate) -> [EKReminder] {
    var result: [EKReminder] = []
    waitForCallback(timeout: 10) { finish in
        store.fetchReminders(matching: predicate) { reminders in
            result = reminders ?? []
            finish()
        }
    }
    return result
}

func reminderPayload(_ reminder: EKReminder, completed: Bool? = nil) -> [String: Any] {
    var due = ""
    if let components = reminder.dueDateComponents,
       let year = components.year,
       let month = components.month,
       let day = components.day,
       year > 0, month > 0, day > 0 {
        due = String(format: "%04d-%02d-%02d", year, month, day)
    }
    var item: [String: Any] = [
        "title": reminder.title ?? "",
        "notes": reminder.notes ?? "",
        "reminder_id": reminder.calendarItemIdentifier,
        "completed": completed ?? reminder.isCompleted,
    ]
    if reminder.isCompleted {
        item["completion_date"] = reminder.completionDate.map { String(describing: $0) } ?? ""
    } else {
        item["creation_date"] = reminder.creationDate.map { String(describing: $0) } ?? ""
        item["due_date"] = due
    }
    return item
}

func handleStatus() {
    let calendar = authorizationName(for: EKEventStore.authorizationStatus(for: .event))
    let reminders = authorizationName(for: EKEventStore.authorizationStatus(for: .reminder))
    emitJSON([
        "ok": true,
        "version": helperVersion,
        "signed": false,
        "bundle_id": "ai.heydex.DexHelper",
        "calendar": calendar,
        "reminders": reminders,
    ])
}

func handleRequestAccess() {
    let store = EKEventStore()
    let calendar = hasCalendarAccess(store)
    let reminders = hasRemindersAccess(store)
    emitJSON([
        "ok": calendar && reminders,
        "version": helperVersion,
        "signed": false,
        "calendar_granted": calendar,
        "reminders_granted": reminders,
        "calendar": authorizationName(for: EKEventStore.authorizationStatus(for: .event)),
        "reminders": authorizationName(for: EKEventStore.authorizationStatus(for: .reminder)),
    ], pretty: true)
    if !calendar || !reminders {
        exit(1)
    }
}

func handleCalendar(_ args: ArraySlice<String>) {
    guard let command = args.first else {
        emitError("Usage: DexHelper calendar <command> ...")
    }
    let rest = Array(args.dropFirst())
    switch command {
    case "list":
        let store = requireCalendarStore()
        let rows = store.calendars(for: .event).map { calendar -> [String: Any] in
            [
                "title": calendar.title ?? "",
                "type": calendar.type.rawValue,
                "color": calendar.cgColor.map { String(describing: $0) } as Any,
                "identifier": calendar.calendarIdentifier,
            ]
        }
        emitJSON(rows)
    case "events":
        guard rest.count == 3, let start = Int(rest[1]), let end = Int(rest[2]) else {
            emitError("Usage: DexHelper calendar events <calendar> <start_offset> <end_offset>")
        }
        emitJSON(events(calendarName: rest[0], startOffset: start, endOffset: end, withAttendees: false))
    case "attendees":
        guard rest.count == 3, let start = Int(rest[1]), let end = Int(rest[2]) else {
            emitError("Usage: DexHelper calendar attendees <calendar> <start_offset> <end_offset>")
        }
        emitJSON(events(calendarName: rest[0], startOffset: start, endOffset: end, withAttendees: true))
    case "search":
        guard rest.count == 4, let back = Int(rest[2]), let forward = Int(rest[3]) else {
            emitError("Usage: DexHelper calendar search <calendar> <query> <days_back> <days_forward>")
        }
        let store = requireCalendarStore()
        guard let calendar = findCalendar(named: rest[0], in: store) else {
            emitError("Calendar not found: \(rest[0])")
        }
        let start = dateByAddingDays(-back)
        let end = dateByAddingDays(forward)
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: [calendar])
        let query = rest[1].lowercased()
        let matches = store.events(matching: predicate)
            .filter { ($0.title ?? "").lowercased().contains(query) }
            .map { formatEvent($0, withAttendees: false) }
            .sorted { ($0["start"] as? String ?? "") < ($1["start"] as? String ?? "") }
        emitJSON(matches)
    case "next":
        guard rest.count == 1 else {
            emitError("Usage: DexHelper calendar next <calendar>")
        }
        let store = requireCalendarStore()
        guard let calendar = findCalendar(named: rest[0], in: store) else {
            emitError("Calendar not found: \(rest[0])")
        }
        let now = Date()
        let end = dateByAddingDays(90, to: now)
        let predicate = store.predicateForEvents(withStart: now, end: end, calendars: [calendar])
        let upcoming = store.events(matching: predicate).sorted { $0.startDate < $1.startDate }
        guard let next = upcoming.first else {
            emitJSON(["message": "No upcoming events found"])
            return
        }
        emitJSON(formatEvent(next, withAttendees: false))
    case "delete":
        guard rest.count == 3, let offset = Int(rest[2]) else {
            emitError("Usage: DexHelper calendar delete <calendar> <title> <day_offset>")
        }
        let store = requireCalendarStore()
        guard let calendar = findCalendar(named: rest[0], in: store) else {
            emitError("Calendar not found: \(rest[0])")
        }
        let start = dateByAddingDays(offset)
        let end = dateByAddingDays(1, to: start)
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: [calendar])
        let matching = store.events(matching: predicate)
            .filter { ($0.title ?? "") == rest[1] }
            .sorted { $0.startDate < $1.startDate }
        guard let event = matching.first else {
            print("No event found matching: \(rest[1])")
            return
        }
        do {
            try store.remove(event, span: .thisEvent, commit: true)
            print("Deleted event: \(rest[1])")
        } catch {
            emitError("Failed to delete event: \(rest[1])")
        }
    case "create":
        guard rest.count >= 4 else {
            emitError(
                "Usage: DexHelper calendar create <calendar> <title> <YYYY-MM-DD HH:MM> <duration> [description] [location]"
            )
        }
        let store = requireCalendarStore()
        guard let calendar = findCalendar(named: rest[0], in: store) else {
            emitError("Calendar not found: \(rest[0])")
        }
        let start: Date
        do {
            start = try parseStartDateTime(rest[2])
        } catch {
            emitError(String(describing: error))
        }
        let duration = Int(rest[3]) ?? 30
        let end = start.addingTimeInterval(TimeInterval(duration * 60))
        let event = EKEvent(eventStore: store)
        event.calendar = calendar
        event.title = rest[1]
        event.startDate = start
        event.endDate = end
        if rest.count > 4, !rest[4].isEmpty {
            event.notes = rest[4]
        }
        if rest.count > 5, !rest[5].isEmpty {
            event.location = rest[5]
        }
        do {
            try store.save(event, span: .thisEvent, commit: true)
            let shown = DateFormatter()
            shown.dateStyle = .medium
            shown.timeStyle = .short
            print("Created: \(rest[1]) at \(shown.string(from: start))")
        } catch {
            emitError("Failed to create event: \(rest[1])")
        }
    default:
        emitError("Unknown calendar command: \(command)")
    }
}

func handleReminders(_ args: ArraySlice<String>) {
    guard let command = args.first else {
        emitError("Usage: DexHelper reminders <command> ...")
    }
    let rest = Array(args.dropFirst())
    switch command {
    case "list_lists":
        let store = requireRemindersStore()
        let rows = store.calendars(for: .reminder).map { list -> [String: Any] in
            [
                "title": list.title ?? "",
                "identifier": list.calendarIdentifier,
                "color": list.cgColor.map { String(describing: $0) } as Any,
            ]
        }
        emitJSON(rows)
    case "list_items":
        guard rest.count == 1 else {
            emitError("Usage: DexHelper reminders list_items <list_name>")
        }
        let store = requireRemindersStore()
        guard let list = findReminderList(named: rest[0], in: store) else {
            emitError("Reminders list not found: \(rest[0])")
        }
        let predicate = store.predicateForIncompleteReminders(
            withDueDateStarting: nil,
            ending: nil,
            calendars: [list]
        )
        let items = fetchReminders(store: store, predicate: predicate)
            .map { reminderPayload($0) }
            .sorted { ($0["creation_date"] as? String ?? "") > ($1["creation_date"] as? String ?? "") }
        emitJSON(items)
    case "list_completed":
        guard rest.count == 1 else {
            emitError("Usage: DexHelper reminders list_completed <list_name>")
        }
        let store = requireRemindersStore()
        guard let list = findReminderList(named: rest[0], in: store) else {
            emitError("Reminders list not found: \(rest[0])")
        }
        let start = Date().addingTimeInterval(-86400 * 2)
        let predicate = store.predicateForCompletedReminders(
            withCompletionDateStarting: start,
            ending: Date(),
            calendars: [list]
        )
        emitJSON(fetchReminders(store: store, predicate: predicate).map {
            reminderPayload($0, completed: true)
        })
    case "complete":
        guard rest.count == 1 else {
            emitError("Usage: DexHelper reminders complete <reminder_id>")
        }
        let store = requireRemindersStore()
        let predicate = store.predicateForReminders(in: nil)
        guard let reminder = fetchReminders(store: store, predicate: predicate)
            .first(where: { $0.calendarItemIdentifier == rest[0] }) else {
            emitError("Reminder not found: \(rest[0])")
        }
        reminder.isCompleted = true
        reminder.completionDate = Date()
        do {
            try store.save(reminder, commit: true)
            emitJSON(["success": true, "reminder_id": rest[0], "status": "completed"])
        } catch {
            emitError("Failed to save reminder: \(error.localizedDescription)")
        }
    case "create":
        guard rest.count >= 2 else {
            emitError("Usage: DexHelper reminders create <list_name> <title> [notes] [due_date]")
        }
        let store = requireRemindersStore()
        guard let list = findReminderList(named: rest[0], in: store) else {
            emitError("Reminders list not found: \(rest[0]). Run 'ensure_lists' first.")
        }
        let reminder = EKReminder(eventStore: store)
        reminder.title = rest[1]
        reminder.calendar = list
        if rest.count > 2, !rest[2].isEmpty {
            reminder.notes = rest[2]
        }
        if rest.count > 3, !rest[3].isEmpty {
            let parts = rest[3].split(separator: "-").compactMap { Int($0) }
            if parts.count == 3 {
                var components = DateComponents()
                components.year = parts[0]
                components.month = parts[1]
                components.day = parts[2]
                components.hour = 9
                components.minute = 0
                reminder.dueDateComponents = components
            }
        }
        do {
            try store.save(reminder, commit: true)
            emitJSON([
                "success": true,
                "reminder_id": reminder.calendarItemIdentifier,
                "title": rest[1],
                "list": rest[0],
            ])
        } catch {
            emitError("Failed to create reminder: \(error.localizedDescription)")
        }
    case "find_and_complete":
        guard rest.count == 2 else {
            emitError("Usage: DexHelper reminders find_and_complete <list_name> <title_query>")
        }
        let store = requireRemindersStore()
        guard let list = findReminderList(named: rest[0], in: store) else {
            emitError("Reminders list not found: \(rest[0])")
        }
        let predicate = store.predicateForIncompleteReminders(
            withDueDateStarting: nil,
            ending: nil,
            calendars: [list]
        )
        let query = rest[1].lowercased()
        let match = fetchReminders(store: store, predicate: predicate).first { reminder in
            let title = (reminder.title ?? "").lowercased()
            return title.contains(query) || query.contains(title)
        }
        guard let reminder = match else {
            emitJSON(["found": false, "message": "No matching reminder for: \(rest[1])"])
            return
        }
        reminder.isCompleted = true
        reminder.completionDate = Date()
        do {
            try store.save(reminder, commit: true)
            emitJSON([
                "found": true,
                "completed": true,
                "reminder_id": reminder.calendarItemIdentifier,
                "title": reminder.title ?? "",
            ])
        } catch {
            emitError("Failed to save: \(error.localizedDescription)")
        }
    case "clear_completed":
        guard rest.count == 1 else {
            emitError("Usage: DexHelper reminders clear_completed <list_name>")
        }
        let store = requireRemindersStore()
        guard let list = findReminderList(named: rest[0], in: store) else {
            emitError("Reminders list not found: \(rest[0])")
        }
        let start = Date().addingTimeInterval(-86400 * 7)
        let predicate = store.predicateForCompletedReminders(
            withCompletionDateStarting: start,
            ending: Date(),
            calendars: [list]
        )
        var removed = 0
        for reminder in fetchReminders(store: store, predicate: predicate) {
            do {
                try store.remove(reminder, commit: true)
                removed += 1
            } catch {
                continue
            }
        }
        emitJSON(["success": true, "removed": removed, "list": rest[0]])
    case "ensure_lists":
        let store = requireRemindersStore()
        var created: [String] = []
        var existing: [String] = []
        for name in ["Dex Inbox", "Dex Today"] {
            if findReminderList(named: name, in: store) != nil {
                existing.append(name)
                continue
            }
            let list = EKCalendar(for: .reminder, eventStore: store)
            list.title = name
            if let source = store.defaultCalendarForNewReminders()?.source {
                list.source = source
            }
            do {
                try store.saveCalendar(list, commit: true)
                created.append(name)
            } catch {
                emitError("Failed to create list '\(name)': \(error.localizedDescription)")
            }
        }
        emitJSON([
            "success": true,
            "created": created,
            "existing": existing,
            "message": "Created \(created.count), already existed \(existing.count)",
        ])
    default:
        emitError("Unknown reminders command: \(command)")
    }
}

func main() {
    let args = Array(CommandLine.arguments.dropFirst())
    guard let domain = args.first else {
        fputs(
            """
            Usage:
              DexHelper version
              DexHelper status
              DexHelper request-access
              DexHelper calendar <command> ...
              DexHelper reminders <command> ...
            """,
            stderr
        )
        exit(1)
    }
    switch domain {
    case "version":
        emitJSON(["version": helperVersion, "signed": false, "bundle_id": "ai.heydex.DexHelper"])
    case "status":
        handleStatus()
    case "request-access":
        handleRequestAccess()
    case "calendar":
        handleCalendar(args.dropFirst())
    case "reminders":
        handleReminders(args.dropFirst())
    default:
        emitError("Unknown command: \(domain)")
    }
}

main()
