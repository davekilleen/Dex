import XCTest
@testable import DexHelper

final class ProtocolTests: XCTestCase {
    func testUnknownOpMessageMatchesPython() {
        let error = HelperError.unknownOp("calendar.nope")
        XCTAssertEqual(error.code, "unknown_op")
        XCTAssertEqual(error.message, "Unknown helper op: calendar.nope")
    }

    func testVersionDispatchHasNoExtraKeys() throws {
        let result = try dispatch(op: "version", args: [])
        guard case .json(let value, let code) = result else {
            return XCTFail("version should return JSON")
        }
        XCTAssertEqual(code, 0)
        let object = try XCTUnwrap(value as? [String: String])
        XCTAssertEqual(object, ["version": HelperIdentity.version])
    }

    func testLoadArgsReadsStringArray() {
        XCTAssertEqual(loadArgs(from: ["args": ["Work", "0", "1"]]), ["Work", "0", "1"])
        XCTAssertEqual(loadArgs(from: [:]), [])
    }

    func testAllowedJSONPaths() {
        XCTAssertTrue(isAllowedJSONPath("/var/tmp/vault/System/.dex/tmp/out.json"))
        XCTAssertTrue(isAllowedJSONPath(helperTmpDirectory().appendingPathComponent("out.json").path))
        XCTAssertFalse(isAllowedJSONPath("/tmp/out.json"))
        XCTAssertFalse(isAllowedJSONPath("/home/testuser/Desktop/secrets.json"))
    }

    func testJSONRoundTripWritesTrailingNewline() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("System/.dex/tmp", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent("helper-out.json")
        try writeOutputFile("{\"version\": \"1.1.0\"}", to: url.path)
        let text = try String(contentsOf: url, encoding: .utf8)
        XCTAssertTrue(text.hasSuffix("\n"))
        XCTAssertEqual(try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: String], [
            "version": "1.1.0",
        ])
    }
}
