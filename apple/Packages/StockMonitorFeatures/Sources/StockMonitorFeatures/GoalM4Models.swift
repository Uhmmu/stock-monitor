import Foundation

// MARK: - Goal M4.0 公司研究契约

public struct FundamentalsMetric: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        label
    }

    public let label: String
    public let value: Double?
    public let source: String?
}

public struct AnalystRating: Codable, Equatable, Sendable {
    public let period: String?
    public let strongBuy: Int
    public let buy: Int
    public let hold: Int
    public let sell: Int
    public let strongSell: Int

    enum CodingKeys: String, CodingKey {
        case period
        case strongBuy
        case buy, hold, sell
        case strongSell
    }
}

public struct FundamentalsResponse: Codable, Equatable, Sendable {
    public let ticker: String
    public let metrics: [FundamentalsMetric]
    public let rating: AnalystRating?
    public let asOf: String
    public let dataMode: String
    public let sourceSupport: SourceSupport

    enum CodingKeys: String, CodingKey {
        case ticker, metrics, rating
        case asOf = "as_of"
        case dataMode = "data_mode"
        case sourceSupport = "source_support"
    }
}

public struct SourceSupport: Codable, Equatable, Sendable {
    public let yahoo: Bool
    public let finnhub: Bool
}

public struct QuarterlyFinancialRow: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        "\(fiscalYear)-\(fiscalPeriod ?? "NA")-\(periodEnd ?? "NA")"
    }

    public let fiscalYear: Int?
    public let fiscalPeriod: String?
    public let periodEnd: String?
    public let filedAt: String?
    public let currency: String?
    public let revenue: Double?
    public let eps: Double?
    public let netIncome: Double?
    public let operatingIncome: Double?
    public let grossMargin: Double?
    public let netMargin: Double?
    public let operatingCashFlow: Double?
    public let freeCashFlow: Double?
    public let source: String?
    public let syncedAt: String?

    enum CodingKeys: String, CodingKey {
        case currency, revenue, eps, source
        case fiscalYear = "fiscal_year"
        case fiscalPeriod = "fiscal_period"
        case periodEnd = "period_end"
        case filedAt = "filed_at"
        case netIncome = "net_income"
        case operatingIncome = "operating_income"
        case grossMargin = "gross_margin"
        case netMargin = "net_margin"
        case operatingCashFlow = "operating_cash_flow"
        case freeCashFlow = "free_cash_flow"
        case syncedAt = "synced_at"
    }
}

public struct FinancialStatementRow: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        "\(fiscalYear ?? 0)-\(fiscalPeriod ?? "NA")-\(periodEnd ?? "NA")"
    }

    public let fiscalYear: Int?
    public let fiscalPeriod: String?
    public let periodEnd: String?
    public let currency: String?
    public let incomeStatement: JSONValue?
    public let balanceSheet: JSONValue?
    public let cashFlow: JSONValue?
    public let source: String?
    public let syncedAt: String?

    enum CodingKeys: String, CodingKey {
        case currency, source
        case fiscalYear = "fiscal_year"
        case fiscalPeriod = "fiscal_period"
        case periodEnd = "period_end"
        case incomeStatement = "income_statement"
        case balanceSheet = "balance_sheet"
        case cashFlow = "cash_flow"
        case syncedAt = "synced_at"
    }
}

/// `/financial-statements` 的 frequency 是查询参数，不随行返回；由服务层回填。
public struct FinancialStatementPage: Equatable, Sendable {
    public let frequency: String
    public let rows: [FinancialStatementRow]

    public init(frequency: String, rows: [FinancialStatementRow]) {
        self.frequency = frequency
        self.rows = rows
    }
}

