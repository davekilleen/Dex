import AppKit
import EventKit
import Foundation

public func authorizationJSONName(for status: EKAuthorizationStatus) -> String {
    switch status {
    case .notDetermined:
        return "not_determined"
    case .restricted:
        return "restricted"
    case .denied:
        return "denied"
    case .writeOnly:
        return "write_only"
    case .fullAccess:
        return "granted"
    default:
        if status.rawValue == EKAuthorizationStatus.fullAccess.rawValue {
            return "granted"
        }
        return "unknown"
    }
}

public func authorizationJSONName(rawValue: Int) -> String {
    switch rawValue {
    case EKAuthorizationStatus.notDetermined.rawValue:
        return "not_determined"
    case EKAuthorizationStatus.restricted.rawValue:
        return "restricted"
    case EKAuthorizationStatus.denied.rawValue:
        return "denied"
    case EKAuthorizationStatus.writeOnly.rawValue:
        return "write_only"
    case EKAuthorizationStatus.fullAccess.rawValue:
        return "granted"
    default:
        return "unknown"
    }
}

public func authorizationSnapshot() -> [String: String] {
    [
        "calendar": authorizationJSONName(for: EKEventStore.authorizationStatus(for: .event)),
        "reminders": authorizationJSONName(for: EKEventStore.authorizationStatus(for: .reminder)),
    ]
}

func prepareAgentApp() {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
}

func requestCalendarAccess(_ store: EKEventStore) -> Bool {
    prepareAgentApp()
    var granted = false
    _ = waitForCallback(timeout: 60) { finish in
        store.requestFullAccessToEvents { ok, _ in
            granted = ok
            finish()
        }
    }
    return granted
}

func requestRemindersAccess(_ store: EKEventStore) -> Bool {
    prepareAgentApp()
    var granted = false
    _ = waitForCallback(timeout: 60) { finish in
        store.requestFullAccessToReminders { ok, _ in
            granted = ok
            finish()
        }
    }
    return granted
}

func requireCalendarStore() throws -> EKEventStore {
    let store = EKEventStore()
    let status = EKEventStore.authorizationStatus(for: .event)
    switch status {
    case .fullAccess, .authorized:
        return store
    case .denied:
        throw HelperError.permissionDenied(PermissionCopy.calendarDenied)
    case .restricted:
        throw HelperError.permissionRestricted(PermissionCopy.calendarRestricted)
    case .writeOnly:
        if requestCalendarAccess(store),
           EKEventStore.authorizationStatus(for: .event) == .fullAccess
            || EKEventStore.authorizationStatus(for: .event) == .authorized {
            return store
        }
        throw HelperError.permissionWriteOnly(PermissionCopy.calendarWriteOnly)
    case .notDetermined:
        if requestCalendarAccess(store),
           EKEventStore.authorizationStatus(for: .event) == .fullAccess
            || EKEventStore.authorizationStatus(for: .event) == .authorized {
            return store
        }
        throw HelperError.permissionDenied(PermissionCopy.calendarDenied)
    @unknown default:
        throw HelperError.unavailable("Dex Helper could not read Calendar permission.")
    }
}

func requireRemindersStore() throws -> EKEventStore {
    let store = EKEventStore()
    let status = EKEventStore.authorizationStatus(for: .reminder)
    switch status {
    case .fullAccess, .authorized:
        return store
    case .denied:
        throw HelperError.permissionDenied(PermissionCopy.remindersDenied)
    case .restricted:
        throw HelperError.permissionRestricted(PermissionCopy.remindersRestricted)
    case .notDetermined, .writeOnly:
        if requestRemindersAccess(store),
           EKEventStore.authorizationStatus(for: .reminder) == .fullAccess
            || EKEventStore.authorizationStatus(for: .reminder) == .authorized {
            return store
        }
        throw HelperError.permissionDenied(PermissionCopy.remindersDenied)
    @unknown default:
        throw HelperError.unavailable("Dex Helper could not read Reminders permission.")
    }
}

public func handleStatus() -> HelperResult {
    .json(authorizationSnapshot(), exitCode: 0)
}

public func handleRequestAccess() throws -> HelperResult {
    try withRequestAccessLock {
        let store = EKEventStore()
        _ = requestCalendarAccess(store)
        _ = requestRemindersAccess(store)
        let snapshot = authorizationSnapshot()
        let bothGranted = snapshot["calendar"] == "granted" && snapshot["reminders"] == "granted"
        return .json(snapshot, exitCode: bothGranted ? 0 : 1)
    }
}
