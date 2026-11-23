import XCTest
@testable import DexHelper

final class FormatTests: XCTestCase {
    func testOrganizerIsNeverANonResponderEvenWhenPending() {
        XCTAssertFalse(attendeeIsNonResponder(status: "Pending", isOrganizer: true))
        XCTAssertTrue(attendeeIsNonResponder(status: "Pending", isOrganizer: false))
        XCTAssertTrue(attendeeIsNonResponder(status: "Unknown", isOrganizer: false))
        XCTAssertTrue(attendeeIsNonResponder(status: "In Process", isOrganizer: false))
        XCTAssertFalse(attendeeIsNonResponder(status: "Accepted", isOrganizer: false))
    }

    func testOrganizerMatchIsEmailBased() {
        XCTAssertTrue(attendeeIsOrganizer(
            email: "pat@example.com",
            isOrganizerFlag: false,
            organizerEmail: "pat@example.com"
        ))
        XCTAssertTrue(attendeeIsOrganizer(
            email: "pat@example.com",
            isOrganizerFlag: true,
            organizerEmail: ""
        ))
        XCTAssertFalse(attendeeIsOrganizer(
            email: "alex@example.com",
            isOrganizerFlag: false,
            organizerEmail: "pat@example.com"
        ))
    }

    func testISODateFormattingUsesOffset() {
        let date = Date(timeIntervalSince1970: 1_735_689_600)
        let text = isoString(from: date)
        XCTAssertNotNil(text)
        XCTAssertTrue(text?.contains("T") == true)
        XCTAssertFalse(text?.contains(" ") == true)
    }

    func testParseLocalDateTimeRejectsBadInput() {
        XCTAssertThrowsError(try parseLocalDateTime("not-a-date")) { error in
            let helper = error as? HelperError
            XCTAssertEqual(helper?.code, "invalid_args")
        }
    }
}