/// ValuationSnapshot payload 以 `snapshot_date` / `generated_at` / `ai_model` 平铺在顶层；
/// 其余键形态随模型版本演进，统一保留为 JSON，客户端不重算任何模型。
public struct ValuationCrossModel: Decodable, Equatable, Sendable {
    public let snapshotDate: String?
    public let generatedAt: String?
    public let aiModel: String?
    public let fields: [String: JSONValue]

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let raw = try container.decode([String: JSONValue].self)
        snapshotDate = raw["snapshot_date"]?.stringValue
        generatedAt = raw["generated_at"]?.stringValue
        aiModel = raw["ai_model"]?.stringValue
        var remaining = raw
        remaining.removeValue(forKey: "snapshot_date")
        remaining.removeValue(forKey: "generated_at")
        remaining.removeValue(forKey: "ai_model")
        fields = remaining
    }
}

public extension JSONValue {
    var stringValue: String? {
        if case let .string(value) = self {
            return value
        }
        return nil
    }

    var numberValue: Double? {
        if case let .number(value) = self {
            return value
        }
        return nil
    }

    var arrayValue: [JSONValue] {
        if case let .array(value) = self {
            return value
        }
        return []
    }

    var objectValue: [String: JSONValue] {
        if case let .object(value) = self {
            return value
        }
        return [:]
    }

    /// 把保留的 JSON 重新解码为更具体的子契约；失败时由调用方回退到通用呈现。
    func decode<T: Decodable>(as type: T.Type) throws -> T {
        try JSONDecoder().decode(type, from: JSONEncoder().encode(self))
    }
}

// MARK: 估值快照已知子契约（快照 payload 的稳定子集；未知键保留在 fields 中不丢弃）

public struct CrossModelMetric: Codable, Equatable, Identifiable, Sendable {
    public let key: String
    public let label: String?
    public let value: Double?
    public let unit: String?
    public let status: String?
    public let peerMedian: Double?
    public let peerCount: Int?
    public let peerDeltaPercent: Double?
    public let comparison: String?
    public let explanation: String?

    public var id: String {
        key
    }

    enum CodingKeys: String, CodingKey {
        case key, label, value, unit, status, comparison, explanation
        case peerMedian = "peer_median"
        case peerCount = "peer_count"
        case peerDeltaPercent = "peer_delta_percent"
    }
}

public struct CrossModelSignal: Codable, Equatable, Identifiable, Sendable {
    public let key: String
    public let label: String?
    public let verdict: String?
    public let stars: Int?
    public let detail: String?

    public var id: String {
        key
    }
}

public struct CrossModelConsensusItem: Codable, Equatable, Sendable {
    public let key: String?
    public let label: String?
    public let value: Double?
}

public struct CrossModelConsensus: Codable, Equatable, Sendable {
    public let items: [CrossModelConsensusItem]?
    public let value: Double?
    public let current: Double?
}

public struct GrahamOverrideRequest: Encodable, Equatable, Sendable {
    public var growthRate: Double?
    public var aaaYield: Double?
    public var normalizedEps: Double?

    public init(growthRate: Double? = nil, aaaYield: Double? = nil, normalizedEps: Double? = nil) {
        self.growthRate = growthRate
        self.aaaYield = aaaYield
        self.normalizedEps = normalizedEps
    }

    enum CodingKeys: String, CodingKey {
        case growthRate = "growth_rate"
        case aaaYield = "aaa_yield"
        case normalizedEps = "normalized_eps"
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(growthRate, forKey: .growthRate)
        try container.encodeIfPresent(aaaYield, forKey: .aaaYield)
        try container.encodeIfPresent(normalizedEps, forKey: .normalizedEps)
    }
}

public struct ValuationHistoryPoint: Codable, Equatable, Sendable {
    public let date: String
    public let price: Double?
    public let epsTtm: Double?
    public let pe: Double?

    enum CodingKeys: String, CodingKey {
        case date, price, pe
        case epsTtm = "eps_ttm"
    }
}

public struct ValuationHistoryStatistics: Codable, Equatable, Sendable {
    public let mean: Double
    public let median: Double
    public let p25: Double
    public let p75: Double
    public let percentile: Double?
    public let vsMedianPct: Double?
    public let validPoints: Int

    enum CodingKeys: String, CodingKey {
        case mean, median, percentile
        case p25
        case p75
        case vsMedianPct = "vs_median_pct"
        case validPoints = "valid_points"
    }
}

