import Foundation

public struct HelperError: Error, Equatable {
    public let code: String
    public let message: String
    public let extra: [String: String]

    public init(code: String, message: String, extra: [String: String] = [:]) {
        self.code = code
        self.message = message
        self.extra = extra
    }

    public var payload: [String: Any] {
        var body: [String: Any] = ["error": message, "code": code]
        for (key, value) in extra {
            body[key] = value
        }
        return body
    }

    public static func usage(_ message: String) -> HelperError {
        HelperError(code: "usage", message: message)
    }

    public static func unknownOp(_ op: String) -> HelperError {
        HelperError(code: "unknown_op", message: "Unknown helper op: \(op)")
    }

    public static func invalidArgs(_ message: String) -> HelperError {
        HelperError(code: "invalid_args", message: message)
    }

    public static func permissionDenied(_ message: String) -> HelperError {
        HelperError(code: "permission_denied", message: message)
    }

    public static func permissionWriteOnly(_ message: String) -> HelperError {
        HelperError(code: "permission_write_only", message: message)
    }

    public static func permissionRestricted(_ message: String) -> HelperError {
        HelperError(code: "permission_restricted", message: message)
    }

    public static func notFound(_ message: String) -> HelperError {
        HelperError(code: "not_found", message: message)
    }

    public static func saveFailed(_ message: String) -> HelperError {
        HelperError(code: "save_failed", message: message)
    }

    public static func timeout(_ message: String) -> HelperError {
        HelperError(code: "timeout", message: message)
    }

    public static func unavailable(_ message: String) -> HelperError {
        HelperError(code: "unavailable", message: message)
    }

    public static func pathRefused(_ message: String) -> HelperError {
        HelperError(code: "path_refused", message: message)
    }
}

public enum HelperIdentity {
    public static let version = "1.1.0"
    public static let bundleId = "ai.heydex.DexHelper"
}

public enum PermissionCopy {
    public static let calendarDenied =
        "Calendar access denied. Enable it in System Settings → Privacy & Security → Calendars for Dex Helper. Run /calendar-setup."
    public static let calendarWriteOnly =
        "Calendar access is set to Add Events Only. Dex Helper needs Full Access to read events. In System Settings → Privacy & Security → Calendars, change Dex Helper to Full Access."
    public static let calendarRestricted =
        "Calendar access is restricted by system policies. Dex Helper cannot read calendars until that restriction is lifted."
    public static let remindersDenied =
        "Reminders access denied. Enable it in System Settings → Privacy & Security → Reminders for Dex Helper. Run /calendar-setup."
    public static let remindersRestricted =
        "Reminders access is restricted by system policies. Dex Helper cannot read reminders until that restriction is lifted."
}
