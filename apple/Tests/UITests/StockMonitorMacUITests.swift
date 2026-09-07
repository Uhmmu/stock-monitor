import XCTest

final class StockMonitorMacUITests: XCTestCase {
    private struct AuditScenario {
        let route: String
        var state = "normal"
        var width = "standard"
        var appearance = "light"
        var density = "comfortable"
    }

    private let routes = [
        "overview", "watchlist", "holdings", "ai", "decisions", "calendar", "discovery", "options",
        "mood", "mood-lab", "alerts", "news", "macro", "industry", "fundamentals", "financials",
        "valuation", "compare", "technical", "sec", "ownership", "congress", "reports", "journal",
        "settings", "administration", "ibkr", "ibkr-admin", "crypto-research", "quant-backtests", "paper",
    ]

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

    @MainActor
    func testReadabilityRouteBaselineMatrix() {
        for route in routes {
            let app = visualAuditApp(route: route)
            app.launch()
            XCTAssertTrue(
                app.descendants(matching: .any)["visual-audit.\(route).normal"].waitForExistence(timeout: 5),
                "Missing visual audit root for \(route)"
            )
            attachScreenshot(of: app, name: "r1-route-\(route)-standard-light-comfortable-normal")
            app.terminate()
        }
    }

    @MainActor
    func testReadabilityGoldenAndFailureMatrix() {
        let scenarios: [AuditScenario] = [
            .init(route: "overview", width: "narrow"),
            .init(route: "financials", state: "partial", density: "compact"),
            .init(route: "news", state: "stale", width: "wide", appearance: "dark"),
            .init(route: "ibkr", state: "error", appearance: "dark", density: "compact"),
            .init(route: "watchlist", state: "empty", width: "narrow", appearance: "dark"),
            .init(route: "reports", state: "loading", width: "wide", density: "compact"),
            .init(route: "administration", state: "permissionDenied"),
        ]
        for scenario in scenarios {
            let app = visualAuditApp(
                route: scenario.route,
                state: scenario.state,
                width: scenario.width,
                appearance: scenario.appearance,
                density: scenario.density
            )
            app.launch()
            XCTAssertTrue(
                app.descendants(matching: .any)["visual-audit.\(scenario.route).\(scenario.state)"].waitForExistence(timeout: 5)
            )
            attachScreenshot(
                of: app,
                name: "r1-golden-\(scenario.route)-\(scenario.width)-\(scenario.appearance)-\(scenario.density)-\(scenario.state)"
            )
            app.terminate()
        }
    }

    private func visualAuditApp(
        route: String,
        state: String = "normal",
        width: String = "standard",
        appearance: String = "light",
        density: String = "comfortable"
    ) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["--visual-audit", "-ApplePersistenceIgnoreState", "YES"]
        app.launchEnvironment["STOCK_MONITOR_API_BASE_URL"] = "http://127.0.0.1:8000"
        app.launchEnvironment["STOCK_MONITOR_API_ENVIRONMENT"] = "debug"
        app.launchEnvironment["STOCK_MONITOR_VISUAL_AUDIT_ROUTE"] = route
        app.launchEnvironment["STOCK_MONITOR_VISUAL_AUDIT_STATE"] = state
        app.launchEnvironment["STOCK_MONITOR_VISUAL_AUDIT_WIDTH"] = width
        app.launchEnvironment["STOCK_MONITOR_VISUAL_AUDIT_APPEARANCE"] = appearance
        app.launchEnvironment["STOCK_MONITOR_VISUAL_AUDIT_DENSITY"] = density
        return app
    }

    private func attachScreenshot(of app: XCUIApplication, name: String) {
        let snapshot = XCTAttachment(screenshot: app.screenshot())
        snapshot.name = name
        snapshot.lifetime = .keepAlways
        add(snapshot)
    }
}
