import Foundation

public struct MarketStatus: Codable, Equatable, Sendable {
    public let isOpen: Bool
    public let session: String?
    public let checkedAt: String

    enum CodingKeys: String, CodingKey {
        case isOpen = "is_open"
        case session
        case checkedAt = "checked_at"
    }
}

public struct DashboardStock: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        ticker
    }

    public let ticker: String
    public let price: Double?
    public let previousClose: Double?
    public let priceSource: String?
    public let updatedAt: String?
    public let volume: Int?
    public let volumeRatio: Double?
    public let volumeLabel: String?
    public let companyName: String?

    enum CodingKeys: String, CodingKey {
        case ticker, price, volume
        case previousClose = "previous_close"
        case priceSource = "price_source"
        case updatedAt = "updated_at"
        case volumeRatio = "volume_ratio"
        case volumeLabel = "volume_label"
        case companyName = "company_name"
    }

    public var changePercent: Double? {
        guard let price, let previousClose, previousClose != 0 else { return nil }
        return (price / previousClose - 1) * 100
    }
}

public struct DashboardSnapshot: Codable, Equatable, Sendable {
    public let market: MarketStatus
    public let stocks: [DashboardStock]
}

public struct MarketIndex: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        symbol
    }

    public let symbol: String
    public let name: String
    public let price: Double?
    public let previousClose: Double?
    public let changePoints: Double?
    public let changePercent: Double?

    enum CodingKeys: String, CodingKey {
        case symbol, name, price
        case previousClose = "previous_close"
        case changePoints = "change_points"
        case changePercent = "change_percent"
    }
}

public struct IndicesSnapshot: Codable, Equatable, Sendable {
    public let indices: [MarketIndex]
    public let market: MarketStatus
}

public struct BenchmarkItem: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        symbol
    }

    public let symbol: String
    public let name: String
    public let returnPercent: Double?
    public let relativeReturnPercent: Double?
    public let status: String
    public let message: String?
    enum CodingKeys: String, CodingKey {
        case symbol, name, status, message
        case returnPercent = "return_percent"
        case relativeReturnPercent = "relative_return_percent"
    }
}

public struct PortfolioBenchmark: Codable, Equatable, Sendable {
    public let startDate: String?
    public let portfolioReturnPercent: Double?
    public let configured: Bool
    public let portfolioReturnSource: String
    public let benchmarks: [BenchmarkItem]
    public let source: String
    public let asOf: String
    enum CodingKeys: String, CodingKey {
        case configured, benchmarks, source
        case startDate = "start_date"
        case portfolioReturnPercent = "portfolio_return_percent"
        case portfolioReturnSource = "portfolio_return_source"
        case asOf = "as_of"
    }
}

public struct RealtimeQuote: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        symbol
    }

    public let symbol: String
    public let price: Double?
    public let previousClose: Double?
    public let timestamp: String?
    public let receivedAt: String?
    public let provider: String?
    public let feed: String?
    public let marketSession: String?
    public let isDelayed: Bool?
    public let delayedSeconds: Int?
    public let isStale: Bool?
    public let ageSeconds: Int?
    public let sourceType: String?

    enum CodingKeys: String, CodingKey {
        case symbol, price, timestamp, provider, feed
        case previousClose = "previous_close"
        case receivedAt = "received_at"
        case marketSession = "market_session"
        case isDelayed = "is_delayed"
        case delayedSeconds = "delayed_seconds"
        case isStale = "is_stale"
        case ageSeconds = "age_seconds"
        case sourceType = "source_type"
    }
}

public struct WatchlistItem: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let ticker: String?
    public let securityID: Int?
    public let enabled: Bool
    public let alertEnabled: Bool
    public let userGroupID: Int?
    public let displayOrder: Int
    public let threshold20m: Double?
    public let threshold1h: Double?
    public let thresholdDay: Double?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, ticker, enabled
        case securityID = "security_id"
        case alertEnabled = "alert_enabled"
        case userGroupID = "user_group_id"
        case displayOrder = "display_order"
        case threshold20m = "threshold_20m"
        case threshold1h = "threshold_1h"
        case thresholdDay = "threshold_day"
        case createdAt = "created_at"
    }
}

