import Foundation
import Observation
import StockMonitorCore
import StockMonitorDesign

public enum M3FeatureError: Equatable, Sendable {
    case message(String)

    public var text: String {
        switch self { case let .message(value): value }
    }

    static func from(_ error: Error) -> M3FeatureError {
        if let api = error as? StockMonitorCore.APIError {
            switch api {
            case let .http(_, message, requestID):
                let suffix = requestID.map { "（请求 \($0)）" } ?? ""
                return .message((message ?? "服务器拒绝了请求") + suffix)
            case let .transport(code): return .message("网络连接失败（\(code)）")
            case .decoding: return .message("服务端数据契约不兼容")
            default: return .message("请求未完成")
            }
        }
        return .message("请求未完成：\(error.localizedDescription)")
    }
}

@MainActor
@Observable
public final class OverviewModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var dashboard: DashboardSnapshot?
    public private(set) var indices: [MarketIndex] = []
    public private(set) var benchmark: PortfolioBenchmark?
    public private(set) var alerts: [MovementAlert] = []
    public private(set) var investigations: [InvestigationItem] = []
    public private(set) var reports: [ReportSummary] = []
    public private(set) var liveQuotes: [String: RealtimeQuote] = [:]
    public private(set) var streamConnected = false
    public private(set) var error: M3FeatureError?
    public private(set) var lastUpdated: Date?
    private let service: MarketWorkflowService
    private var streamTask: Task<Void, Never>?

    public init(service: MarketWorkflowService) {
        self.service = service
    }

    public func load() async {
        state = dashboard == nil ? .loading : .refreshing
        do {
            async let dashboard = service.dashboard()
            async let indices = service.indices()
            async let alerts = service.alerts(limit: 8)
            async let reports = service.reports(limit: 6)
            async let benchmark = service.portfolioBenchmark()
            async let investigations = service.investigations(limit: 12)
            let values = try await (dashboard, indices, alerts, reports, benchmark)
            self.dashboard = values.0
            self.indices = values.1.indices
            self.alerts = values.2
            self.reports = values.3
            self.benchmark = values.4
            // 调查状态只影响徽标；失败时保留空列表，不阻塞总览主数据。
            self.investigations = await (try? investigations) ?? []
            state = .ready
            error = nil
            lastUpdated = .now
            startStream(symbols: values.0.stocks.map(\.ticker))
        } catch {
            self.error = .from(error)
            state = dashboard == nil ? .error : .stale
        }
    }

    public func stop() {
        streamTask?.cancel()
        streamTask = nil
        streamConnected = false
        Task { await service.stopQuoteEvents() }
    }

    private func startStream(symbols: [String]) {
        streamTask?.cancel()
        guard !symbols.isEmpty else { return }
        streamTask = Task { [weak self, service] in
            do {
                let stream = try await service.quoteEvents(symbols: symbols)
                self?.streamConnected = true
                for await quote in stream {
                    guard !Task.isCancelled else { return }
                    self?.liveQuotes[quote.symbol] = quote
                }
            } catch {
                self?.streamConnected = false
                if self?.dashboard != nil {
                    self?.state = .stale
                }
            }
        }
    }
}

