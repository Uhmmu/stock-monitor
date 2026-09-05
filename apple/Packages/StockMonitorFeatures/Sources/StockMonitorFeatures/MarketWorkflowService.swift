import Foundation
import StockMonitorCore

public actor MarketWorkflowService {
    private let authSession: AuthSession
    private let streamCoordinator: MarketStreamCoordinator
    private let decoder = JSONDecoder()

    public init(authSession: AuthSession, streamCoordinator: MarketStreamCoordinator = MarketStreamCoordinator()) {
        self.authSession = authSession
        self.streamCoordinator = streamCoordinator
    }

    public func dashboard() async throws -> DashboardSnapshot {
        try await authSession.authorizedGet(DashboardSnapshot.self, path: "/api/dashboard")
    }

    public func indices() async throws -> IndicesSnapshot {
        try await authSession.authorizedGet(IndicesSnapshot.self, path: "/api/indices")
    }

    public func portfolioBenchmark() async throws -> PortfolioBenchmark {
        try await authSession.authorizedGet(PortfolioBenchmark.self, path: "/api/portfolio/benchmark")
    }

    public func realtimeQuotes(symbols: [String]) async throws -> [RealtimeQuote] {
        struct Response: Decodable, Sendable { let quotes: [RealtimeQuote] }
        let response = try await authSession.authorizedGet(
            Response.self,
            path: "/api/market/realtime",
            queryItems: [URLQueryItem(name: "symbols", value: symbols.joined(separator: ","))]
        )
        return response.quotes
    }

    public func quoteEvents(symbols: [String]) async throws -> AsyncStream<RealtimeQuote> {
        let normalized = Set(symbols.map { $0.uppercased() })
        let request = try await authSession.authorizedSSERequest(
            path: "/api/market/realtime/stream",
            queryItems: [URLQueryItem(name: "symbols", value: normalized.sorted().joined(separator: ","))]
        )
        let source = await streamCoordinator.subscribe()
        await streamCoordinator.connect(request: request, symbols: normalized)
        let decoder = decoder
        return AsyncStream { continuation in
            let task = Task {
                var ordering = MarketEventOrderingGate()
                for await event in source where event.event == "quote_update" && ordering.accepts(event) {
                    if let quote = try? decoder.decode(RealtimeQuote.self, from: Data(event.data.utf8)) {
                        continuation.yield(quote)
                    }
                }
                continuation.finish()
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    public func stopQuoteEvents() async {
        await streamCoordinator.disconnect()
    }

    public func stockManagement() async throws -> StockManagementSnapshot {
        try await authSession.authorizedGet(StockManagementSnapshot.self, path: "/api/stock-management")
    }

    public func watchlist() async throws -> [WatchlistItem] {
        try await authSession.authorizedGet([WatchlistItem].self, path: "/api/watchlist")
    }

    public func searchSecurities(_ query: String) async throws -> [SecurityCandidate] {
        let response = try await authSession.authorizedGet(
            SecuritySearchResult.self,
            path: "/api/securities/search",
            queryItems: [URLQueryItem(name: "q", value: query), URLQueryItem(name: "limit", value: "8")]
        )
        return response.results
    }

    public func addToWatchlist(_ candidate: SecurityCandidate) async throws -> WatchlistItem {
        try await authSession.authorizedRequest(
            WatchlistItem.self,
            path: "/api/watchlist",
            method: .post,
            body: WatchlistCreateRequest(candidate: candidate),
            idempotent: true
        )
    }

    public func updateWatchlist(id: Int, update: WatchlistUpdateRequest) async throws -> WatchlistItem {
        try await authSession.authorizedRequest(
            WatchlistItem.self,
            path: "/api/watchlist/\(id)",
            method: .patch,
            body: update,
            idempotent: true
        )
    }

    public func removeFromWatchlist(id: Int) async throws {
        try await authSession.authorizedRequestWithoutResponse(
            path: "/api/watchlist/\(id)", method: .delete, body: String?.none, idempotent: true
        )
    }

    public func createGroup(name: String) async throws -> StockGroup {
        try await authSession.authorizedRequest(
            StockGroup.self, path: "/api/stock-groups", method: .post,
            body: StockGroupRequest(name: name), idempotent: true
        )
    }

    public func renameGroup(id: Int, name: String) async throws -> StockGroup {
        try await authSession.authorizedRequest(
            StockGroup.self, path: "/api/stock-groups/\(id)", method: .patch,
            body: StockGroupRequest(name: name), idempotent: true
        )
    }

    public func deleteGroup(id: Int) async throws {
        try await authSession.authorizedRequestWithoutResponse(
            path: "/api/stock-groups/\(id)", method: .delete, body: String?.none, idempotent: true
        )
    }

    public func peers(for symbol: String) async throws -> PeerList {
        try await authSession.authorizedGet(PeerList.self, path: "/api/peers/\(symbol)")
    }

    public func addPeer(to symbol: String, candidate: SecurityCandidate) async throws {
        _ = try await authSession.authorizedRequest(
            PeerMutationResponse.self, path: "/api/peers/\(symbol)", method: .post,
            body: WatchlistCreateRequest(candidate: candidate), idempotent: true
        )
    }

    public func removePeer(from symbol: String, peer: String) async throws {
        try await authSession.authorizedRequestWithoutResponse(
            path: "/api/peers/\(symbol)/\(peer)", method: .delete, body: String?.none, idempotent: true
        )
    }

    public func setOfficialPeerExcluded(base: String, peer: String, excluded: Bool) async throws {
        if excluded {
            _ = try await authSession.authorizedRequest(
                MutationStatus.self, path: "/api/peers/\(base)/\(peer)/exclude",
                method: .post, body: EmptyRequest(), idempotent: true
            )
        } else {
            try await authSession.authorizedRequestWithoutResponse(
                path: "/api/peers/\(base)/\(peer)/exclude", method: .delete,
                body: String?.none, idempotent: true
            )
        }
    }

    public func alerts(offset: Int = 0, limit: Int = 40) async throws -> [MovementAlert] {
        try await authSession.authorizedGet(
            [MovementAlert].self,
            path: "/api/alerts",
            queryItems: [URLQueryItem(name: "offset", value: String(offset)), URLQueryItem(name: "limit", value: String(limit))]
        )
    }

    public func investigations(offset: Int = 0, limit: Int = 40) async throws -> [InvestigationItem] {
        try await authSession.authorizedGet(
            [InvestigationItem].self,
            path: "/api/investigations",
            queryItems: [URLQueryItem(name: "offset", value: String(offset)), URLQueryItem(name: "limit", value: String(limit))]
        )
    }

    public func marketNews(offset: Int = 0, limit: Int = 40, topic: String? = nil) async throws -> MarketNewsPage {
        var query = [URLQueryItem(name: "offset", value: String(offset)), URLQueryItem(name: "limit", value: String(limit))]
        if let topic, !topic.isEmpty {
            query.append(URLQueryItem(name: "topic", value: topic))
        }
        return try await authSession.authorizedGet(MarketNewsPage.self, path: "/api/news/market", queryItems: query)
    }

    public func companyNews(symbol: String, offset: Int = 0, limit: Int = 40) async throws -> [NewsItem] {
        try await authSession.authorizedGet(
            [NewsItem].self,
            path: "/api/news",
            queryItems: [
                URLQueryItem(name: "ticker", value: symbol), URLQueryItem(name: "offset", value: String(offset)),
                URLQueryItem(name: "limit", value: String(limit)),
            ]
        )
    }

    public func requestSummary(newsID: Int) async throws -> NewsItem {
        try await authSession.authorizedRequest(
            NewsItem.self, path: "/api/news/\(newsID)/summarize", method: .post,
            body: EmptyRequest(), idempotent: true
        )
    }

    public func calendar(cursor: Int = 0, limit: Int = 40, relevantOnly: Bool = true) async throws -> CalendarPage {
        try await authSession.authorizedGet(
            CalendarPage.self,
            path: "/api/calendar/events",
            queryItems: [
                URLQueryItem(name: "cursor", value: String(cursor)), URLQueryItem(name: "limit", value: String(limit)),
                URLQueryItem(name: "relevant_only", value: relevantOnly ? "true" : "false"),
            ]
        )
    }

    public func reports(offset: Int = 0, limit: Int = 40) async throws -> [ReportSummary] {
        try await authSession.authorizedGet(
            [ReportSummary].self,
            path: "/api/reports",
            queryItems: [URLQueryItem(name: "offset", value: String(offset)), URLQueryItem(name: "limit", value: String(limit))]
        )
    }

    public func report(id: Int) async throws -> ReportDetail {
        try await authSession.authorizedGet(ReportDetail.self, path: "/api/reports/\(id)")
    }
}

private struct EmptyRequest: Encodable, Sendable {}
