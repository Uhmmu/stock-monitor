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
    #expect(model.searchResults.map(\.route) == [.valuation])
    #expect(model.searchResults.first?.context == AppSection.company.title)
}

@MainActor
@Test func commandSearchGroupsFunctionsStocksConversationsAndReports() {
    let model = AppNavigationModel()
    model.selectedSymbol = "AAPL"
    model.replaceSearchIndex(
        securities: [.init(kind: .security, title: "NVDA", context: "NVIDIA", route: .fundamentals, symbol: "NVDA")],
        conversations: [.init(kind: .conversation, title: "苹果研究", context: "AI Chat · 会话 #7", route: .ai, symbol: nil)],
        reports: [.init(kind: .report, title: "AAPL 日报", context: "AAPL · 2026-09-09", route: .reports, symbol: "AAPL")]
    )
    model.searchQuery = ""
    #expect(Set(model.groupedSearchResults.map(\.0)) == Set(NavigationSearchKind.allCases))

    model.searchQuery = "MSFT"
    let stock = model.searchResults.first { $0.kind == .security }
    #expect(stock?.title == "MSFT")
    if let stock {
        model.navigate(to: stock)
    }
    #expect(model.selection == .fundamentals)
    #expect(model.selectedSymbol == "MSFT")
}

@MainActor
@Test func favoritesRecentsOrderingAndResetAreDeterministic() {
    let model = AppNavigationModel(selection: .technical)
    #expect(model.expandedSections.contains(.company))
    model.toggleFavorite(.valuation)
    model.navigate(to: .news)
    model.navigate(to: .valuation)
    #expect(model.favorites == [.valuation])
    #expect(model.recents == [.valuation, .news])

    let original = model.routes(in: .company)
    model.moveRoutes(in: .company, from: IndexSet(integer: 0), to: original.count)
    #expect(model.routes(in: .company).last == original.first)

    model.resetNavigationLayout()
    #expect(model.favorites.isEmpty)
    #expect(model.recents.isEmpty)
    #expect(model.routeOrder == AppRoute.allCases)
    #expect(model.expandedSections.contains(.assets))
}

@MainActor
@Test func navigationNeverRestoresAdministratorRoutesForARegularUser() {
    let model = AppNavigationModel(
        favorites: [.overview, .administration],
        recents: [.ibkrAdmin, .news],
        routeOrder: [.administration, .overview]
    )
    #expect(model.favorites == [.overview])
    #expect(model.recents == [.news])
    #expect(!model.routes(in: .records).contains(.administration))
}

@MainActor
@Test func routeInteractionStateSurvivesNavigationAndResetsWithLayout() {
    let model = AppNavigationModel(selection: .watchlist)
    model.updateState(for: .watchlist) {
        $0.selectedIdentifier = "1578.T"
        $0.filterQuery = "7"
        $0.sortKey = "change"
        $0.scrollAnchor = "row-1578.T"
    }
    model.navigate(to: .news)
    model.updateState(for: .news) { $0.filterQuery = "市场|AAPL|earnings" }
    model.navigate(to: .watchlist)

    #expect(model.state(for: .watchlist).selectedIdentifier == "1578.T")
    #expect(model.state(for: .watchlist).sortKey == "change")
    #expect(model.state(for: .news).filterQuery == "市场|AAPL|earnings")

    model.resetNavigationLayout()
    #expect(model.routeStates.isEmpty)
}

@Test func r7InteractionAuditCoversEveryRouteWithRecoverableBehavior() {
    #expect(R7InteractionAuditCatalog.entries.count == AppRoute.allCases.count)
    #expect(Set(R7InteractionAuditCatalog.entries.map(\.route)) == Set(AppRoute.allCases))
    #expect(R7InteractionAuditCatalog.entries.allSatisfy { !$0.primaryAction.isEmpty })
    #expect(R7InteractionAuditCatalog.entries.allSatisfy { $0.failureRecovery.contains("重试") })
    #expect(R7InteractionAuditCatalog.entry(for: .watchlist).retainedState.contains("选中证券"))
    #expect(R7InteractionAuditCatalog.entry(for: .news).detailPattern.contains("Sheet"))
}