@MainActor
@Observable
public final class WatchlistModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var snapshot: StockManagementSnapshot?
    public private(set) var contractItems: [Int: WatchlistItem] = [:]
    public private(set) var searchResults: [SecurityCandidate] = []
    public private(set) var peers: [PeerItem] = []
    public var selectedSymbol: String?
    public var searchQuery = ""
    public private(set) var pendingIDs: Set<Int> = []
    public private(set) var error: M3FeatureError?
    private let service: MarketWorkflowService
    private var searchTask: Task<Void, Never>?

    public init(service: MarketWorkflowService) {
        self.service = service
    }

    public var stocks: [ManagedStock] {
        snapshot?.watchlisted ?? []
    }

    public func load() async {
        state = snapshot == nil ? .loading : .refreshing
        do {
            async let management = service.stockManagement()
            async let items = service.watchlist()
            let values = try await (management, items)
            snapshot = values.0
            contractItems = Dictionary(uniqueKeysWithValues: values.1.map { ($0.id, $0) })
            if selectedSymbol == nil {
                selectedSymbol = values.0.watchlisted.first?.ticker
            }
            state = .ready
            error = nil
            await loadPeers()
        } catch {
            self.error = .from(error)
            state = snapshot == nil ? .error : .stale
        }
    }

    public func search() {
        searchTask?.cancel()
        let query = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        guard query.count >= 1 else { searchResults = []; return }
        searchTask = Task { [weak self, service] in
            try? await Task.sleep(for: .milliseconds(180))
            guard !Task.isCancelled else { return }
            do { self?.searchResults = try await service.searchSecurities(query) }
            catch { self?.error = .from(error) }
        }
    }

    public func add(_ candidate: SecurityCandidate) async {
        do {
            _ = try await service.addToWatchlist(candidate)
            searchQuery = ""
            searchResults = []
            await load()
        } catch { self.error = .from(error) }
    }

    public func setAlert(_ enabled: Bool, stock: ManagedStock) async {
        guard let id = stock.watchlistID else { return }
        pendingIDs.insert(id)
        defer { pendingIDs.remove(id) }
        do {
            _ = try await service.updateWatchlist(id: id, update: WatchlistUpdateRequest(alertEnabled: enabled))
            await load()
        } catch { self.error = .from(error) }
    }

    public func setMonitoring(_ enabled: Bool, stock: ManagedStock) async {
        guard let id = stock.watchlistID else { return }
        pendingIDs.insert(id)
        defer { pendingIDs.remove(id) }
        do {
            _ = try await service.updateWatchlist(id: id, update: WatchlistUpdateRequest(enabled: enabled))
            await load()
        } catch { self.error = .from(error) }
    }

    public func move(from source: IndexSet, to destination: Int) async {
        guard var value = snapshot else { return }
        value.watchlisted.move(fromOffsets: source, toOffset: destination)
        snapshot = value
        do {
            for (order, stock) in value.watchlisted.enumerated() {
                guard let id = stock.watchlistID, stock.displayOrder != order else { continue }
                _ = try await service.updateWatchlist(id: id, update: WatchlistUpdateRequest(displayOrder: order))
            }
            await load()
        } catch {
            self.error = .from(error)
            await load()
        }
    }

    public func remove(_ stock: ManagedStock, undoManager: UndoManager?) async {
        guard let id = stock.watchlistID, let contract = contractItems[id] else { return }
        pendingIDs.insert(id)
        do {
            try await service.removeFromWatchlist(id: id)
            undoManager?.registerUndo(withTarget: self) { target in
                Task { await target.restore(contract) }
            }
            undoManager?.setActionName("移除 \(stock.ticker)")
            await load()
        } catch {
            self.error = .from(error)
            pendingIDs.remove(id)
        }
    }

    public func createGroup(_ name: String) async {
        do { _ = try await service.createGroup(name: name); await load() }
        catch { self.error = .from(error) }
    }

    public func renameGroup(_ group: StockGroup, name: String) async {
        do { _ = try await service.renameGroup(id: group.id, name: name); await load() }
        catch { self.error = .from(error) }
    }

    public func deleteGroup(_ group: StockGroup) async {
        do { try await service.deleteGroup(id: group.id); await load() }
        catch { self.error = .from(error) }
    }

    public func updateThresholds(stock: ManagedStock, twentyMinutes: Double?, oneHour: Double?, day: Double?) async {
        guard let id = stock.watchlistID else { return }
        pendingIDs.insert(id)
        defer { pendingIDs.remove(id) }
        do {
            _ = try await service.updateWatchlist(
                id: id,
                update: WatchlistUpdateRequest(
                    threshold20m: twentyMinutes, threshold1h: oneHour, thresholdDay: day,
                    includeThresholds: true
                )
            )
            await load()
        } catch { self.error = .from(error) }
    }

    public func assign(stock: ManagedStock, to groupID: Int) async {
        guard let id = stock.watchlistID else { return }
        do { _ = try await service.updateWatchlist(id: id, update: WatchlistUpdateRequest(userGroupID: groupID)); await load() }
        catch { self.error = .from(error) }
    }

    public func loadPeers() async {
        guard let selectedSymbol else { peers = []; return }
        do { peers = try await service.peers(for: selectedSymbol).items }
        catch { peers = [] }
    }

    public func addPeer(_ candidate: SecurityCandidate) async {
        guard let selectedSymbol else { return }
        do { try await service.addPeer(to: selectedSymbol, candidate: candidate); await loadPeers() }
        catch { self.error = .from(error) }
    }

    public func togglePeer(_ peer: PeerItem) async {
        guard let selectedSymbol else { return }
        do {
            if peer.source == "manual" {
                try await service.removePeer(from: selectedSymbol, peer: peer.ticker)
            } else {
                try await service.setOfficialPeerExcluded(base: selectedSymbol, peer: peer.ticker, excluded: !peer.excluded)
            }
            await loadPeers()
        } catch { self.error = .from(error) }
    }

    private func restore(_ item: WatchlistItem) async {
        guard let securityID = item.securityID else {
            error = .message("缺少证券实体，无法撤销")
            return
        }
        let candidate = SecurityCandidate(
            providerKey: "security:\(securityID)", securityID: securityID,
            displaySymbol: item.ticker ?? "", displayName: item.ticker ?? "",
            exchange: nil, market: nil, currency: nil, instrumentType: nil,
            yahooSymbol: nil, finnhubSymbol: nil, source: "local", isLocal: true
        )
        do { _ = try await service.addToWatchlist(candidate); await load() }
        catch { self.error = .from(error) }
    }
}

