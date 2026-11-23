import Foundation

public func waitForCallback(timeout: TimeInterval, work: (@escaping () -> Void) -> Void) -> Bool {
    var done = false
    work { done = true }
    let deadline = Date().addingTimeInterval(timeout)
    while !done && Date() < deadline {
        RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.05))
    }
    return done
}

public func isoString(from date: Date?) -> String? {
    guard let date else { return nil }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withColonSeparatorInTimeZone]
    formatter.timeZone = TimeZone.current
    return formatter.string(from: date)
}

public func startOfToday() -> Date {
    Calendar.current.startOfDay(for: Date())
}

public func dateByAddingDays(_ days: Int, to date: Date = startOfToday()) -> Date {
    Calendar.current.date(byAdding: .day, value: days, to: date) ?? date
}

public func parseLocalDateTime(_ raw: String) throws -> Date {
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.dateFormat = "yyyy-MM-dd HH:mm"
    formatter.timeZone = TimeZone.current
    guard let date = formatter.date(from: raw) else {
        throw HelperError.invalidArgs("Invalid start time. Use YYYY-MM-DD HH:MM.")
    }
    return date
}

public func parseLocalDate(_ raw: String) -> DateComponents? {
    let parts = raw.split(separator: "-").compactMap { Int($0) }
    guard parts.count == 3 else { return nil }
    var components = DateComponents()
    components.year = parts[0]
    components.month = parts[1]
    components.day = parts[2]
    components.hour = 9
    components.minute = 0
    return components
}

public func helperSupportDirectory() -> URL {
    let root = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Dex/helper", isDirectory: true)
    return root
}

public func helperTmpDirectory() -> URL {
    helperSupportDirectory().appendingPathComponent("tmp", isDirectory: true)
}

public func isAllowedJSONPath(_ rawPath: String) -> Bool {
    let path = URL(fileURLWithPath: rawPath).standardizedFileURL.path
    if path.contains("/System/.dex/tmp/") {
        return true
    }
    let allowedTmp = helperTmpDirectory().standardizedFileURL.path
    return path == allowedTmp || path.hasPrefix(allowedTmp.hasSuffix("/") ? allowedTmp : allowedTmp + "/")
}

public func encodeJSON(_ value: Any, pretty: Bool = true) throws -> String {
    guard JSONSerialization.isValidJSONObject(value) else {
        throw HelperError.unavailable("Dex Helper could not encode a result.")
    }
    var options: JSONSerialization.WritingOptions = pretty ? [.prettyPrinted] : []
    options.insert(.withoutEscapingSlashes)
    let data = try JSONSerialization.data(withJSONObject: value, options: options)
    guard let text = String(data: data, encoding: .utf8) else {
        throw HelperError.unavailable("Dex Helper could not encode a result.")
    }
    return text
}

public func writeOutputFile(_ text: String, to rawPath: String) throws {
    let body = text.hasSuffix("\n") ? text : text + "\n"
    let data = Data(body.utf8)
    let url = URL(fileURLWithPath: rawPath)
    let directory = url.deletingLastPathComponent()
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    if FileManager.default.fileExists(atPath: url.path) {
        try data.write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    } else {
        let created = FileManager.default.createFile(
            atPath: url.path,
            contents: data,
            attributes: [.posixPermissions: 0o600]
        )
        if !created {
            throw HelperError.unavailable("Dex Helper could not write its result.")
        }
    }
}

public func withRequestAccessLock<T>(_ work: () throws -> T) throws -> T {
    let directory = helperSupportDirectory()
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    let lockURL = directory.appendingPathComponent("request-access.lock")
    let path = lockURL.path
    if !FileManager.default.fileExists(atPath: path) {
        FileManager.default.createFile(atPath: path, contents: Data(), attributes: [.posixPermissions: 0o600])
    }

    let fd = open(path, O_RDWR)
    guard fd >= 0 else {
        throw HelperError.unavailable("Dex Helper could not start the permission ask.")
    }
    defer { close(fd) }

    let staleLimit: TimeInterval = 120
    let deadline = Date().addingTimeInterval(staleLimit)
    while flock(fd, LOCK_EX | LOCK_NB) != 0 {
        if Date() >= deadline {
            throw HelperError.timeout("Dex Helper timed out waiting to ask for Calendar and Reminders.")
        }
        if let attributes = try? FileManager.default.attributesOfItem(atPath: path),
           let modified = attributes[.modificationDate] as? Date,
           Date().timeIntervalSince(modified) > staleLimit {
            _ = flock(fd, LOCK_UN)
            continue
        }
        RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.05))
    }
    defer { _ = flock(fd, LOCK_UN) }
    try Data("\(ProcessInfo.processInfo.processIdentifier)".utf8).write(to: lockURL, options: .atomic)
    return try work()
}

public func jsonNull(_ value: String?) -> Any {
    value ?? NSNull()
}
