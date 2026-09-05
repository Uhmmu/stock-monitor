import Foundation

// MARK: - Goal M4.2 市场情报契约

public struct MacroOverview: Codable, Equatable, Sendable {
    public let lastSyncAt: String?
    public let lastAttemptStatus: String?
    public let lastSuccessfulSyncAt: String?
    public let latestObservationDate: String?
    public let source: JSONValue?
    public let usage: JSONValue?
    public let summaries: JSONValue?
    public let cards: JSONValue?
    public let curveAnalysis: JSONValue?
    public let integrity: JSONValue?
    public let disclaimer: String?

    enum CodingKeys: String, CodingKey {
        case source, usage, summaries, cards, disclaimer
        case lastSyncAt = "last_sync_at"
        case lastAttemptStatus = "last_attempt_status"
        case lastSuccessfulSyncAt = "last_successful_sync_at"
        case latestObservationDate = "latest_observation_date"
        case curveAnalysis = "curve_analysis"
        case integrity
    }
}

public struct MacroSeriesRow: Codable, Equatable, Identifiable, Sendable {
    public let seriesKey: String
    public let nameZh: String?
    public let nameEn: String?
    public let definitionText: String?
    public let current: JSONValue?
    public let previous: JSONValue?
    public let observationDate: String?
    public let lastFetchedAt: String?
    public let dataStatus: String?
    public let freshness: JSONValue?
    public let trend: JSONValue?

    public var id: String {
        seriesKey
    }

    enum CodingKeys: String, CodingKey {
        case current, previous, trend, freshness
        case seriesKey = "series_key"
        case nameZh = "name_zh"
        case nameEn = "name_en"
        case definitionText = "definition"
        case observationDate = "observation_date"
        case lastFetchedAt = "last_fetched_at"
        case dataStatus = "data_status"
    }
}

public struct MacroObservation: Codable, Equatable, Sendable {
    public let observationDate: String
    public let value: Double?
    public let unit: String?
    public let isDerived: Bool?

    enum CodingKeys: String, CodingKey {
        case value, unit
        case observationDate = "observation_date"
        case isDerived = "is_derived"
    }
}

public struct MacroSeriesDetail: Codable, Equatable, Sendable {
    public let seriesKey: String?
    public let nameZh: String?
    public let observations: [MacroObservation]?
    public let latest: JSONValue?
    public let previous: JSONValue?
    public let sparkline: [MacroObservation]?
    public let trend: JSONValue?
    public let freshness: JSONValue?
    public let dataStatus: String?
    public let interpretation: JSONValue?
    public let derivedSeries: JSONValue?

    enum CodingKeys: String, CodingKey {
        case observations, latest, previous, sparkline, trend, freshness, interpretation
        case seriesKey = "series_key"
        case nameZh = "name_zh"
        case dataStatus = "data_status"
        case derivedSeries = "derived_series"
    }
}

public struct YieldCurvePoint: Codable, Equatable, Sendable {
    public let maturity: String
    public let value: Double?
}

public struct YieldCurveSnapshot: Codable, Equatable, Identifiable, Sendable {
    public let label: String
    public let observationDate: String?
    public let points: [YieldCurvePoint]

    public var id: String {
        "\(label)-\(observationDate ?? "NA")"
    }

    enum CodingKeys: String, CodingKey {
        case label, points
        case observationDate = "observation_date"
    }
}

public struct MacroYieldCurve: Codable, Equatable, Sendable {
    public let maturities: [String]
    public let curves: [YieldCurveSnapshot]
    public let spreads: JSONValue?
    public let analysis: JSONValue?
    public let disclaimer: String?
}

public struct MacroSyncStatus: Codable, Equatable, Sendable {
    public let source: JSONValue?
    public let usage: JSONValue?
    public let lastSuccessfulSyncAt: String?
    public let lastAttemptAt: String?
    public let lastAttemptStatus: String?
    public let nextScheduledSync: String?
    public let runs: JSONValue?
    public let disclaimer: String?

