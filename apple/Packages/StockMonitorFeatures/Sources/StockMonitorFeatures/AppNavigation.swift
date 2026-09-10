import Foundation
import Observation

public enum AppSection: String, CaseIterable, Identifiable, Sendable {
    case assets, research, intelligence, company, records, ibkr, crypto
    public var id: Self {
        self
    }

    public var title: String {
        switch self {
        case .assets: "概览与资产"
        case .research: "研究与决策"
        case .intelligence: "市场情报"
        case .company: "公司分析"
        case .records: "记录与系统"
        case .ibkr: "IBKR"
        case .crypto: "Crypto 工作区"
        }
    }
}

public enum AppWorkspace: String, CaseIterable, Identifiable, Sendable {
    case company, portfolio, ai, crypto

    public var id: Self {
        self
    }

    public var title: String {
        switch self {
        case .company: "公司"
        case .portfolio: "组合"
        case .ai: "AI"
        case .crypto: "Crypto"
        }
    }

    public var routes: [AppRoute] {
        switch self {
        case .company: [.fundamentals, .financials, .valuation, .technical, .sec, .ownership, .congress, .compare]
        case .portfolio: [.holdings, .decisions, .journal]
        case .ai: [.ai, .discovery, .reports]
        case .crypto: [.cryptoResearch, .quantBacktests, .paper]
        }
    }
}

public enum AppRoute: String, CaseIterable, Codable, Hashable, Identifiable, Sendable {
    case overview, watchlist, holdings, ai, decisions, calendar, discovery, options
    case mood, moodLab = "mood-lab", alerts, news, macro, industry
    case fundamentals, financials, valuation, compare, technical, sec, ownership, congress
    case reports, journal, settings, administration, ibkr, ibkrAdmin = "ibkr-admin"
    case cryptoResearch = "crypto-research", quantBacktests = "quant-backtests", paper

    public var id: Self {
        self
    }

    public var section: AppSection {
        switch self {
        case .overview, .watchlist, .holdings: .assets
        case .ai, .decisions, .calendar, .discovery, .options: .research
        case .mood, .moodLab, .alerts, .news, .macro, .industry: .intelligence
        case .fundamentals, .financials, .valuation, .compare, .technical, .sec, .ownership, .congress: .company
        case .reports, .journal, .settings, .administration: .records
        case .ibkr, .ibkrAdmin: .ibkr
        case .cryptoResearch, .quantBacktests, .paper: .crypto
        }
    }

    public var title: String {
        switch self {
        case .overview: "总览"
        case .watchlist: "自选股"
        case .holdings: "持仓"
        case .ai: "Chat"
        case .decisions: "投资决策"
        case .calendar: "投资日历"
        case .discovery: "机会发现"
        case .options: "期权研究"
        case .mood: "AI 情绪台"
        case .moodLab: "Mood 验证实验室"
        case .alerts: "异动中心"
        case .news: "新闻中心"
        case .macro: "美国宏观"
        case .industry: "行业板块"
        case .fundamentals: "基本面"
        case .financials: "财务报表"
        case .valuation: "估值"
        case .compare: "个股对比"
        case .technical: "技术分析"
        case .sec: "SEC"
        case .ownership: "机构持仓"
        case .congress: "公众人物交易"
        case .reports: "报告中心"
        case .journal: "交易日志"
        case .settings: "设置"
        case .administration: "用户管理"
        case .ibkr: "IBKR"
        case .ibkrAdmin: "IBKR 管理"
        case .cryptoResearch: "Crypto 研究"
        case .quantBacktests: "量化回测"
        case .paper: "内部 PAPER"
        }
    }

    public var systemImage: String {
        switch self {
        case .overview: "rectangle.grid.2x2"
        case .watchlist: "star"
        case .holdings: "briefcase"
        case .ai: "bubble.left.and.text.bubble.right"
        case .decisions: "checklist"
        case .calendar: "calendar"
        case .discovery: "safari"
        case .options: "function"
        case .mood, .moodLab: "waveform.path.ecg"
        case .alerts: "bell"
        case .news: "newspaper"
        case .macro: "globe.americas"
        case .industry: "chart.line.uptrend.xyaxis"
        case .fundamentals: "building.2"
        case .financials: "tablecells"
        case .valuation: "scalemass"
        case .compare: "square.split.2x1"
        case .technical: "chart.xyaxis.line"
        case .sec: "doc.text.magnifyingglass"
        case .ownership: "person.3"
        case .congress: "person.crop.rectangle.stack"
        case .reports: "doc.richtext"
        case .journal: "book.closed"
        case .settings: "gearshape"
        case .administration: "person.badge.key"
        case .ibkr: "building.columns"
        case .ibkrAdmin: "wrench.and.screwdriver"
        case .cryptoResearch: "bitcoinsign.circle"
        case .quantBacktests: "point.3.connected.trianglepath.dotted"
        case .paper: "doc.text"
        }
    }

    public var requiresAdministrator: Bool {
        [.moodLab, .administration, .ibkrAdmin].contains(self)
    }

