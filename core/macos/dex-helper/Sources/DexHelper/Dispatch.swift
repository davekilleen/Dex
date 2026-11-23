import Foundation

public enum HelperResult {
    case json(Any, exitCode: Int32)
    case text(String, exitCode: Int32)

    public var exitCode: Int32 {
        switch self {
        case .json(_, let code), .text(_, let code):
            return code
        }
    }

    public func encodedText() throws -> String {
        switch self {
        case .json(let value, _):
            return try encodeJSON(value)
        case .text(let value, _):
            return value
        }
    }
}

public func dispatch(op: String, args: [String]) throws -> HelperResult {
    switch op {
    case "version":
        return .json(["version": HelperIdentity.version], exitCode: 0)
    case "status":
        return handleStatus()
    case "request-access":
        return try handleRequestAccess()
    case "calendar.list":
        return try handleCalendarList()
    case "calendar.events":
        return try handleCalendarEvents(args, withAttendees: false)
    case "calendar.attendees":
        return try handleCalendarEvents(args, withAttendees: true)
    case "calendar.search":
        return try handleCalendarSearch(args)
    case "calendar.next":
        return try handleCalendarNext(args)
    case "calendar.delete":
        return try handleCalendarDelete(args)
    case "calendar.create":
        return try handleCalendarCreate(args)
    case "reminders.list_lists":
        return try handleRemindersListLists()
    case "reminders.list_items":
        return try handleRemindersListItems(args)
    case "reminders.list_completed":
        return try handleRemindersListCompleted(args)
    case "reminders.complete":
        return try handleRemindersComplete(args)
    case "reminders.create":
        return try handleRemindersCreate(args)
    case "reminders.find_and_complete":
        return try handleRemindersFindAndComplete(args)
    case "reminders.clear_completed":
        return try handleRemindersClearCompleted(args)
    case "reminders.ensure_lists":
        return try handleRemindersEnsureLists()
    default:
        throw HelperError.unknownOp(op)
    }
}

public func loadArgs(from payload: [String: Any]) -> [String] {
    guard let raw = payload["args"] as? [Any] else { return [] }
    return raw.map { String(describing: $0) }
}

public func loadPayload(from inPath: String?) throws -> [String: Any] {
    guard let inPath, !inPath.isEmpty else { return [:] }
    let data = try Data(contentsOf: URL(fileURLWithPath: inPath))
    if data.isEmpty {
        return [:]
    }
    let parsed = try JSONSerialization.jsonObject(with: data, options: [])
    return parsed as? [String: Any] ?? [:]
}

public func runHelper(arguments: [String]) -> Int32 {
    let argv = Array(arguments.dropFirst())
    guard argv.count >= 2 else {
        fputs("Usage: DexHelper <op> <json-out-path> [json-in-path]\n", stderr)
        if argv.count >= 1 {
            let outPath = argv.count >= 2 ? argv[1] : ""
            if !outPath.isEmpty, isAllowedJSONPath(outPath) {
                try? writeOutputFile(
                    (try? encodeJSON(HelperError.usage("Usage: DexHelper <op> <json-out-path> [json-in-path]").payload)) ?? "",
                    to: outPath
                )
            }
        }
        return 2
    }

    let op = argv[0]
    let outPath = argv[1]
    let inPath = argv.count > 2 ? argv[2] : nil

    func finish(_ result: HelperResult) -> Int32 {
        do {
            try writeOutputFile(try result.encodedText(), to: outPath)
            return result.exitCode
        } catch let error as HelperError {
            try? writeOutputFile((try? encodeJSON(error.payload)) ?? "", to: outPath)
            return 1
        } catch {
            try? writeOutputFile(
                (try? encodeJSON(HelperError.unavailable("Dex Helper could not write its result.").payload)) ?? "",
                to: outPath
            )
            return 1
        }
    }

    if !isAllowedJSONPath(outPath) {
        return finish(.json(HelperError.pathRefused("Dex Helper refused an output path outside its temp folders.").payload, exitCode: 1))
    }
    if let inPath, !isAllowedJSONPath(inPath) {
        return finish(.json(HelperError.pathRefused("Dex Helper refused an input path outside its temp folders.").payload, exitCode: 1))
    }

    do {
        let payload = try loadPayload(from: inPath)
        let args = loadArgs(from: payload)
        let result = try dispatch(op: op, args: args)
        return finish(result)
    } catch let error as HelperError {
        return finish(.json(error.payload, exitCode: 1))
    } catch {
        return finish(
            .json(
                HelperError.unavailable("Dex Helper could not talk to Calendar or Reminders.").payload,
                exitCode: 1
            )
        )
    }
}