    enum CodingKeys: String, CodingKey {
        case source, usage, runs, disclaimer
        case lastSuccessfulSyncAt = "last_successful_sync_at"
        case lastAttemptAt = "last_attempt_at"
        case lastAttemptStatus = "last_attempt_status"
        case nextScheduledSync = "next_scheduled_sync"
    }
}

public struct IndustryPulseItem: Codable, Equatable, Identifiable, Sendable {
    public let nodeID: Int
    public let nodeKey: String?
    public let name: String?
    public let nameZh: String?
    public let tradingDate: String?
    public let pulse: Double?
    public let mood: String?
    public let regime: String?
    public let heat: Double?
    public let risk: Double?
    public let change1d: Double?
    public let change5d: Double?
    public let change20d: Double?
    public let rank: Int?
    public let confidence: Double?
    public let coverageQuality: Double?
    public let direction: String?
    public let proxyMode: String?
    public let constituentCount: Int?
    public let calculationStatus: String?
    public let history: [IndustryPulseHistoryPoint]?
    public let proxyEtfs: [String]?
    public let components: JSONValue?
    public let breadth: JSONValue?

    public var id: Int {
        nodeID
    }

    enum CodingKeys: String, CodingKey {
        case pulse, mood, regime, heat, risk, rank, confidence, direction, history, components, breadth
        case nodeID = "node_id"
        case nodeKey = "node_key"
        case name
        case nameZh = "name_zh"
        case tradingDate = "trading_date"
        case change1d = "change_1d"
        case change5d = "change_5d"
        case change20d = "change_20d"
        case coverageQuality = "coverage_quality"
        case proxyMode = "proxy_mode"
        case constituentCount = "constituent_count"
        case calculationStatus = "calculation_status"
        case proxyEtfs = "proxy_etfs"
    }
}

public struct IndustryPulseHistoryPoint: Codable, Equatable, Sendable {
    public let tradingDate: String
    public let pulse: Double?

    enum CodingKeys: String, CodingKey {
        case pulse
        case tradingDate = "trading_date"
    }
}

public struct IndustryPulseOverview: Codable, Equatable, Sendable {
    public let asOf: String?
    public let rangeDays: Int?
    public let sectors: [IndustryPulseItem]
    public let status: String?

    enum CodingKeys: String, CodingKey {
        case asOf, sectors, status
        case rangeDays = "range_days"
    }
}

public struct IndustryFocusSignal: Codable, Equatable, Identifiable, Sendable {
    public let signalType: String
    public let nodeID: Int
    public let nodeKey: String?
    public let name: String?
    public let nameZh: String?
    public let score: Double?
    public let rank: Int?
    public let confidence: Double?
    public let pulse: Double?
    public let change5d: Double?
    public let direction: String?
    public let heat: Double?
    public let risk: Double?
    public let payload: JSONValue?

    public var id: String {
        "\(signalType)-\(nodeID)"
    }

    enum CodingKeys: String, CodingKey {
        case score, rank, confidence, pulse, direction, heat, risk, payload
        case signalType = "signal_type"
        case nodeID = "node_id"
        case nodeKey = "node_key"
        case name
        case nameZh = "name_zh"
        case change5d = "change_5d"
    }
}

public struct IndustryFocusPayload: Codable, Equatable, Sendable {
    public let asOf: String?
    public let signals: [IndustryFocusSignal]
    public let buckets: [String: [IndustryFocusSignal]]
}

public struct IndustryAICategory: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let nodeKey: String?
    public let name: String?
    public let nameZh: String?
    public let pulse: Double?
    public let change5d: Double?
    public let confidence: Double?
    public let coverageQuality: Double?
    public let heat: Double?
    public let risk: Double?
    public let mood: String?
    public let proxyEtfs: [String]?
    public let groups: [IndustryAICategory]?

    enum CodingKeys: String, CodingKey {
        case id, pulse, confidence, heat, risk, mood, groups
        case nodeKey = "node_key"
        case name
        case nameZh = "name_zh"
        case change5d = "change_5d"
        case coverageQuality = "coverage_quality"
        case proxyEtfs = "proxy_etfs"
    }
}