    public var workspace: AppWorkspace? {
        AppWorkspace.allCases.first { $0.routes.contains(self) }
    }

    public var isHighRiskWorkspace: Bool {
        [.administration, .ibkrAdmin, .paper].contains(self)
    }

    public var searchAliases: [String] {
        switch self {
        case .ai: ["AI", "聊天", "会话", "Chat"]
        case .reports: ["报告", "研报", "研究报告"]
        case .holdings: ["组合", "资产", "仓位"]
        case .fundamentals: ["公司", "指标", "基本面"]
        case .technical: ["图表", "K线", "技术"]
        case .cryptoResearch: ["加密", "币", "Crypto"]
        default: [title, rawValue]
        }
    }

    public var isGoalM3Route: Bool {
        [.overview, .watchlist, .alerts, .news, .calendar, .reports].contains(self)
    }

    /// Goal M4（公司研究、技术分析图表、市场情报）已接入原生页面。
    public var isGoalM4Route: Bool {
        [
            .fundamentals, .financials, .valuation, .compare, .sec, .ownership, .congress,
            .technical, .macro, .industry, .options, .mood, .moodLab,
        ].contains(self)
    }

    /// Goal M5（AI、组合、IBKR、Crypto 与系统管理）原生工作台。
    public var isGoalM5Route: Bool {
        [
            .ai, .decisions, .discovery, .holdings, .journal, .settings, .administration,
            .ibkr, .ibkrAdmin, .cryptoResearch, .quantBacktests, .paper,
        ].contains(self)
    }

    public static func visible(isAdministrator: Bool) -> [AppRoute] {
        allCases.filter { isAdministrator || !$0.requiresAdministrator }
    }
}

public struct StockDetailRoute: Codable, Hashable, Sendable {
    public let symbol: String
    public init(symbol: String) {
        self.symbol = symbol.uppercased()
    }
}

public struct ResearchDetailRoute: Codable, Hashable, Sendable {
    public let route: AppRoute
    public let identifier: String
    public init(route: AppRoute, identifier: String) {
        self.route = route
        self.identifier = identifier
    }
}

public enum NavigationSearchKind: String, CaseIterable, Identifiable, Sendable {
    case function, security, conversation, report
    public var id: Self {
        self
    }

    public var title: String {
        switch self {
        case .function: "功能"
        case .security: "股票"
        case .conversation: "会话"
        case .report: "报告"
        }
    }
}

public struct NavigationSearchResult: Identifiable, Equatable, Sendable {
    public let kind: NavigationSearchKind
    public let title: String
    public let context: String
    public let route: AppRoute
    public let symbol: String?

    public var id: String {
        "\(kind.rawValue):\(route.rawValue):\(symbol ?? title)"
    }
}

/// A small, per-window snapshot of the choices that define a route's working context.
/// Views can opt into the typed fields they own without serializing loaded business data.
public struct RouteInteractionState: Codable, Equatable, Sendable {
    public var selectedIdentifier: String?
    public var filterQuery: String
    public var sortKey: String?
    public var scrollAnchor: String?

    public init(
        selectedIdentifier: String? = nil,
        filterQuery: String = "",
        sortKey: String? = nil,
        scrollAnchor: String? = nil
    ) {
        self.selectedIdentifier = selectedIdentifier
        self.filterQuery = filterQuery
        self.sortKey = sortKey
        self.scrollAnchor = scrollAnchor
    }
}

@MainActor
@Observable
public final class AppNavigationModel {
    public var selection: AppRoute
    public var inspectorVisible = false
    public var searchPresented = false
    public var searchQuery = ""
    public var isAdministrator: Bool
    public var selectedSymbol: String?
    public var favorites: [AppRoute]
    public var recents: [AppRoute]
    public var routeOrder: [AppRoute]
    public var expandedSections: Set<AppSection>
    public var indexedSearchResults: [NavigationSearchResult] = []
    public var routeStates: [AppRoute: RouteInteractionState] = [:]

    public init(
        selection: AppRoute = .overview,
        isAdministrator: Bool = false,
        favorites: [AppRoute] = [],
        recents: [AppRoute] = [],
        routeOrder: [AppRoute] = AppRoute.allCases,
        expandedSections: Set<AppSection> = [.assets]
    ) {
        self.selection = selection
        self.isAdministrator = isAdministrator
        self.favorites = Self.uniqueVisible(favorites, isAdministrator: isAdministrator)
        self.recents = Array(Self.uniqueVisible(recents, isAdministrator: isAdministrator).prefix(6))
        let ordered = Self.uniqueVisible(routeOrder, isAdministrator: true)
        self.routeOrder = ordered + AppRoute.allCases.filter { !ordered.contains($0) }
        self.expandedSections = expandedSections.union([selection.section])
    }

