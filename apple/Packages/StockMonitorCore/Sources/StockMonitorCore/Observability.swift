import Foundation

public struct NetworkMetricsSnapshot: Equatable, Sendable {
    public let requestCount: Int
    public let cacheHits: Int
    public let streamReconnects: Int
    public let parseMilliseconds: [Double]
    public let frameHitches: Int
}

public actor NetworkMetrics {
    private var requestCount = 0
    private var cacheHits = 0
    private var streamReconnects = 0
    private var parseMilliseconds: [Double] = []
    private var frameHitches = 0

    public init() {}
    public func recordRequest() {
        requestCount += 1
    }

    public func recordCacheHit() {
        cacheHits += 1
    }

    public func recordReconnect() {
        streamReconnects += 1
    }

    public func recordParse(milliseconds: Double) {
        parseMilliseconds.append(milliseconds); if parseMilliseconds.count > 128 {
            parseMilliseconds.removeFirst()
        }
    }

    public func recordFrameHitch() {
        frameHitches += 1
    }

    public func snapshot() -> NetworkMetricsSnapshot {
        .init(requestCount: requestCount, cacheHits: cacheHits, streamReconnects: streamReconnects, parseMilliseconds: parseMilliseconds, frameHitches: frameHitches)
    }
}