public struct IndustryAIPayload: Codable, Equatable, Sendable {
    public let asOf: String?
    public let groups: [IndustryAICategory]?
    public let relations: JSONValue?
    public let breadthSummary: JSONValue?

    enum CodingKeys: String, CodingKey {
        case asOf, groups, relations
        case breadthSummary = "breadth_summary"
    }
}

public struct IndustrySystemStatus: Codable, Equatable, Sendable {
    public let marketData: JSONValue?
    public let replacementPending: Int?
    public let latestRun: JSONValue?

    enum CodingKeys: String, CodingKey {
        case latestRun = "latest_run"
        case marketData = "market_data"
        case replacementPending = "replacement_pending"
    }
}

public struct OptionsQuality: Codable, Equatable, Sendable {
    public let level: String?
    public let score: Double?
    public let coverage: Double?
    public let warnings: [String]?
}

public struct OptionSummaryItem: Codable, Equatable, Identifiable, Sendable {
    public let symbol: String
    public let assetType: String?
    public let status: String?
    public let provider: String?
    public let quality: OptionsQuality?
    public let atmIv: Double?
    public let ivChange1: Double?
    public let activityPercentile: Double?
    public let activityChange1: Double?
    public let putCallVolumeRatio: Double?
    public let putCallOiRatio: Double?
    public let downsideSkew: Double?
    public let skewChange1: Double?
    public let oiChange1: Double?
    public let totalVolume: Double?
    public let label: String?

    public var id: String {
        symbol
    }

    enum CodingKeys: String, CodingKey {
        case symbol, status, provider, quality, label
        case assetType = "asset_type"
        case atmIv = "atm_iv"
        case ivChange1 = "iv_change_1"
        case activityPercentile = "activity_percentile"
        case activityChange1 = "activity_change_1"
        case putCallVolumeRatio = "put_call_volume_ratio"
        case putCallOiRatio = "put_call_oi_ratio"
        case downsideSkew = "downside_skew"
        case skewChange1 = "skew_change_1"
        case oiChange1 = "oi_change_1"
        case totalVolume = "total_volume"
    }
}

public struct OptionsOverview: Codable, Equatable, Sendable {
    public let status: String?
    public let asOf: String?
    public let market: [OptionSummaryItem]
    public let sectors: [JSONValue]
    public let watchlist: [OptionSummaryItem]
    public let rankings: [String: [OptionSummaryItem]]
    public let sync: JSONValue?
    public let limitations: [String]?
}

public struct OptionChainRow: Codable, Equatable, Identifiable, Sendable {
    public var id: String {
        let expiry = expiration ?? "NA"
        let kind = optionType ?? "NA"
        let strikeValue = strike.map { value in String(value) } ?? "NA"
        return expiry + "-" + kind + "-" + strikeValue
    }

    public let strike: Double?
    public let expiration: String?
    public let optionType: String?
    public let last: Double?
    public let bid: Double?
    public let ask: Double?
    public let volume: Double?
    public let openInterest: Double?
    public let impliedVolatility: Double?
    public let delta: Double?
    public let gamma: Double?
    public let theta: Double?
    public let vega: Double?
    public let itm: Bool?
    public let displayName: String?

    enum CodingKeys: String, CodingKey {
        case strike, expiration, last, bid, ask, volume, delta, gamma, theta, vega, itm
        case optionType = "option_type"
        case openInterest = "open_interest"
        case impliedVolatility = "implied_volatility"
        case displayName
    }
}

public struct OptionHistoryPoint: Codable, Equatable, Sendable {
    public let date: String?
    public let atmIv: Double?
    public let callVolume: Double?
    public let putVolume: Double?
    public let putCallVolumeRatio: Double?
    public let putCallOiRatio: Double?
    public let downsideSkew: Double?
    public let totalVolume: Double?

    enum CodingKeys: String, CodingKey {
        case date
        case atmIv = "atm_iv"
        case callVolume = "call_volume"
        case putVolume = "put_volume"
        case putCallVolumeRatio = "put_call_volume_ratio"
        case putCallOiRatio = "put_call_oi_ratio"
        case downsideSkew = "downside_skew"
        case totalVolume = "total_volume"
    }
}

