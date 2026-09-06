import Foundation
import Observation

public enum AppSection: String, CaseIterable, Identifiable, Sendable {
    case assets, research, intelligence, company, records, ibkr, crypto
    public var id: Self {
        self
    }

    public var title: String {
        switch self {
        case .assets: "概览与资产"; case .research: "研究与决策"; case .intelligence: "市场情报"
        case .company: "公司分析"; case .records: "记录与系统"; case .ibkr: "IBKR"; case .crypto: "Crypto 工作区"
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
        case .overview: "总览"; case .watchlist: "自选股"; case .holdings: "持仓"; case .ai: "Chat"
        case .decisions: "投资决策"; case .calendar: "投资日历"; case .discovery: "机会发现"; case .options: "期权研究"
        case .mood: "AI 情绪台"; case .moodLab: "Mood 验证实验室"; case .alerts: "异动中心"; case .news: "新闻中心"
        case .macro: "美国宏观"; case .industry: "行业板块"; case .fundamentals: "基本面"; case .financials: "财务报表"
        case .valuation: "估值"; case .compare: "个股对比"; case .technical: "技术分析"; case .sec: "SEC"
        case .ownership: "机构持仓"; case .congress: "公众人物交易"; case .reports: "报告中心"; case .journal: "交易日志"
        case .settings: "设置"; case .administration: "用户管理"; case .ibkr: "IBKR"; case .ibkrAdmin: "IBKR 管理"
        case .cryptoResearch: "Crypto 研究"; case .quantBacktests: "量化回测"; case .paper: "内部 PAPER"
        }
    }

    public var systemImage: String {
        switch self {
        case .overview: "rectangle.grid.2x2"; case .watchlist: "star"; case .holdings: "briefcase"
        case .ai: "bubble.left.and.text.bubble.right"; case .decisions: "checklist"; case .calendar: "calendar"
        case .discovery: "safari"; case .options: "function"; case .mood, .moodLab: "waveform.path.ecg"
        case .alerts: "bell"; case .news: "newspaper"; case .macro: "globe.americas"; case .industry: "chart.line.uptrend.xyaxis"
        case .fundamentals: "building.2"; case .financials: "tablecells"; case .valuation: "scalemass"; case .compare: "square.split.2x1"
        case .technical: "chart.xyaxis.line"; case .sec: "doc.text.magnifyingglass"; case .ownership: "person.3"; case .congress: "person.crop.rectangle.stack"
        case .reports: "doc.richtext"; case .journal: "book.closed"; case .settings: "gearshape"; case .administration: "person.badge.key"
        case .ibkr: "building.columns"; case .ibkrAdmin: "wrench.and.screwdriver"; case .cryptoResearch: "bitcoinsign.circle"
        case .quantBacktests: "point.3.connected.trianglepath.dotted"; case .paper: "doc.text"
        }
    }

    public var requiresAdministrator: Bool {
        [.moodLab, .administration, .ibkrAdmin].contains(self)
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

public struct StockDetailRoute: Codable, Hashable, Sendable { public let symbol: String; public init(symbol: String) {
    self.symbol = symbol.uppercased()
} }
public struct ResearchDetailRoute: Codable, Hashable, Sendable { public let route: AppRoute; public let identifier: String; public init(route: AppRoute, identifier: String) {
    self.route = route; self.identifier = identifier
} }

@MainActor
@Observable
public final class AppNavigationModel {
    public var selection: AppRoute
    public var inspectorVisible = false
    public var searchPresented = false
    public var searchQuery = ""
    public var isAdministrator: Bool
    public var selectedSymbol: String?

    public init(selection: AppRoute = .overview, isAdministrator: Bool = false) {
        self.selection = selection
        self.isAdministrator = isAdministrator
    }

    public var searchResults: [AppRoute] {
        let candidates = AppRoute.visible(isAdministrator: isAdministrator)
        let query = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        return query.isEmpty ? candidates : candidates.filter { $0.title.localizedCaseInsensitiveContains(query) || $0.rawValue.localizedCaseInsensitiveContains(query) }
    }

    public func navigate(to route: AppRoute) {
        guard isAdministrator || !route.requiresAdministrator else { return }
        selection = route
        searchPresented = false
    }

    @discardableResult
    public func handle(url: URL) -> Bool {
        guard url.scheme == "stockmonitor" else { return false }
        let routeName = url.host == "route" ? url.pathComponents.dropFirst().first : url.host
        guard let routeName, let route = AppRoute(rawValue: routeName), isAdministrator || !route.requiresAdministrator else { return false }
        selection = route
        if let components = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            selectedSymbol = components.queryItems?.first(where: { $0.name == "symbol" })?.value?.uppercased()
        }
        return true
    }
}
