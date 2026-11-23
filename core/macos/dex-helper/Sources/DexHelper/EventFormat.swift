import EventKit
import Foundation

public func participantStatusName(_ status: EKParticipantStatus) -> String {
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

public func participantTypeName(_ type: EKParticipantType) -> String {
    switch type {
    case .unknown: return "Unknown"
    case .person: return "Person"
    case .room: return "Room"
    case .resource: return "Resource"
    case .group: return "Group"
    @unknown default: return "Unknown"
    }
}

public func participantEmail(_ participant: EKParticipant) -> String {
    participant.url.absoluteString.replacingOccurrences(of: "mailto:", with: "")
}

public func foldedStatus(_ status: String) -> String {
    let normalized = status.replacingOccurrences(of: "_", with: " ").replacingOccurrences(of: "-", with: " ").lowercased()
    return normalized.split(whereSeparator: { $0.isWhitespace }).joined()
}

public func attendeeIsOrganizer(email: String, isOrganizerFlag: Bool, organizerEmail: String) -> Bool {
    if isOrganizerFlag {
        return true
    }
    let left = email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let right = organizerEmail.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    return !left.isEmpty && !right.isEmpty && left == right
}

public func attendeeIsNonResponder(status: String, isOrganizer: Bool) -> Bool {
    if isOrganizer {
        return false
    }
    let folded = foldedStatus(status)
    return ["", "pending", "unknown", "needsaction", "notresponded", "inprocess"].contains(folded)
}

public func formatEvent(_ event: EKEvent, withAttendees: Bool) -> [String: Any] {
    var currentUserStatus: Any = NSNull()
    if let attendees = event.attendees, let me = attendees.first(where: { $0.isCurrentUser }) {
        currentUserStatus = participantStatusName(me.participantStatus)
    }

    var payload: [String: Any] = [
        "provider": "eventkit",
        "provider_event_id": event.eventIdentifier ?? event.calendarItemIdentifier,
        "provider_series_id": event.calendarItemIdentifier,
        "title": event.title ?? "",
        "start": isoString(from: event.startDate) ?? "",
        "end": isoString(from: event.endDate) ?? "",
        "location": event.location ?? "",
        "url": event.url?.absoluteString ?? "",
        "notes": event.notes ?? "",
        "all_day": event.isAllDay,
        "calendar_identifier": event.calendar?.calendarIdentifier ?? NSNull(),
        "calendar_name": event.calendar?.title ?? NSNull(),
        "state": "scheduled",
        "current_user_status": currentUserStatus,
        "last_modified": isoString(from: event.lastModifiedDate) ?? NSNull(),
    ]

    guard withAttendees else { return payload }

    var organizerInfo: [String: String]?
    if let organizer = event.organizer {
        organizerInfo = [
            "name": organizer.name ?? "",
            "email": participantEmail(organizer),
        ]
        payload["organizer"] = organizerInfo as Any
    }

    var attendees: [[String: Any]] = []
    for attendee in event.attendees ?? [] {
        let email = participantEmail(attendee)
        let organizerEmail = organizerInfo?["email"] ?? ""
        let isOrganizer = attendeeIsOrganizer(
            email: email,
            isOrganizerFlag: attendee.participantRole == .chair,
            organizerEmail: organizerEmail
        )
        let status = participantStatusName(attendee.participantStatus)
        attendees.append([
            "name": attendee.name ?? "",
            "email": email,
            "status": status,
            "type": participantTypeName(attendee.participantType),
            "is_organizer": isOrganizer,
            "is_current_user": attendee.isCurrentUser,
            "is_non_responder": attendeeIsNonResponder(status: status, isOrganizer: isOrganizer),
        ])
    }
    payload["attendees"] = attendees
    return payload
}

public func calendarColorDescription(_ calendar: EKCalendar) -> Any {
    if let color = calendar.cgColor {
        return String(describing: color)
    }
    return NSNull()
}