@MainActor
@Observable
public final class ActivityModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var alerts: [MovementAlert] = []
    public private(set) var investigations: [InvestigationItem] = []
    public private(set) var canLoadMore = true
    public private(set) var error: M3FeatureError?
    private let service: MarketWorkflowService
    private let pageSize = 40

    public init(service: MarketWorkflowService) {
        self.service = service
    }

    public func load(reset: Bool = true) async {
        let offset = reset ? 0 : alerts.count
        state = alerts.isEmpty ? .loading : .refreshing
        do {
            async let newAlerts = service.alerts(offset: offset, limit: pageSize)
            async let newInvestigations = service.investigations(offset: reset ? 0 : investigations.count, limit: pageSize)
            let values = try await (newAlerts, newInvestigations)
            alerts = reset ? values.0 : alerts + values.0
            investigations = reset ? values.1 : investigations + values.1
            canLoadMore = values.0.count == pageSize || values.1.count == pageSize
            state = .ready; error = nil
        } catch { self.error = .from(error); state = alerts.isEmpty ? .error : .stale }
    }
}

@MainActor
@Observable
public final class NewsModel {
    public enum Scope: String, CaseIterable, Identifiable { case market = "市场"; case company = "个股"; public var id: Self {
        self
    } }
    public var scope: Scope = .market
    public var symbol = "AAPL"
    public var topic = ""
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var items: [NewsItem] = []
    public private(set) var total = 0
    public private(set) var canLoadMore = true
    public private(set) var error: M3FeatureError?
    private let service: MarketWorkflowService
    private let pageSize = 40

    public init(service: MarketWorkflowService) {
        self.service = service
    }

    public func load(reset: Bool = true) async {
        let offset = reset ? 0 : items.count
        state = items.isEmpty ? .loading : .refreshing
        do {
            let page: [NewsItem]
            if scope == .market {
                let value = try await service.marketNews(offset: offset, limit: pageSize, topic: topic)
                page = value.items; total = value.total
            } else {
                page = try await service.companyNews(symbol: symbol.uppercased(), offset: offset, limit: pageSize)
                total = offset + page.count + (page.count == pageSize ? 1 : 0)
            }
            items = reset ? page : items + page
            canLoadMore = page.count == pageSize
            state = .ready; error = nil
        } catch { self.error = .from(error); state = items.isEmpty ? .error : .stale }
    }

    public func summarize(_ item: NewsItem) async {
        do {
            let updated = try await service.requestSummary(newsID: item.id)
            if let index = items.firstIndex(where: { $0.id == item.id }) {
                items[index] = updated
            }
        } catch { self.error = .from(error) }
    }
}

@MainActor
@Observable
public final class CalendarModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var items: [CalendarEvent] = []
    public private(set) var nextCursor: Int?
    public private(set) var error: M3FeatureError?
    private let service: MarketWorkflowService

    public init(service: MarketWorkflowService) {
        self.service = service
    }

    public func load(reset: Bool = true) async {
        state = items.isEmpty ? .loading : .refreshing
        do {
            let page = try await service.calendar(cursor: reset ? 0 : nextCursor ?? items.count)
            items = reset ? page.items : items + page.items
            nextCursor = page.nextCursor
            state = .ready; error = nil
        } catch { self.error = .from(error); state = items.isEmpty ? .error : .stale }
    }
}

@MainActor
@Observable
public final class ReportsModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var reports: [ReportSummary] = []
    public private(set) var selected: ReportDetail?
    public private(set) var canLoadMore = true
    public private(set) var error: M3FeatureError?
    private let service: MarketWorkflowService
    private let pageSize = 40

    public init(service: MarketWorkflowService) {
        self.service = service
    }

    public func load(reset: Bool = true) async {
        state = reports.isEmpty ? .loading : .refreshing
        do {
            let page = try await service.reports(offset: reset ? 0 : reports.count, limit: pageSize)
            reports = reset ? page : reports + page
            canLoadMore = page.count == pageSize
            state = .ready; error = nil
        } catch { self.error = .from(error); state = reports.isEmpty ? .error : .stale }
    }

    public func select(_ summary: ReportSummary) async {
        do { selected = try await service.report(id: summary.id) }
        catch { self.error = .from(error) }
    }
}