public struct OptionDetailResponse: Codable, Equatable, Sendable {
    public let symbol: String
    public let assetType: String?
    public let status: String?
    public let provider: String?
    public let quality: OptionsQuality?
    public let expirations: [String]
    public let selectedExpiration: String?
    public let chain: [OptionChainRow]
    public let history: [OptionHistoryPoint]
    public let atmIv: Double?
    public let ivChange1: Double?
    public let putCallVolumeRatio: Double?
    public let downsideSkew: Double?

    enum CodingKeys: String, CodingKey {
        case symbol, status, provider, quality, expirations, chain, history
        case assetType = "asset_type"
        case selectedExpiration = "selected_expiration"
        case atmIv = "atm_iv"
        case ivChange1 = "iv_change_1"
        case putCallVolumeRatio = "put_call_volume_ratio"
        case downsideSkew = "downside_skew"
    }
}

public struct MoodSnapshotItem: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let scopeType: String
    public let scopeKey: String
    public let tradingDate: String?
    public let name: String?
    public let nameZh: String?
    public let level: String?
    public let state: String?
    public let previousState: String?
    public let direction: String?
    public let phase: String?
    public let regime: String?
    public let moodScore: Double?
    public let agreementScore: Double?
    public let agreementLevel: String?
    public let confidence: Double?
    public let quality: JSONValue?
    public let coverage: Double?
    public let freshnessStatus: String?
    public let durationSessions: Int?
    public let evidence: JSONValue?
    public let divergences: JSONValue?
    public let transition: JSONValue?

    enum CodingKeys: String, CodingKey {
        case id, name, level, state, direction, phase, regime, evidence, divergences, transition
        case scopeType = "scope_type"
        case scopeKey = "scope_key"
        case tradingDate = "trading_date"
        case nameZh = "name_zh"
        case previousState = "previous_state"
        case moodScore = "mood_score"
        case agreementScore = "agreement_score"
        case agreementLevel = "agreement_level"
        case confidence
        case quality
        case coverage
        case freshnessStatus = "freshness_status"
        case durationSessions = "duration_sessions"
    }
}

public struct MoodOverview: Codable, Equatable, Sendable {
    public let rangeDays: Int?
    public let asOf: String?
    public let market: MoodSnapshotItem?
    public let sectors: [MoodSnapshotItem]
    public let aiChain: [MoodSnapshotItem]
    public let movers: JSONValue?
    public let divergences: JSONValue?
    public let transitions: JSONValue?
    public let report: JSONValue?
    public let reportSections: JSONValue?
    public let limitations: [String]?

    enum CodingKeys: String, CodingKey {
        case asOf, market, sectors, report, limitations
        case rangeDays = "range_days"
        case aiChain = "ai_chain"
        case movers
        case divergences
        case transitions
        case reportSections = "report_sections"
    }
}

public struct MoodHistoryResponse: Codable, Equatable, Sendable {
    public let scopeType: String
    public let scopeKey: String
    public let asOf: String?
    public let status: String?
    public let calculationVersion: String?
    public let item: MoodSnapshotItem?
    public let history: [MoodSnapshotItem]

    enum CodingKeys: String, CodingKey {
        case asOf, status, item, history
        case scopeType = "scope_type"
        case scopeKey = "scope_key"
        case calculationVersion = "calculation_version"
    }
}

public struct MoodHistoryHealth: Codable, Equatable, Sendable {
    public let healthStatus: String?
    public let latestEod: String?
    public let oldestEod: String?
    public let historyDays: Int?
    public let completeDays: Int?
    public let partialDays: Int?
    public let run: JSONValue?
    public let calendar: JSONValue?
    public let warnings: [String]?
    public let maturity: JSONValue?

    enum CodingKeys: String, CodingKey {
        case run, calendar, warnings, maturity
        case healthStatus = "health_status"
        case latestEod = "latest_eod"
        case oldestEod = "oldest_eod"
        case historyDays = "history_days"
        case completeDays = "complete_days"
        case partialDays = "partial_days"
    }
}

