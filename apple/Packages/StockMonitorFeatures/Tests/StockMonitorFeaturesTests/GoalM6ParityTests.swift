@testable import StockMonitorFeatures
import Testing

@MainActor
@Test func parityCatalogAccountsForEveryNativeRouteExactlyOnce() {
    let entries = GoalM6ParityCatalog.entries
    #expect(entries.count == AppRoute.allCases.count)
    #expect(Set(entries.map(\.macRoute)) == Set(AppRoute.allCases))
    #expect(Set(entries.map(\.macRoute)).count == entries.count)
    #expect(entries.allSatisfy { !$0.webSurface.isEmpty })
}

@MainActor
@Test func parityCatalogAndNavigationAgreeOnRoleGatedSurfaces() {
    for entry in GoalM6ParityCatalog.entries {
        #expect(entry.administratorOnly == entry.macRoute.requiresAdministrator)
    }
}

@MainActor
@Test func noRouteFallsBackToTheGoalTwoPlaceholderAfterGoalFive() {
    for route in AppRoute.allCases {
        #expect(route.isGoalM3Route || route.isGoalM4Route || route.isGoalM5Route)
    }
}
