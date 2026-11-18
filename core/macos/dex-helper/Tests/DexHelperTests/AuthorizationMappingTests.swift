import EventKit
import XCTest
@testable import DexHelper

final class AuthorizationMappingTests: XCTestCase {
    func testAppleStatusNamesUseSnakeCase() {
        XCTAssertEqual(authorizationJSONName(for: .notDetermined), "not_determined")
        XCTAssertEqual(authorizationJSONName(for: .restricted), "restricted")
        XCTAssertEqual(authorizationJSONName(for: .denied), "denied")
        XCTAssertEqual(authorizationJSONName(for: .fullAccess), "granted")
        XCTAssertEqual(authorizationJSONName(for: .writeOnly), "write_only")
    }

    func testWriteOnlyRawValueIsNotReportedAsGranted() {
        // Apple's writeOnly is 4. Mapping 4 to granted was the old Python bug.
        XCTAssertEqual(authorizationJSONName(rawValue: EKAuthorizationStatus.writeOnly.rawValue), "write_only")
        XCTAssertEqual(authorizationJSONName(rawValue: EKAuthorizationStatus.fullAccess.rawValue), "granted")
        XCTAssertNotEqual(EKAuthorizationStatus.writeOnly.rawValue, EKAuthorizationStatus.fullAccess.rawValue)
    }

    func testUnknownRawValueIsUnknown() {
        XCTAssertEqual(authorizationJSONName(rawValue: 99), "unknown")
    }
}