public struct StockGroup: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let name: String
    public let displayOrder: Int

    enum CodingKeys: String, CodingKey { case id, name; case displayOrder = "display_order" }
}

public struct ManagedStock: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        ticker
    }

    public let ticker: String
    public let companyName: String?
    public let officialSector: String?
    public let officialIndustry: String?
    public let userGroupID: Int?
    public let displayOrder: Int
    public let isWatchlisted: Bool
    public let isPeerReferenced: Bool
    public let peerReferencedBy: [String]
    public let price: Double?
    public let changePercent: Double?
    public let alertEnabled: Bool
    public let threshold20m: Double?
    public let threshold1h: Double?
    public let thresholdDay: Double?
    public let watchlistID: Int?

    enum CodingKeys: String, CodingKey {
        case ticker, price
        case companyName = "company_name"
        case officialSector = "official_sector"
        case officialIndustry = "official_industry"
        case userGroupID = "user_group_id"
        case displayOrder = "display_order"
        case isWatchlisted = "is_watchlisted"
        case isPeerReferenced = "is_peer_referenced"
        case peerReferencedBy = "peer_referenced_by"
        case changePercent = "change_percent"
        case alertEnabled = "alert_enabled"
        case threshold20m = "threshold_20m"
        case threshold1h = "threshold_1h"
        case thresholdDay = "threshold_day"
        case watchlistID = "watchlist_id"
    }
}

public struct StockManagementSnapshot: Codable, Equatable, Sendable {
    public var groups: [StockGroup]
    public var watchlisted: [ManagedStock]
    public var matched: [ManagedStock]
}

public struct PeerItem: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        ticker
    }

    public let ticker: String
    public let source: String
    public let excluded: Bool
    public let displayOrder: Int
    public let isWatchlisted: Bool

    enum CodingKeys: String, CodingKey {
        case ticker, source, excluded
        case displayOrder = "display_order"
        case isWatchlisted = "is_watchlisted"
    }
}

public struct PeerList: Codable, Equatable, Sendable {
    public let baseTicker: String
    public let items: [PeerItem]
    enum CodingKeys: String, CodingKey { case items; case baseTicker = "base_ticker" }
}

public struct StockGroupRequest: Codable, Equatable, Sendable {
    public let name: String
    public init(name: String) {
        self.name = name
    }
}

public struct PeerMutationResponse: Codable, Equatable, Sendable {
    public let baseTicker: String
    public let peerTicker: String
    public let source: String
    enum CodingKeys: String, CodingKey {
        case source
        case baseTicker = "base_ticker"
        case peerTicker = "peer_ticker"
    }
}

public struct SecurityCandidate: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        providerKey
    }

    public let providerKey: String
    public let securityID: Int?
    public let displaySymbol: String
    public let displayName: String
    public let exchange: String?
    public let market: String?
    public let currency: String?
    public let instrumentType: String?
    public let yahooSymbol: String?
    public let finnhubSymbol: String?
    public let source: String
    public let isLocal: Bool

    public init(
        providerKey: String, securityID: Int?, displaySymbol: String, displayName: String,
        exchange: String?, market: String?, currency: String?, instrumentType: String?,
        yahooSymbol: String?, finnhubSymbol: String?, source: String, isLocal: Bool
    ) {
        self.providerKey = providerKey
        self.securityID = securityID
        self.displaySymbol = displaySymbol
        self.displayName = displayName
        self.exchange = exchange
        self.market = market
        self.currency = currency
        self.instrumentType = instrumentType
        self.yahooSymbol = yahooSymbol
        self.finnhubSymbol = finnhubSymbol
        self.source = source
        self.isLocal = isLocal
    }

    enum CodingKeys: String, CodingKey {
        case exchange, market, currency, source
        case providerKey = "provider_key"
        case securityID = "security_id"
        case displaySymbol = "display_symbol"
        case displayName = "display_name"
        case instrumentType = "instrument_type"
        case yahooSymbol = "yahoo_symbol"
        case finnhubSymbol = "finnhub_symbol"
        case isLocal = "is_local"
    }
}