    public var searchResults: [NavigationSearchResult] {
        let candidates = AppRoute.visible(isAdministrator: isAdministrator)
        let query = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        var results = candidates
            .filter { route in
                query.isEmpty || ([route.title, route.rawValue] + route.searchAliases).contains {
                    $0.localizedCaseInsensitiveContains(query)
                }
            }
            .map { NavigationSearchResult(kind: .function, title: $0.title, context: $0.section.title, route: $0, symbol: nil) }

        if Self.looksLikeTicker(query) {
            let symbol = query.uppercased()
            results.append(.init(kind: .security, title: symbol, context: "在公司工作区打开", route: .fundamentals, symbol: symbol))
        } else if let selectedSymbol, query.isEmpty || selectedSymbol.localizedCaseInsensitiveContains(query) {
            results.append(.init(
                kind: .security, title: selectedSymbol, context: "当前证券 · 公司工作区",
                route: .fundamentals, symbol: selectedSymbol
            ))
        }
        results.append(contentsOf: indexedSearchResults.filter { result in
            query.isEmpty || result.title.localizedCaseInsensitiveContains(query)
                || result.context.localizedCaseInsensitiveContains(query)
        })
        var seen = Set<String>()
        return results.filter { seen.insert($0.id).inserted }
    }

    public var groupedSearchResults: [(NavigationSearchKind, [NavigationSearchResult])] {
        NavigationSearchKind.allCases.compactMap { kind in
            let values = searchResults.filter { $0.kind == kind }
            return values.isEmpty ? nil : (kind, values)
        }
    }

    public func routes(in section: AppSection) -> [AppRoute] {
        routeOrder.filter { $0.section == section && (isAdministrator || !$0.requiresAdministrator) }
    }

    public func navigate(to route: AppRoute) {
        guard isAdministrator || !route.requiresAdministrator else { return }
        selection = route
        expandedSections.insert(route.section)
        recents.removeAll { $0 == route }
        recents.insert(route, at: 0)
        recents = Array(recents.prefix(6))
        searchPresented = false
    }

    public func state(for route: AppRoute) -> RouteInteractionState {
        routeStates[route] ?? RouteInteractionState()
    }

    public func updateState(for route: AppRoute, _ update: (inout RouteInteractionState) -> Void) {
        var value = state(for: route)
        update(&value)
        routeStates[route] = value
    }

    public func rememberSelection(_ identifier: String?, for route: AppRoute) {
        updateState(for: route) { $0.selectedIdentifier = identifier }
    }

    public func navigate(to result: NavigationSearchResult) {
        if let symbol = result.symbol {
            selectedSymbol = symbol
        }
        navigate(to: result.route)
    }

    public func replaceSearchIndex(
        securities: [NavigationSearchResult],
        conversations: [NavigationSearchResult],
        reports: [NavigationSearchResult]
    ) {
        indexedSearchResults = securities.filter { $0.kind == .security }
            + conversations.filter { $0.kind == .conversation }
            + reports.filter { $0.kind == .report }
    }

    public func toggleFavorite(_ route: AppRoute) {
        if favorites.contains(route) {
            favorites.removeAll { $0 == route }
        } else {
            favorites.append(route)
        }
    }

    public func moveRoutes(in section: AppSection, from offsets: IndexSet, to destination: Int) {
        var sectionRoutes = routes(in: section)
        let moving = offsets.sorted().map { sectionRoutes[$0] }
        for offset in offsets.sorted(by: >) {
            sectionRoutes.remove(at: offset)
        }
        let removedBeforeDestination = offsets.filter { $0 < destination }.count
        sectionRoutes.insert(contentsOf: moving, at: max(0, min(destination - removedBeforeDestination, sectionRoutes.count)))
        var iterator = sectionRoutes.makeIterator()
        routeOrder = routeOrder.map { $0.section == section ? (iterator.next() ?? $0) : $0 }
    }

    public func resetNavigationLayout() {
        favorites = []
        recents = []
        routeOrder = AppRoute.allCases
        expandedSections = [.assets, selection.section]
        inspectorVisible = false
        routeStates = [:]
    }

    @discardableResult
    public func handle(url: URL) -> Bool {
        guard url.scheme == "stockmonitor" else { return false }
        let routeName = url.host == "route" ? url.pathComponents.dropFirst().first : url.host
        guard let routeName,
              let route = AppRoute(rawValue: routeName),
              isAdministrator || !route.requiresAdministrator
        else { return false }
        selection = route
        expandedSections.insert(route.section)
        if let components = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            selectedSymbol = components.queryItems?.first(where: { $0.name == "symbol" })?.value?.uppercased()
        }
        return true
    }

    private static func uniqueVisible(_ routes: [AppRoute], isAdministrator: Bool) -> [AppRoute] {
        var seen = Set<AppRoute>()
        return routes.filter { (isAdministrator || !$0.requiresAdministrator) && seen.insert($0).inserted }
    }

    private static func looksLikeTicker(_ value: String) -> Bool {
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-^")
        let asciiLetters = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
        guard (1 ... 12).contains(value.count), value.rangeOfCharacter(from: asciiLetters) != nil else { return false }
        return value.unicodeScalars.allSatisfy { $0.isASCII && allowed.contains($0) }
    }
}
