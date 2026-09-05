import Foundation
@testable import StockMonitorFeatures
import Testing

@MainActor
@Test func everyGoalFeatureHasAStableRouteAndAdminRoutesAreHidden() {
    #expect(AppRoute.allCases.count >= 30)
    #expect(!AppRoute.visible(isAdministrator: false).contains(.ibkrAdmin))
    #expect(AppRoute.visible(isAdministrator: true).contains(.ibkrAdmin))
    #expect(Set(AppRoute.allCases.map(\.rawValue)).count == AppRoute.allCases.count)
}

@MainActor
@Test func deepLinkRestoresRouteAndSymbolWithoutClientSidePrivilegeEscalation() throws {
    let user = AppNavigationModel()
    #expect(try user.handle(url: #require(URL(string: "stockmonitor://technical?symbol=aapl"))))
    #expect(user.selection == .technical)
    #expect(user.selectedSymbol == "AAPL")
    #expect(try !user.handle(url: #require(URL(string: "stockmonitor://ibkr-admin"))))

    let admin = AppNavigationModel(isAdministrator: true)
    #expect(try admin.handle(url: #require(URL(string: "stockmonitor://ibkr-admin"))))
}

@MainActor
@Test func commandSearchMatchesLocalizedTitles() {
    let model = AppNavigationModel()
    model.searchQuery = "估值"
    #expect(model.searchResults == [.valuation])
}