public struct ValuationHistoryWindow: Codable, Equatable, Sendable {
    public let firstDate: String?
    public let lastDate: String?
    public let yearsAvailable: Double?

    enum CodingKeys: String, CodingKey {
        case firstDate = "first_date"
        case lastDate = "last_date"
        case yearsAvailable = "years_available"
    }
}

public struct ValuationHistoryCurrent: Codable, Equatable, Sendable {
    public let price: Double?
    public let epsTtm: Double?
    public let pe: Double?
    public let peStatus: String?
    public let asOfDate: String?

    enum CodingKeys: String, CodingKey {
        case price, pe
        case epsTtm = "eps_ttm"
        case peStatus = "pe_status"
        case asOfDate = "as_of_date"
    }
}

public struct ValuationHistoryResponse: Codable, Equatable, Sendable {
    public let ticker: String
    public let metric: String
    public let rangeKey: String
    public let status: String
    public let current: ValuationHistoryCurrent?
    public let statistics: ValuationHistoryStatistics?
    public let history: ValuationHistoryWindow?
    public let series: [ValuationHistoryPoint]

    enum CodingKeys: String, CodingKey {
        case ticker, metric, status, current, statistics, history, series
        case rangeKey = "range"
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        ticker = try container.decode(String.self, forKey: .ticker)
        metric = try container.decode(String.self, forKey: .metric)
        rangeKey = try container.decode(String.self, forKey: .rangeKey)
        status = try container.decode(String.self, forKey: .status)
        current = try container.decodeIfPresent(ValuationHistoryCurrent.self, forKey: .current)
        statistics = try container.decodeIfPresent(ValuationHistoryStatistics.self, forKey: .statistics)
        history = try container.decodeIfPresent(ValuationHistoryWindow.self, forKey: .history)
        series = try container.decodeIfPresent([ValuationHistoryPoint].self, forKey: .series) ?? []
    }
}

// MARK: SEC

public struct SecFilingItem: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let form: String
    public let formLabel: String?
    public let items: String?
    public let eventLabels: [String]
    public let priority: Int?
    public let filingDate: String?
    public let reportDate: String?
    public let filingUrl: String?

    enum CodingKeys: String, CodingKey {
        case id, form, items, priority
        case formLabel = "form_label"
        case eventLabels = "event_labels"
        case filingDate = "filing_date"
        case reportDate = "report_date"
        case filingUrl = "filing_url"
    }
}

public struct SecEventItem: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let form: String?
    public let itemCode: String?
    public let itemLabel: String?
    public let priority: Int?
    public let text: String?
    public let summaryZh: String?
    public let summaryModel: String?
    public let summaryStatus: String?
    public let filingDate: String?
    public let filingUrl: String?

    enum CodingKeys: String, CodingKey {
        case id, form, text, priority
        case itemCode = "item_code"
        case itemLabel = "item_label"
        case summaryZh = "summary_zh"
        case summaryModel = "summary_model"
        case summaryStatus = "summary_status"
        case filingDate = "filing_date"
        case filingUrl = "filing_url"
    }
}

public struct SecFinancialRow: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        "\(fiscalYear ?? 0)-\(fiscalPeriod ?? "NA")-\(periodEnd ?? "NA")"
    }

    public let fiscalYear: Int?
    public let fiscalPeriod: String?
    public let form: String?
    public let periodEnd: String?
    public let currency: String?
    public let source: String?
    public let syncedAt: String?
    public let revenue: Double?
    public let netIncome: Double?
    public let operatingIncome: Double?
    public let grossProfit: Double?
    public let epsBasic: Double?
    public let epsDiluted: Double?
    public let cashAndEquivalents: Double?
    public let totalDebt: Double?
    public let sharesOutstanding: Double?
    public let operatingCashFlow: Double?

    enum CodingKeys: String, CodingKey {
        case form, currency, source, revenue
        case fiscalYear = "fiscal_year"
        case fiscalPeriod = "fiscal_period"
        case periodEnd = "period_end"
        case syncedAt = "synced_at"
        case netIncome = "net_income"
        case operatingIncome = "operating_income"
        case grossProfit = "gross_profit"
        case epsBasic = "eps_basic"
        case epsDiluted = "eps_diluted"
        case cashAndEquivalents = "cash_and_equivalents"
        case totalDebt = "total_debt"
        case sharesOutstanding = "shares_outstanding"
        case operatingCashFlow = "operating_cash_flow"
    }
}

