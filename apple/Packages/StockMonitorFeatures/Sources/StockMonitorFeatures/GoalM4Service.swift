import Foundation
import StockMonitorCore

/// Goal M4 研究工作台数据边界：全部读取现有认证 REST 契约，不新增服务端端点。
public actor ResearchWorkspaceService {
    private let authSession: AuthSession

    public init(authSession: AuthSession) {
        self.authSession = authSession
    }

    // MARK: M4.0 公司财务、估值、SEC 与对比

    public func fundamentals(ticker: String) async throws -> FundamentalsResponse {
        try await authSession.authorizedGet(
            FundamentalsResponse.self, path: "/api/fundamentals",
            queryItems: [URLQueryItem(name: "ticker", value: ticker)]
        )
    }

    public func financials(ticker: String) async throws -> [QuarterlyFinancialRow] {
        try await authSession.authorizedGet(
            [QuarterlyFinancialRow].self, path: "/api/financials",
            queryItems: [URLQueryItem(name: "ticker", value: ticker)]
        )
    }

    public func financialStatements(ticker: String, frequency: String) async throws -> FinancialStatementPage {
        let rows = try await authSession.authorizedGet(
            [FinancialStatementRow].self, path: "/api/financial-statements",
            queryItems: [URLQueryItem(name: "ticker", value: ticker), URLQueryItem(name: "frequency", value: frequency)]
        )
        return FinancialStatementPage(frequency: frequency, rows: rows)
    }

    public func crossModel(ticker: String) async throws -> ValuationCrossModel {
        try await authSession.authorizedGet(
            ValuationCrossModel.self, path: "/api/cross-model",
            queryItems: [URLQueryItem(name: "ticker", value: ticker)]
        )
    }

    public func refreshCrossModel(ticker: String) async throws -> MutationStatus {
        try await authSession.authorizedRequest(
            MutationStatus.self, path: "/api/cross-model/refresh", method: .post,
            body: EmptyRequestBody(), queryItems: [URLQueryItem(name: "ticker", value: ticker)], idempotent: true
        )
    }

    public func grahamOverrides(ticker: String, request: GrahamOverrideRequest) async throws -> JSONValue {
        try await authSession.authorizedRequest(
            JSONValue.self, path: "/api/cross-model/graham", method: .post,
            body: request, queryItems: [URLQueryItem(name: "ticker", value: ticker)], idempotent: true
        )
    }

    public func valuationHistory(ticker: String, range: String) async throws -> ValuationHistoryResponse {
        try await authSession.authorizedGet(
            ValuationHistoryResponse.self, path: "/api/valuation/history",
            queryItems: [URLQueryItem(name: "ticker", value: ticker), URLQueryItem(name: "range", value: range)]
        )
    }

    public func secFilings(ticker: String) async throws -> [SecFilingItem] {
        try await authSession.authorizedGet(
            [SecFilingItem].self, path: "/api/sec-filings",
            queryItems: [URLQueryItem(name: "ticker", value: ticker)]
        )
    }

    public func refreshSecFilings(ticker: String) async throws -> MutationStatus {
        try await authSession.authorizedRequest(
            MutationStatus.self, path: "/api/sec-filings/refresh", method: .post,
            body: EmptyRequestBody(), queryItems: [URLQueryItem(name: "ticker", value: ticker)], idempotent: true
        )
    }

    public func secEvents(ticker: String) async throws -> [SecEventItem] {
        try await authSession.authorizedGet(
            [SecEventItem].self, path: "/api/sec-events",
            queryItems: [URLQueryItem(name: "ticker", value: ticker)]
        )
    }

    public func secFinancials(ticker: String) async throws -> [SecFinancialRow] {
        try await authSession.authorizedGet(
            [SecFinancialRow].self, path: "/api/sec-financials",
            queryItems: [URLQueryItem(name: "ticker", value: ticker)]
        )
    }

    public func secInsider(ticker: String) async throws -> [SecInsiderItem] {
        try await authSession.authorizedGet(
            [SecInsiderItem].self, path: "/api/sec-insider",
            queryItems: [URLQueryItem(name: "ticker", value: ticker)]
        )
    }

    public func sec13F(ticker: String) async throws -> Sec13FPage {
        try await authSession.authorizedGet(
            Sec13FPage.self, path: "/api/sec-13f",
            queryItems: [URLQueryItem(name: "ticker", value: ticker)]
        )
    }

    /// 公司研究页的证券集合：服务端对研究端点做全局自选门控
    /// （`_require_watched_ticker`），未入库代码一律 404，因此默认代码必须来自自选列表。
    public func watchlistSymbols() async throws -> [String] {
        let items = try await authSession.authorizedGet([WatchlistItem].self, path: "/api/watchlist")
        return items.compactMap(\.ticker).filter { !$0.isEmpty }
    }

    /// 公司头上下文（R4.2）：既有 dashboard 只读契约，市场状态与自选行情一次拉取。
    public func dashboardSnapshot() async throws -> DashboardSnapshot {
        try await authSession.authorizedGet(DashboardSnapshot.self, path: "/api/dashboard")
    }

    public func companyProfile(symbol: String) async throws -> CompanyProfileOut {
        try await authSession.authorizedGet(CompanyProfileOut.self, path: "/api/company-profile/\(symbol)")
    }

    public func congressTrades(ticker: String) async throws -> [CongressTradeItem] {
        try await authSession.authorizedGet(
            [CongressTradeItem].self, path: "/api/congress/trades",
            queryItems: [URLQueryItem(name: "ticker", value: ticker)]
        )
    }

    public func congressFigures() async throws -> [CongressFigure] {
        try await authSession.authorizedGet([CongressFigure].self, path: "/api/congress/figures")
    }

    public func congressFigure(slug: String) async throws -> CongressFigureDetail {
        try await authSession.authorizedGet(CongressFigureDetail.self, path: "/api/congress/figure/\(slug)")
    }

    public func compareCatalog() async throws -> CompareCatalog {
        try await authSession.authorizedGet(CompareCatalog.self, path: "/api/compare/metrics")
    }

    public func compare(symbols: [String]) async throws -> CompareRun {
        try await authSession.authorizedRequest(
            CompareRun.self, path: "/api/compare", method: .post,
            body: CompareSymbolsRequest(symbols: symbols), idempotent: true
        )
    }

    public func compareHistory(symbols: [String], metricKey: String) async throws -> CompareHistoryResponse {
        try await authSession.authorizedRequest(
            CompareHistoryResponse.self, path: "/api/compare/history", method: .post,
            body: CompareHistoryRequest(symbols: symbols, metricKey: metricKey), idempotent: true
        )
    }

    // MARK: M4.1 技术分析与原生图表

    public func technicalAnalysis(symbol: String) async throws -> TechnicalAnalysisDetail {
        try await authSession.authorizedGet(TechnicalAnalysisDetail.self, path: "/api/technical-analysis/\(symbol)")
    }

    public func createPriceAlert(symbol: String, targetPrice: Double, direction: String) async throws -> TechnicalPriceAlert {
        try await authSession.authorizedRequest(
            TechnicalPriceAlert.self, path: "/api/technical-analysis/\(symbol)/price-alerts", method: .post,
            body: TechnicalPriceAlertRequest(targetPrice: targetPrice, direction: direction), idempotent: true
        )
    }

    public func deletePriceAlert(symbol: String, alertID: Int) async throws {
        try await authSession.authorizedRequestWithoutResponse(
            path: "/api/technical-analysis/\(symbol)/price-alerts/\(alertID)",
            method: .delete, body: String?.none, idempotent: true
        )
    }

    // MARK: M4.2 宏观、行业、期权、Mood

    public func macroOverview() async throws -> MacroOverview {
        try await authSession.authorizedGet(MacroOverview.self, path: "/api/fundamentals/macro/us/overview")
    }

    public func macroSeries() async throws -> [MacroSeriesRow] {
        try await authSession.authorizedGet([MacroSeriesRow].self, path: "/api/fundamentals/macro/us/series")
    }

    public func macroSeriesDetail(key: String, limit: Int = 500) async throws -> MacroSeriesDetail {
        try await authSession.authorizedGet(
            MacroSeriesDetail.self, path: "/api/fundamentals/macro/us/series/\(key)",
            queryItems: [URLQueryItem(name: "limit", value: String(limit))]
        )
    }

    public func macroYieldCurve() async throws -> MacroYieldCurve {
        try await authSession.authorizedGet(MacroYieldCurve.self, path: "/api/fundamentals/macro/us/yield-curve")
    }

    public func macroSyncStatus() async throws -> MacroSyncStatus {
        try await authSession.authorizedGet(MacroSyncStatus.self, path: "/api/fundamentals/macro/us/sync-status")
    }

    public func industryOverview(rangeDays: Int) async throws -> IndustryPulseOverview {
        try await authSession.authorizedGet(
            IndustryPulseOverview.self, path: "/api/industry-pulse/overview",
            queryItems: [URLQueryItem(name: "range", value: String(rangeDays))]
        )
    }

    public func industryFocus(rangeDays: Int) async throws -> IndustryFocusPayload {
        try await authSession.authorizedGet(
            IndustryFocusPayload.self, path: "/api/industry-pulse/focus",
            queryItems: [URLQueryItem(name: "range", value: String(rangeDays))]
        )
    }

    public func industryAIChain(rangeDays: Int) async throws -> IndustryAIPayload {
        try await authSession.authorizedGet(
            IndustryAIPayload.self, path: "/api/industry-pulse/ai-chain",
            queryItems: [URLQueryItem(name: "range", value: String(rangeDays))]
        )
    }

    public func industryStatus() async throws -> IndustrySystemStatus {
        try await authSession.authorizedGet(IndustrySystemStatus.self, path: "/api/industry-pulse/status")
    }

    public func industryNode(nodeID: Int, rangeDays: Int) async throws -> IndustryPulseItem {
        try await authSession.authorizedGet(
            IndustryPulseItem.self, path: "/api/industry-pulse/nodes/\(nodeID)",
            queryItems: [URLQueryItem(name: "range", value: String(rangeDays))]
        )
    }

    public func optionsOverview(ranking: String = "activity") async throws -> OptionsOverview {
        try await authSession.authorizedGet(
            OptionsOverview.self, path: "/api/options/overview",
            queryItems: [URLQueryItem(name: "ranking", value: ranking)]
        )
    }

    public func optionDetail(symbol: String, expiration: String? = nil) async throws -> OptionDetailResponse {
        var query: [URLQueryItem] = []
        if let expiration, !expiration.isEmpty {
            query.append(URLQueryItem(name: "expiration", value: expiration))
        }
        return try await authSession.authorizedGet(
            OptionDetailResponse.self, path: "/api/options/symbols/\(symbol)", queryItems: query
        )
    }

    public func optionHistory(symbol: String, days: Int = 365) async throws -> OptionHistoryEnvelope {
        try await authSession.authorizedGet(
            OptionHistoryEnvelope.self, path: "/api/options/symbols/\(symbol)/history",
            queryItems: [URLQueryItem(name: "days", value: String(days))]
        )
    }

    public func moodOverview(rangeDays: Int = 20) async throws -> MoodOverview {
        try await authSession.authorizedGet(
            MoodOverview.self, path: "/api/mood/overview",
            queryItems: [URLQueryItem(name: "range", value: String(rangeDays))]
        )
    }

    public func moodDetail(scopeType: String, scopeKey: String, rangeDays: Int = 60) async throws -> MoodHistoryResponse {
        try await authSession.authorizedGet(
            MoodHistoryResponse.self, path: "/api/mood/\(scopeType)/\(scopeKey)",
            queryItems: [URLQueryItem(name: "range", value: String(rangeDays))]
        )
    }

    public func moodHistoryHealth(days: Int = 60) async throws -> MoodHistoryHealth {
        try await authSession.authorizedGet(
            MoodHistoryHealth.self, path: "/api/mood/history-health",
            queryItems: [URLQueryItem(name: "days", value: String(days))]
        )
    }

    public func moodHistoryGaps(days: Int = 60) async throws -> MoodHistoryGaps {
        try await authSession.authorizedGet(
            MoodHistoryGaps.self, path: "/api/mood/history-gaps",
            queryItems: [URLQueryItem(name: "days", value: String(days))]
        )
    }

    public func recoverMoodHistory(request: MoodRecoveryRequest) async throws -> JSONValue {
        try await authSession.authorizedRequest(
            JSONValue.self, path: "/api/mood/history-recovery", method: .post, body: request, idempotent: false
        )
    }

    public func moodPriceHistory(symbol: String, days: Int = 180) async throws -> MoodPriceHistory {
        try await authSession.authorizedGet(
            MoodPriceHistory.self, path: "/api/mood/price-history/\(symbol)",
            queryItems: [URLQueryItem(name: "days", value: String(days))]
        )
    }

    // MARK: 管理员 Mood Lab

    public func moodLabOverview(runID: Int? = nil) async throws -> MoodValidationOverview {
        var query: [URLQueryItem] = []
        if let runID {
            query.append(URLQueryItem(name: "run_id", value: String(runID)))
        }
        return try await authSession.authorizedGet(MoodValidationOverview.self, path: "/api/mood-lab/overview", queryItems: query)
    }

    public func moodLabRuns(limit: Int = 20) async throws -> MoodValidationRunsResponse {
        try await authSession.authorizedGet(
            MoodValidationRunsResponse.self, path: "/api/mood-lab/runs",
            queryItems: [URLQueryItem(name: "limit", value: String(limit))]
        )
    }

    public func startMoodLabRun(request: MoodValidationRunRequest) async throws -> MoodValidationRun {
        try await authSession.authorizedRequest(
            MoodValidationRun.self, path: "/api/mood-lab/runs", method: .post, body: request, idempotent: false
        )
    }

    public func moodLabResults(runID: Int) async throws -> MoodValidationResultsResponse {
        try await authSession.authorizedGet(MoodValidationResultsResponse.self, path: "/api/mood-lab/runs/\(runID)/results")
    }
}

struct EmptyRequestBody: Encodable, Sendable {}

struct CompareSymbolsRequest: Encodable, Sendable {
    let symbols: [String]
}

struct CompareHistoryRequest: Encodable, Sendable {
    let symbols: [String]
    let metricKey: String

    enum CodingKeys: String, CodingKey {
        case symbols
        case metricKey = "metric_key"
    }
}

public struct OptionHistoryEnvelope: Codable, Equatable, Sendable {
    public let symbol: String?
    public let history: [OptionHistoryPoint]?
    public let count: Int?
    public let status: String?
    public let historicalComparison: JSONValue?

    enum CodingKeys: String, CodingKey {
        case symbol, history, count, status
        case historicalComparison = "historical_comparison"
    }
}
