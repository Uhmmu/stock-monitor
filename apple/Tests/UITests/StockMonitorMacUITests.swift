import XCTest

final class StockMonitorMacUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testSecureLoginGateIsVisibleWithoutStoredCredentials() {
        let app = XCUIApplication()
        app.launchEnvironment["STOCK_MONITOR_API_BASE_URL"] = "http://127.0.0.1:8000"
        app.launchEnvironment["STOCK_MONITOR_API_ENVIRONMENT"] = "debug"
        app.launchEnvironment["STOCK_MONITOR_TEST_KEYCHAIN_SERVICE"] = "com.jiale.StockMonitor.ui-tests.login-gate"
        app.launchArguments += ["-ApplePersistenceIgnoreState", "YES"]
        app.launch()

        XCTAssertTrue(app.descendants(matching: .any)["login.view"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Stock Monitor"].exists)
        XCTAssertTrue(app.buttons["登录"].exists)

        let snapshot = XCTAttachment(screenshot: app.screenshot())
        snapshot.name = "goal-m3-secure-login-gate"
        snapshot.lifetime = .keepAlways
        add(snapshot)
    }
}