public struct SecInsiderItem: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let insiderName: String?
    public let insiderTitle: String?
    public let transactionDate: String?
    public let transactionCode: String?
    public let shares: Double?
    public let price: Double?
    public let value: Double?
    public let sharesOwnedAfter: Double?
    public let flag: String?
    public let filingUrl: String?

    enum CodingKeys: String, CodingKey {
        case id, shares, price, value, flag
        case insiderName = "insider_name"
        case insiderTitle = "insider_title"
        case transactionDate = "transaction_date"
        case transactionCode = "transaction_code"
        case sharesOwnedAfter = "shares_owned_after"
        case filingUrl = "filing_url"
    }
}

public struct Sec13FHoldingItem: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let managerName: String?
    public let shares: Double?
    public let valueUsd: Double?
    public let putCall: String?
    public let shareChange: Double?
    public let isNew: Bool?
    public let filingDate: String?

    enum CodingKeys: String, CodingKey {
        case id, shares, putCall
        case managerName = "manager_name"
        case valueUsd = "value_usd"
        case shareChange = "share_change"
        case isNew = "is_new"
        case filingDate = "filing_date"
    }
}

public struct Sec13FPage: Codable, Equatable, Sendable {
    public let reportPeriod: String?
    public let prevPeriod: String?
    public let holdings: [Sec13FHoldingItem]

    enum CodingKeys: String, CodingKey {
        case holdings
        case reportPeriod = "report_period"
        case prevPeriod = "prev_period"
    }
}

// MARK: Congress / 公众人物

public struct CongressTradeItem: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let filerID: String?
    public let filerName: String?
    public let chamber: String?
    public let party: String?
    public let state: String?
    public let ticker: String?
    public let assetName: String?
    public let transactionType: String?
    public let transactionDate: String?
    public let filingDate: String?
    public let amountLabel: String?
    public let isLate: Bool?

    enum CodingKeys: String, CodingKey {
        case id, chamber, party, state, ticker
        case filerID = "filer_id"
        case filerName = "filer_name"
        case assetName = "asset_name"
        case transactionType = "transaction_type"
        case transactionDate = "transaction_date"
        case filingDate = "filing_date"
        case amountLabel = "amount_label"
        case isLate = "is_late"
    }
}

public struct CongressFigure: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        slug
    }

    public let slug: String
    public let displayName: String
    public let kind: String?
    public let photoUrl: String?
    public let note: String?
    public let isSeed: Bool?
    public let hasPositions: Bool?

    enum CodingKeys: String, CodingKey {
        case slug, note
        case displayName = "display_name"
        case kind
        case photoUrl = "photo_url"
        case isSeed = "is_seed"
        case hasPositions = "has_positions"
    }
}

public struct FigurePosition: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        "\(ticker)-\(category ?? "NA")"
    }

    public let ticker: String?
    public let assetName: String?
    public let category: String?
    public let value: Double
    public let isPercent: Bool?
    public let note: String?

    enum CodingKeys: String, CodingKey {
        case ticker, value, note
        case assetName = "asset_name"
        case category
        case isPercent = "is_percent"
    }
}

public struct CongressFigureDetail: Codable, Equatable, Sendable {
    public let slug: String
    public let displayName: String
    public let kind: String?
    public let photoUrl: String?
    public let note: String?
    public let isSeed: Bool?
    public let positions: [FigurePosition]
    public let positionsArePercent: Bool?
    public let trades: [CongressTradeItem]
    public let moves: JSONValue?

    enum CodingKeys: String, CodingKey {
        case slug, kind, note, positions, trades, moves
        case displayName = "display_name"
        case photoUrl = "photo_url"
        case isSeed = "is_seed"
        case positionsArePercent = "positions_are_percent"
    }
}

// MARK: 个股对比