public struct SecuritySearchResult: Codable, Equatable, Sendable {
    public let query: String
    public let results: [SecurityCandidate]
}

public struct MovementAlert: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let ticker: String
    public let period: String
    public let changePercent: Double
    public let triggeredAt: String

    enum CodingKeys: String, CodingKey {
        case id, ticker, period
        case changePercent = "change_percent"
        case triggeredAt = "triggered_at"
    }
}

public struct InvestigationItem: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let ticker: String
    public let status: String
    public let startedAt: String
    public let endsAt: String
    public let nextSearchAt: String?
    public let newsCount: Int
    public let lastError: String?

    enum CodingKeys: String, CodingKey {
        case id, ticker, status
        case startedAt = "started_at"
        case endsAt = "ends_at"
        case nextSearchAt = "next_search_at"
        case newsCount = "news_count"
        case lastError = "last_error"
    }
}

public indirect enum JSONValue: Codable, Equatable, Sendable {
    case object([String: JSONValue])
    case array([JSONValue])
    case string(String)
    case number(Double)
    case bool(Bool)
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported JSON value")
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case let .object(value): try container.encode(value)
        case let .array(value): try container.encode(value)
        case let .string(value): try container.encode(value)
        case let .number(value): try container.encode(value)
        case let .bool(value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    public var displayText: String {
        switch self {
        case let .string(value): value
        case let .number(value): value.formatted()
        case let .bool(value): value ? "是" : "否"
        case .null: "数据不足"
        case let .array(values): values.map { "- \($0.displayText)" }.joined(separator: "\n")
        case let .object(values):
            values.keys.sorted().map { "**\($0)**：\(values[$0]?.displayText ?? "数据不足")" }.joined(separator: "\n\n")
        }
    }
}

public struct NewsItem: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let ticker: String?
    public let provider: String
    public let title: String
    public let translatedTitle: String?
    public let url: String?
    public let source: String?
    public let summary: String?
    public let topic: String?
    public let publishedAt: String?
    public let foundAt: String
    public let aiSummary: String?
    public let aiAnalysis: JSONValue?
    public let aiSummaryStatus: String?
    public let aiSummaryGeneratedAt: String?

    enum CodingKeys: String, CodingKey {
        case id, ticker, provider, title, url, source, summary, topic
        case translatedTitle = "translated_title"
        case publishedAt = "published_at"
        case foundAt = "found_at"
        case aiSummary = "ai_summary"
        case aiAnalysis = "ai_analysis"
        case aiSummaryStatus = "ai_summary_status"
        case aiSummaryGeneratedAt = "ai_summary_generated_at"
    }

    public var displayTitle: String {
        translatedTitle ?? title
    }

    public var timestamp: String {
        publishedAt ?? foundAt
    }
}

public struct MarketNewsPage: Codable, Equatable, Sendable {
    public let items: [NewsItem]
    public let total: Int
    public let generatedAt: String
    public let lastUpdatedAt: String?
    public let sources: [String]

    enum CodingKeys: String, CodingKey {
        case items, total, sources
        case generatedAt = "generated_at"
        case lastUpdatedAt = "last_updated_at"
    }
}

public struct CalendarEvent: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public let eventType: String
    public let symbol: String?
    public let companyName: String?
    public let title: String
    public let description: String?
    public let eventDate: String
    public let eventTime: String?
    public let timeStatus: String
    public let isConfirmed: Bool
    public let isEstimated: Bool
    public let confidence: String?
    public let impactLevel: String
    public let primarySource: String
    public let hasConflict: Bool
    public let portfolioRelevance: Bool
    public let watchlistRelevance: Bool
    public let fetchedAt: String?
    public let stale: Bool
    public let warning: String?

    enum CodingKeys: String, CodingKey {
        case id, symbol, title, description, confidence, stale, warning
        case eventType = "event_type"
        case companyName = "company_name"
        case eventDate = "event_date"
        case eventTime = "event_time"
        case timeStatus = "time_status"
        case isConfirmed = "is_confirmed"
        case isEstimated = "is_estimated"
        case impactLevel = "impact_level"
        case primarySource = "primary_source"
        case hasConflict = "has_conflict"
        case portfolioRelevance = "portfolio_relevance"
        case watchlistRelevance = "watchlist_relevance"
        case fetchedAt = "fetched_at"
    }
}

