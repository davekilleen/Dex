import EventKit
import Foundation

public func reminderPayload(_ reminder: EKReminder, completed: Bool? = nil) -> [String: Any] {
    var due = ""
    if let components = reminder.dueDateComponents,
       let year = components.year,
       let month = components.month,
       let day = components.day,
       year > 0, month > 0, day > 0 {
        due = String(format: "%04d-%02d-%02d", year, month, day)
    }
    let isCompleted = completed ?? reminder.isCompleted
    var item: [String: Any] = [
        "title": reminder.title ?? "",
        "notes": reminder.notes ?? "",
        "reminder_id": reminder.calendarItemIdentifier,
        "completed": isCompleted,
    ]
    if isCompleted {
        item["completion_date"] = isoString(from: reminder.completionDate) ?? ""
    } else {
        item["creation_date"] = isoString(from: reminder.creationDate) ?? ""
        item["due_date"] = due
    }
    return item
}

public func fetchReminders(store: EKEventStore, predicate: NSPredicate) throws -> [EKReminder] {
    var result: [EKReminder]?
    var finished = false
    let done = waitForCallback(timeout: 10) { finish in
        store.fetchReminders(matching: predicate) { reminders in
            result = reminders ?? []
            finished = true
            finish()
        }
    }
    if !done || !finished {
        throw HelperError.timeout("Dex Helper timed out reading Reminders.")
    }
    return result ?? []
}
