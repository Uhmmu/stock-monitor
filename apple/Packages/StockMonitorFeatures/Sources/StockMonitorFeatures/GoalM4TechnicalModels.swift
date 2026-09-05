import Foundation

// MARK: - Goal M4.1 技术分析契约

public struct CompanyProfileOut: Codable, Equatable, Sendable {
    public let symbol: String
    public let status: String
    public let companyName: String?
    public let logoUrl: String?
    public let website: String?
    public let ceo: String?
    public let sector: String?
    public let industry: String?
    public let country: String?
    public let exchange: String?
    public let currency: String?
    public let descriptionZh: String?
    public let descriptionEn: String?
    public let profileSource: String?
    public let profileFetchedAt: String?

    enum CodingKeys: String, CodingKey {
        case symbol, status, website, ceo, sector, industry, country, exchange, currency
        case companyName = "company_name"
        case logoUrl = "logo_url"
        case descriptionZh = "description_zh"
        case descriptionEn = "description_en"
        case profileSource = "profile_source"
        case profileFetchedAt = "profile_fetched_at"
    }
}

public struct ChartCandle: Codable, Equatable, Sendable {
    public let time: String
    public let open: Double
    public let high: Double
    public let low: Double
    public let close: Double
    public let volume: Int

    public init(time: String, open: Double, high: Double, low: Double, close: Double, volume: Int) {
        self.time = time
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
    }
}

public struct MovingAveragePoint: Codable, Equatable, Sendable {
    public let time: String
    public let value: Double
}

public struct ChartSeries: Codable, Equatable, Sendable {
    public let candles: [ChartCandle]
    public let movingAverages: [String: [MovingAveragePoint]]

    enum CodingKeys: String, CodingKey {
        case candles
        case movingAverages = "moving_averages"
    }
}

public struct TechnicalChartEvent: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public let time: String
    public let type: String
    public let label: String?
    public let title: String?
    public let href: String?
}

public struct PortfolioCostContext: Codable, Equatable, Sendable {
    public let averageCost: Double
    public let quantity: Double
    public let currency: String?

    enum CodingKeys: String, CodingKey {
        case quantity, currency
        case averageCost = "average_cost"
    }
}

public struct TechnicalPriceAlert: Codable, Equatable, Identifiable, Sendable {
    public let id: Int
    public let ticker: String
    public let targetPrice: Double
    public let direction: String
    public let enabled: Bool
    public let triggeredAt: String?
    public let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, ticker, direction, enabled
        case targetPrice = "target_price"
        case triggeredAt = "triggered_at"
        case createdAt = "created_at"
    }
}

public struct TechnicalPriceAlertRequest: Encodable, Equatable, Sendable {
    public let targetPrice: Double
    public let direction: String

    public init(targetPrice: Double, direction: String) {
        self.targetPrice = targetPrice
        self.direction = direction
    }

    enum CodingKeys: String, CodingKey {
        case direction
        case targetPrice = "target_price"
    }
}

public struct TechnicalAnalysisDetail: Codable, Equatable, Sendable {
    public let symbol: String
    public let status: String
    public let companyName: String?
    public let logoUrl: String?
    public let analysis: JSONValue?
    public let dataThrough: String?
    public let generatedAt: String?
    public let stale: Bool?
    public let profile: CompanyProfileOut?
    public let chartDataStatus: String?
    public let chartDataReason: String?
    public let chartDataSource: String?
    public let chartSeries: [String: ChartSeries]?
    public let events: [TechnicalChartEvent]?
    public let portfolioCost: PortfolioCostContext?
    public var priceAlerts: [TechnicalPriceAlert]?
    public let dataStatus: JSONValue?

    enum CodingKeys: String, CodingKey {
        case symbol, status, analysis, profile, events
        case companyName = "company_name"
        case logoUrl = "logo_url"
        case dataThrough = "data_through"
        case generatedAt = "generated_at"
        case stale
        case chartDataStatus = "chart_data_status"
        case chartDataReason = "chart_data_reason"
        case chartDataSource = "chart_data_source"
        case chartSeries = "chart_series"
        case portfolioCost = "portfolio_cost"
        case priceAlerts = "price_alerts"
        case dataStatus = "data_status"
    }
}