public struct CalendarPage: Codable, Equatable, Sendable {
    public let items: [CalendarEvent]
    public let total: Int
    public let nextCursor: Int?
    public let generatedAt: String

    enum CodingKeys: String, CodingKey {
        case items, total
        case nextCursor = "next_cursor"
        case generatedAt = "generated_at"
    }
}

public struct ReportSummary: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let ticker: String
    public let reportType: String
    public let title: String
    public let model: String?
    public let createdAt: String
    public let confidence: String?

    enum CodingKeys: String, CodingKey {
        case id, ticker, title, model, confidence
        case reportType = "report_type"
        case createdAt = "created_at"
    }
}

public struct ReportDetail: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let ticker: String
    public let reportType: String
    public let title: String
    public let content: String
    public let model: String?
    public let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, ticker, title, content, model
        case reportType = "report_type"
        case createdAt = "created_at"
    }
}

public struct MutationStatus: Codable, Equatable, Sendable {
    public let status: String
    public let ticker: String?
    public let scope: String?
}

public struct WatchlistCreateRequest: Codable, Equatable, Sendable {
    public let securityID: Int?
    public let source: String?
    public let yahooSymbol: String?
    public let finnhubSymbol: String?

    public init(candidate: SecurityCandidate) {
        securityID = candidate.securityID
        source = candidate.source
        yahooSymbol = candidate.yahooSymbol
        finnhubSymbol = candidate.finnhubSymbol
    }

    enum CodingKeys: String, CodingKey {
        case source
        case securityID = "security_id"
        case yahooSymbol = "yahoo_symbol"
        case finnhubSymbol = "finnhub_symbol"
    }
}

public struct WatchlistUpdateRequest: Encodable, Equatable, Sendable {
    public var enabled: Bool?
    public var alertEnabled: Bool?
    public var userGroupID: Int?
    public var displayOrder: Int?
    public var threshold20m: Double?
    public var threshold1h: Double?
    public var thresholdDay: Double?
    private let includeThresholds: Bool

    public init(
        enabled: Bool? = nil, alertEnabled: Bool? = nil, userGroupID: Int? = nil,
        displayOrder: Int? = nil, threshold20m: Double? = nil,
        threshold1h: Double? = nil, thresholdDay: Double? = nil,
        includeThresholds: Bool = false
    ) {
        self.enabled = enabled
        self.alertEnabled = alertEnabled
        self.userGroupID = userGroupID
        self.displayOrder = displayOrder
        self.threshold20m = threshold20m
        self.threshold1h = threshold1h
        self.thresholdDay = thresholdDay
        self.includeThresholds = includeThresholds
    }

    enum CodingKeys: String, CodingKey {
        case enabled
        case alertEnabled = "alert_enabled"
        case userGroupID = "user_group_id"
        case displayOrder = "display_order"
        case threshold20m = "threshold_20m"
        case threshold1h = "threshold_1h"
        case thresholdDay = "threshold_day"
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(enabled, forKey: .enabled)
        try container.encodeIfPresent(alertEnabled, forKey: .alertEnabled)
        try container.encodeIfPresent(userGroupID, forKey: .userGroupID)
        try container.encodeIfPresent(displayOrder, forKey: .displayOrder)
        if includeThresholds {
            try container.encode(threshold20m, forKey: .threshold20m)
            try container.encode(threshold1h, forKey: .threshold1h)
            try container.encode(thresholdDay, forKey: .thresholdDay)
        }
    }
}

public struct DisplayOrderRequest: Codable, Equatable, Sendable {
    public let displayOrder: Int
    public init(displayOrder: Int) {
        self.displayOrder = displayOrder
    }

    enum CodingKeys: String, CodingKey { case displayOrder = "display_order" }
}