public struct CompareMetricDefinition: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        key
    }

    public let key: String
    public let label: String
    public let category: String
    public let unit: String?
    public let format: String?
    public let source: String?
    public let direction: String?
    public let sortable: Bool?
    public let supportsHistory: Bool?
    public let tooltip: String?

    enum CodingKeys: String, CodingKey {
        case key, label, category, unit, format, source, direction, sortable, tooltip
        case supportsHistory = "supports_history"
    }
}

public struct CompareCatalog: Codable, Equatable, Sendable {
    public let metrics: [CompareMetricDefinition]
    public let categories: [String]
}

public struct CompareRelative: Codable, Equatable, Sendable {
    public let kind: String?
    public let value: Double?
    public let unit: String?
}

public struct CompareCell: Codable, Equatable, Sendable {
    public let value: Double?
    public let status: String?
    public let source: String?
    public let asOf: String?
    public let period: String?
    public let rank: Int?
    public let percentile: Double?
    public let relativeToMedian: Double?
    public let isBest: Bool?
    public let isWorst: Bool?
    public let trend: JSONValue?
    public let relative: CompareRelative?

    enum CodingKeys: String, CodingKey {
        case value, status, source, period, rank, percentile, trend, relative
        case asOf = "as_of"
        case relativeToMedian = "relative_to_median"
        case isBest = "is_best"
        case isWorst = "is_worst"
    }
}

public struct CompareMetricRow: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        definition.key
    }

    public let definition: CompareMetricDefinition
    public let cells: [String: CompareCell]
    public let availableCount: Int?
    public let dispersion: Double?
    public let isDifferentiator: Bool?
    public let periodMismatch: Bool?
    public let comparisonWarning: String?

    enum CodingKeys: String, CodingKey {
        case definition, cells, dispersion
        case availableCount = "available_count"
        case isDifferentiator = "is_differentiator"
        case periodMismatch = "period_mismatch"
        case comparisonWarning = "comparison_warning"
    }
}

public struct CompareSecurity: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        symbol
    }

    public let symbol: String
    public let name: String?
    public let sector: String?
    public let industry: String?
    public let currency: String?
    public let instrumentType: String?

    enum CodingKeys: String, CodingKey {
        case symbol, name, sector, industry, currency
        case instrumentType = "instrument_type"
    }
}

public struct CompareMetricReference: Codable, Equatable, Sendable {
    public let key: String
    public let label: String
}

public struct CompareHighlight: Codable, Equatable, Identifiable, Sendable {
    public let symbol: String
    public let strengths: [CompareMetricReference]
    public let weaknesses: [CompareMetricReference]

    public var id: String {
        symbol
    }
}

public struct CompareCategoryWinner: Codable, Equatable, Identifiable, Sendable {
    public let category: String
    public let symbol: String?
    public let ties: [String]
    public let evidence: JSONValue?
    public let tradeoffs: JSONValue?

    public var id: String {
        category
    }
}

public struct CompareRun: Codable, Equatable, Sendable {
    public let securities: [CompareSecurity]
    public let metrics: [CompareMetricRow]
    public let categories: [String]
    public let highlights: [CompareHighlight]
    public let categoryWinners: [CompareCategoryWinner]
    public let suggestedPeers: JSONValue?
    public let limitations: [String]
    public let generatedAt: String?

    enum CodingKeys: String, CodingKey {
        case securities, metrics, categories, highlights, limitations
        case categoryWinners = "category_winners"
        case suggestedPeers = "suggested_peers"
        case generatedAt = "generated_at"
    }
}

public struct CompareHistoryPoint: Codable, Equatable, Sendable {
    public let date: String
    public let value: Double?
    public let indexed: Double?
}

public struct CompareHistorySeries: Codable, Equatable, Identifiable, Sendable {
    public let symbol: String
    public let points: [CompareHistoryPoint]

    public var id: String {
        symbol
    }
}

public struct CompareHistoryResponse: Codable, Equatable, Sendable {
    public let metric: CompareMetricDefinition
    public let mode: String
    public let series: [CompareHistorySeries]
    public let limitations: [String]
}
