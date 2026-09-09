import Foundation
import Testing

@Test func macOSWorkspaceNavigationKeepsOneWindowSplitOwner() throws {
    let packageRoot = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
    let sources = packageRoot.appendingPathComponent("Sources/StockMonitorFeatures")
    let appShell = try String(
        contentsOf: sources.appendingPathComponent("AppShell.swift"),
        encoding: .utf8
    )
    let workspaceViews = try String(
        contentsOf: sources.appendingPathComponent("GoalM5Views.swift"),
        encoding: .utf8
    )
    let secondarySplit = try String(
        contentsOf: sources.appendingPathComponent("SecondaryNavigationSplit.swift"),
        encoding: .utf8
    )

    #expect(appShell.components(separatedBy: "NavigationSplitView(").count - 1 == 1)
    #expect(workspaceViews.components(separatedBy: "SecondaryNavigationSplit(").count - 1 == 3)
    #expect(secondarySplit.contains("HSplitView"))
    #expect(secondarySplit.components(separatedBy: "NavigationSplitView {").count - 1 == 1)
}
