import Foundation

public struct SupportDiagnostics: Equatable, Sendable {
    public let generatedAt: Date
    public let appVersion: String
    public let buildNumber: String
    public let operatingSystem: String
    public let architecture: String
    public let compatibilityState: String
    public let metrics: NetworkMetricsSnapshot

    public init(
        generatedAt: Date = Date(), appVersion: String, buildNumber: String,
        operatingSystem: String, architecture: String, compatibilityState: String,
        metrics: NetworkMetricsSnapshot
    ) {
        self.generatedAt = generatedAt
        self.appVersion = appVersion
        self.buildNumber = buildNumber
        self.operatingSystem = operatingSystem
        self.architecture = architecture
        self.compatibilityState = compatibilityState
        self.metrics = metrics
    }

    public var text: String {
        let timestamp = ISO8601DateFormatter().string(from: generatedAt)
        let parse = metrics.parseMilliseconds
        let averageParse = parse.isEmpty ? 0 : parse.reduce(0, +) / Double(parse.count)
        return """
        Stock Monitor support diagnostics
        generated_at: \(timestamp)
        app_version: \(appVersion) (\(buildNumber))
        operating_system: \(operatingSystem)
        architecture: \(architecture)
        compatibility: \(compatibilityState)
        request_count: \(metrics.requestCount)
        cache_hits: \(metrics.cacheHits)
        stream_reconnects: \(metrics.streamReconnects)
        average_parse_ms: \(String(format: "%.2f", averageParse))
        frame_hitches: \(metrics.frameHitches)
        privacy: no tokens, usernames, account identifiers, holdings, conversations, request URLs, or payloads are included
        """
    }
}