public struct MoodHistoryGaps: Codable, Equatable, Sendable {
    public let status: String?
    public let gaps: JSONValue?
    public let duplicates: JSONValue?
    public let calendar: JSONValue?
}

public struct MoodPriceHistory: Codable, Equatable, Sendable {
    public let symbol: String
    public let status: String?
    public let source: String?
    public let asOf: String?
    public let candles: [ChartCandle]
}

public struct MoodValidationRun: Codable, Equatable, Identifiable, Sendable {
    public let runID: Int
    public let status: String?
    public let progress: Double?
    public let createdAt: String?
    public let startedAt: String?
    public let completedAt: String?
    public let dateFrom: String?
    public let dateTo: String?
    public let scopeFilter: JSONValue?
    public let forwardHorizons: JSONValue?
    public let coverage: JSONValue?
    public let warnings: [String]?
    public let errorMessage: String?
    public let queued: Bool?
    public let taskID: String?

    public var id: Int {
        runID
    }

    enum CodingKeys: String, CodingKey {
        case status, progress, warnings
        case runID = "run_id"
        case createdAt = "created_at"
        case startedAt = "started_at"
        case completedAt = "completed_at"
        case dateFrom = "date_from"
        case dateTo = "date_to"
        case scopeFilter = "scope_filter"
        case forwardHorizons = "forward_horizons"
        case coverage
        case errorMessage = "error_message"
        case queued
        case taskID = "task_id"
    }
}

public struct MoodValidationRunsResponse: Codable, Equatable, Sendable {
    public let runs: [MoodValidationRun]
}

public struct MoodValidationResultItem: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let studyType: String?
    public let scopeType: String?
    public let scopeKey: String?
    public let state: String?
    public let bucket: String?
    public let horizon: Int?
    public let sampleMode: String?
    public let sampleCount: Int?
    public let metrics: JSONValue?
    public let confidenceInterval: JSONValue?
    public let quality: JSONValue?
    public let warnings: [String]?

    enum CodingKeys: String, CodingKey {
        case id, state, bucket, horizon, metrics, warnings
        case studyType = "study_type"
        case scopeType = "scope_type"
        case scopeKey = "scope_key"
        case sampleMode = "sample_mode"
        case sampleCount = "sample_count"
        case confidenceInterval = "confidence_interval"
        case quality
    }
}

public struct MoodValidationResultsResponse: Codable, Equatable, Sendable {
    public let runID: Int
    public let results: [MoodValidationResultItem]

    enum CodingKeys: String, CodingKey {
        case results
        case runID = "run_id"
    }
}

public struct MoodValidationOverview: Codable, Equatable, Sendable {
    public let status: String?
    public let run: MoodValidationRun?
    public let studies: JSONValue?
    public let limitations: [String]?
    public let warnings: [String]?
}

public struct MoodValidationRunRequest: Encodable, Equatable, Sendable {
    public var dateFrom: String?
    public var dateTo: String?
    public var scopes: [String]
    public var horizons: [Int]

    public init(dateFrom: String? = nil, dateTo: String? = nil, scopes: [String], horizons: [Int]) {
        self.dateFrom = dateFrom
        self.dateTo = dateTo
        self.scopes = scopes
        self.horizons = horizons
    }

    enum CodingKeys: String, CodingKey {
        case scopes, horizons
        case dateFrom = "date_from"
        case dateTo = "date_to"
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encodeIfPresent(dateFrom, forKey: .dateFrom)
        try container.encodeIfPresent(dateTo, forKey: .dateTo)
        try container.encode(scopes, forKey: .scopes)
        try container.encode(horizons, forKey: .horizons)
    }
}

public struct MoodRecoveryRequest: Encodable, Equatable, Sendable {
    public let tradingDate: String
    public let scopes: [String]
    public let reason: String

    public init(tradingDate: String, scopes: [String], reason: String) {
        self.tradingDate = tradingDate
        self.scopes = scopes
        self.reason = reason
    }

    enum CodingKeys: String, CodingKey {
        case scopes, reason
        case tradingDate = "trading_date"
    }
}
