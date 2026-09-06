import Foundation
import StockMonitorCore
@testable import StockMonitorFeatures
import Testing

@Test func everyGoalM5RouteIsBoundAndAdminRoutesStayHidden() {
    let routes: [AppRoute] = [
        .ai, .decisions, .discovery, .holdings, .journal, .settings, .administration,
        .ibkr, .ibkrAdmin, .cryptoResearch, .quantBacktests, .paper,
    ]
    for route in routes {
        #expect(route.isGoalM5Route)
    }
    #expect(!AppRoute.overview.isGoalM5Route)
    #expect(!AppRoute.visible(isAdministrator: false).contains(.administration))
    #expect(!AppRoute.visible(isAdministrator: false).contains(.ibkrAdmin))
}

@Test func catalogCoversAllThreePhasesAndUsesOnlyInternalPaper() {
    let catalog = GoalM5Catalog()
    #expect(catalog.decisions.phase == .ai)
    #expect(catalog.portfolio.phase == .portfolio)
    #expect(catalog.paper.phase == .crypto)
    let paperText = catalog.paper.actions.map(\.path).joined(separator: " ").lowercased()
    #expect(paperText.contains("/api/crypto/quant/paper"))
    #expect(!paperText.contains("binance"))
    #expect(!paperText.contains("live"))
    #expect(catalog.ibkr.securityNotice?.contains("socks5h") == true)
}

@Test func nonAdminCatalogDropsRoleGatedOperationsEvenWhenDescriptorIsRequestedDirectly() throws {
    let catalog = GoalM5Catalog()
    let userView = try #require(catalog.descriptor(for: .administration, isAdministrator: false))
    #expect(userView.endpoints.isEmpty)
    #expect(userView.actions.isEmpty)
    let adminView = try #require(catalog.descriptor(for: .administration, isAdministrator: true))
    #expect(!adminView.endpoints.isEmpty)
    let allAdministratorOnly = adminView.endpoints.allSatisfy(\.administratorOnly)
    #expect(allAdministratorOnly)
}

@Test func representativeM5ServerPayloadsPreserveGapsAndAuthoritativeState() throws {
    let portfolioFixture = Data(
        #"{"base_currency":"USD","valuation_available":false,"missing_fx":["JPY"],"total_market_value":null}"#.utf8
    )
    let portfolio = try JSONDecoder().decode(JSONValue.self, from: portfolioFixture)
    #expect(portfolio.objectValue["valuation_available"]?.boolValue == false)
    #expect(portfolio.objectValue["total_market_value"] == .null)

    let paperFixture = Data(#"{"mode":"PAPER","ledger":{"status":"reconciled"},"live_trading":false}"#.utf8)
    let paper = try JSONDecoder().decode(JSONValue.self, from: paperFixture)
    #expect(paper.objectValue["mode"]?.stringValue == "PAPER")
    #expect(paper.objectValue["live_trading"]?.boolValue == false)

    let ibkrFixture = Data(#"{"available":true,"account_id_masked":"***1234","warnings":[]}"#.utf8)
    let ibkr = try JSONDecoder().decode(JSONValue.self, from: ibkrFixture)
    #expect(ibkr.objectValue["account_id_masked"]?.stringValue == "***1234")
}

@Test func aiRequestsEncodeServerFieldNamesAndNoCredentialFields() throws {
    let request = AIMessageRequest(message: "解释风险", model: nil, webAccessMode: "search", activeSymbol: "AAPL")
    let data = try JSONEncoder().encode(request)
    let object = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    #expect(object["web_access_mode"] as? String == "search")
    #expect(object["active_symbol"] as? String == "AAPL")
    #expect(object["stream"] as? Bool == true)
    #expect(object["deep_search_confirmed"] as? Bool == false)
    let containsSensitiveField = object.keys.contains {
        $0.localizedCaseInsensitiveContains("password") || $0.localizedCaseInsensitiveContains("proxy")
    }
    #expect(!containsSensitiveField)
}

@Test func allReadEndpointsRemainAuthenticatedAPIPaths() {
    let catalog = GoalM5Catalog()
    let descriptors = [
        catalog.decisions, catalog.discovery, catalog.portfolio, catalog.journal,
        catalog.ibkr, catalog.ibkrAdmin, catalog.cryptoResearch, catalog.quant,
        catalog.paper, catalog.settings, catalog.administration,
    ]
    for endpoint in descriptors.flatMap(\.endpoints) {
        #expect(endpoint.path.hasPrefix("/api/"))
    }
    for action in descriptors.flatMap(\.actions) {
        #expect(action.path.hasPrefix("/api/"))
    }
}
