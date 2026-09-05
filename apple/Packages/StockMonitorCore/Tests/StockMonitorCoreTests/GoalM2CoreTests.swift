import Foundation
@testable import StockMonitorCore
import Testing

@Test func sseParserHandlesArbitraryUnicodeChunksCRLFAndMultilineData() {
    let payload = "event: quote_update\r\ndata: {\"symbol\":\"中概股\",\r\ndata: \"price\":3}\r\nid: 7\r\n\r\n"
    let bytes = Array(payload.utf8)
    var parser = SSEParser()
    var events: [ServerSentEvent] = []
    for byte in bytes {
        events += parser.append(Data([byte]))
    }
    #expect(events == [ServerSentEvent(event: "quote_update", data: "{\"symbol\":\"中概股\",\n\"price\":3}", id: "7")])
}

@Test func aiStreamStateMachineIgnoresUnknownAndStopsAfterTerminal() {
    var machine = AIStreamStateMachine()
    machine.consume(.init(event: "provider.reasoning", data: #"{"secret":true}"#))
    machine.consume(.init(event: "response.delta", data: #"{"delta":"先查询"}"#))
    machine.consume(.init(event: "response.reset", data: "{}"))
    machine.consume(.init(event: "response.delta", data: #"{"delta":"最终答案"}"#))
    machine.consume(.init(event: "response.completed", data: #"{"status":"completed","answer":"最终答案"}"#))
    machine.consume(.init(event: "response.delta", data: #"{"delta":"不应追加"}"#))
    #expect(machine.snapshot.phase == .completed)
    #expect(machine.snapshot.answer == "最终答案")
    #expect(machine.snapshot.eventCount == 4)
}

@Test func interruptedAIStreamPreservesLastGoodText() {
    var machine = AIStreamStateMachine()
    machine.consume(.init(event: "response.delta", data: #"{"delta":"已收到"}"#))
    machine.finishTransport()
    #expect(machine.snapshot.answer == "已收到")
    #expect(machine.snapshot.phase == .failed(code: "AI_STREAM_INTERRUPTED", message: "连接已中断，已保留服务端状态。"))
}

@Test func resourceStorePreservesLastGoodValueAcrossRefreshFailure() async {
    let store = ResourceStore<String, String>()
    await store.succeed("last-good", for: "overview", fetchedAt: Date(timeIntervalSince1970: 10))
    await store.beginLoading("overview")
    await store.fail(.transport(code: NSURLErrorNotConnectedToInternet), for: "overview")
    #expect(await store.state(for: "overview").value == "last-good")
}

@Test func privateResponsesNeverEnterDiskCacheAndLogoutClearsSafeCache() async throws {
    let directory = FileManager.default.temporaryDirectory.appending(path: "stock-monitor-cache-\(UUID().uuidString)")
    let cache = DiskResponseCache(directory: directory, maximumBytes: 1024)
    let response = CachedResponse(data: Data("safe".utf8), etag: "v1", expiresAt: .now.addingTimeInterval(60))
    try await cache.insert(response, forKey: "overview")
    #expect(try await cache.value(forKey: "overview")?.data == response.data)
    try await cache.insert(response, forKey: "ai-private", privacy: .privateContent)
    #expect(try await cache.value(forKey: "ai-private") == nil)
    await cache.clearPrivateData()
    #expect(try await cache.value(forKey: "overview") == nil)
}

@Test func staleMarketEventsAreRejectedPerSymbol() {
    var gate = MarketEventOrderingGate()
    let first = gate.accepts(.init(event: "quote_update", data: #"{"symbol":"AAPL","timestamp":"2026-09-05T10:00:00Z"}"#))
    let stale = gate.accepts(.init(event: "quote_update", data: #"{"symbol":"AAPL","timestamp":"2026-09-05T09:59:59Z"}"#))
    let other = gate.accepts(.init(event: "quote_update", data: #"{"symbol":"MSFT","timestamp":"2026-09-05T09:00:00Z"}"#))
    #expect(first)
    #expect(!stale)
    #expect(other)
}

@Test func jobPollingStopsAtEveryTerminalState() {
    let policy = ActiveJobPollingPolicy(initialDelay: 1, maximumDelay: 8)
    #expect(policy.delay(afterAttempt: 4, status: .running) == 8)
    #expect(policy.delay(afterAttempt: 1, status: .completed) == nil)
    #expect(policy.delay(afterAttempt: 1, status: .failed) == nil)
    #expect(policy.delay(afterAttempt: 1, status: .cancelled) == nil)
}

@Test func safeCacheHitsAreRecordedWithoutKeysOrPayloads() async throws {
    let directory = FileManager.default.temporaryDirectory.appending(path: "stock-monitor-metrics-\(UUID().uuidString)")
    let metrics = NetworkMetrics()
    let cache = DiskResponseCache(directory: directory, metrics: metrics)
    try await cache.insert(.init(data: Data("value".utf8), etag: nil, expiresAt: .distantFuture), forKey: "account-scoped-key")
    _ = try await cache.value(forKey: "account-scoped-key")
    let snapshot = await metrics.snapshot()
    #expect(snapshot.cacheHits == 1)
    #expect(snapshot.requestCount == 0)
    await cache.clearPrivateData()
}
