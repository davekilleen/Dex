import EventKit
import Foundation

func findReminderList(named name: String, in store: EKEventStore) -> EKCalendar? {
    store.calendars(for: .reminder).first { $0.title == name }
}

public func handleRemindersListLists() throws -> HelperResult {
    let store = try requireRemindersStore()
    let rows = store.calendars(for: .reminder).map { list -> [String: Any] in
        [
            "title": list.title,
            "identifier": list.calendarIdentifier,
            "color": calendarColorDescription(list),
        ]
    }
    return .json(rows, exitCode: 0)
}

public func handleRemindersListItems(_ args: [String]) throws -> HelperResult {
    guard args.count == 1 else {
        throw HelperError.invalidArgs("reminders.list_items needs a list name.")
    }
    let store = try requireRemindersStore()
    guard let list = findReminderList(named: args[0], in: store) else {
        throw HelperError.notFound("Reminders list not found: \(args[0])")
    }
    let predicate = store.predicateForIncompleteReminders(
        withDueDateStarting: nil,
        ending: nil,
        calendars: [list]
    )
    let items = try fetchReminders(store: store, predicate: predicate)
        .map { reminderPayload($0) }
        .sorted { ($0["creation_date"] as? String ?? "") > ($1["creation_date"] as? String ?? "") }
    return .json(items, exitCode: 0)
}

public func handleRemindersListCompleted(_ args: [String]) throws -> HelperResult {
    guard args.count == 1 else {
        throw HelperError.invalidArgs("reminders.list_completed needs a list name.")
    }
    let store = try requireRemindersStore()
    guard let list = findReminderList(named: args[0], in: store) else {
        throw HelperError.notFound("Reminders list not found: \(args[0])")
    }
    let start = Date().addingTimeInterval(-86400 * 2)
    let predicate = store.predicateForCompletedReminders(
        withCompletionDateStarting: start,
        ending: Date(),
        calendars: [list]
    )
    let items = try fetchReminders(store: store, predicate: predicate).map {
        reminderPayload($0, completed: true)
    }
    return .json(items, exitCode: 0)
}

public func handleRemindersComplete(_ args: [String]) throws -> HelperResult {
    guard args.count == 1 else {
        throw HelperError.invalidArgs("reminders.complete needs a reminder id.")
    }
    let store = try requireRemindersStore()
    let predicate = store.predicateForReminders(in: nil)
    guard let reminder = try fetchReminders(store: store, predicate: predicate)
        .first(where: { $0.calendarItemIdentifier == args[0] }) else {
        throw HelperError.notFound("Reminder not found: \(args[0])")
    }
    reminder.isCompleted = true
    reminder.completionDate = Date()
    do {
        try store.save(reminder, commit: true)
        return .json(
            ["success": true, "reminder_id": args[0], "status": "completed"],
            exitCode: 0
        )
    } catch {
        throw HelperError.saveFailed("Failed to save reminder: \(error.localizedDescription)")
    }
}

public func handleRemindersCreate(_ args: [String]) throws -> HelperResult {
    guard args.count >= 2 else {
        throw HelperError.invalidArgs("reminders.create needs a list name and a title.")
    }
    let store = try requireRemindersStore()
    guard let list = findReminderList(named: args[0], in: store) else {
        throw HelperError.notFound("Reminders list not found: \(args[0]). Run 'ensure_lists' first.")
    }
    let reminder = EKReminder(eventStore: store)
    reminder.title = args[1]
    reminder.calendar = list
    if args.count > 2, !args[2].isEmpty {
        reminder.notes = args[2]
    }
    if args.count > 3, !args[3].isEmpty, let components = parseLocalDate(args[3]) {
        reminder.dueDateComponents = components
    }
    do {
        try store.save(reminder, commit: true)
        return .json(
            [
                "success": true,
                "reminder_id": reminder.calendarItemIdentifier,
                "title": args[1],
                "list": args[0],
            ],
            exitCode: 0
        )
    } catch {
        throw HelperError.saveFailed("Failed to create reminder: \(error.localizedDescription)")
    }
}

public func handleRemindersFindAndComplete(_ args: [String]) throws -> HelperResult {
    guard args.count == 2 else {
        throw HelperError.invalidArgs("reminders.find_and_complete needs a list name and a title query.")
    }
    let store = try requireRemindersStore()
    guard let list = findReminderList(named: args[0], in: store) else {
        throw HelperError.notFound("Reminders list not found: \(args[0])")
    }
    let predicate = store.predicateForIncompleteReminders(
        withDueDateStarting: nil,
        ending: nil,
        calendars: [list]
    )
    let query = args[1].lowercased()
    let match = try fetchReminders(store: store, predicate: predicate).first { reminder in
        let title = (reminder.title ?? "").lowercased()
        return title.contains(query) || query.contains(title)
    }
    guard let reminder = match else {
        return .json(
            ["found": false, "message": "No matching reminder for: \(args[1])"],
            exitCode: 0
        )
    }
    reminder.isCompleted = true
    reminder.completionDate = Date()
    do {
        try store.save(reminder, commit: true)
        return .json(
            [
                "found": true,
                "completed": true,
                "reminder_id": reminder.calendarItemIdentifier,
                "title": reminder.title ?? "",
            ],
            exitCode: 0
        )
    } catch {
        throw HelperError.saveFailed("Failed to save: \(error.localizedDescription)")
    }
}

public func handleRemindersClearCompleted(_ args: [String]) throws -> HelperResult {
    guard args.count == 1 else {
        throw HelperError.invalidArgs("reminders.clear_completed needs a list name.")
    }
    let store = try requireRemindersStore()
    guard let list = findReminderList(named: args[0], in: store) else {
        throw HelperError.notFound("Reminders list not found: \(args[0])")
    }
    let start = Date().addingTimeInterval(-86400 * 7)
    let predicate = store.predicateForCompletedReminders(
        withCompletionDateStarting: start,
        ending: Date(),
        calendars: [list]
    )
    var removed = 0
    for reminder in try fetchReminders(store: store, predicate: predicate) {
        do {
            try store.remove(reminder, commit: true)
            removed += 1
        } catch {
            continue
        }
    }
    return .json(["success": true, "removed": removed, "list": args[0]], exitCode: 0)
}

public func handleRemindersEnsureLists() throws -> HelperResult {
    let store = try requireRemindersStore()
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
            throw HelperError.saveFailed("Failed to create list '\(name)': \(error.localizedDescription)")
        }
    }
    return .json(
        [
            "success": true,
            "created": created,
            "existing": existing,
            "message": "Created \(created.count), already existed \(existing.count)",
        ],
        exitCode: 0
    )
}
