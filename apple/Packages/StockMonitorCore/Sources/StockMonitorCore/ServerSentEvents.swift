import Foundation
#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

public struct ServerSentEvent: Equatable, Sendable {
    public let event: String
    public let data: String
    public let id: String?
    public let retryMilliseconds: Int?

    public init(event: String = "message", data: String, id: String? = nil, retryMilliseconds: Int? = nil) {
        self.event = event
        self.data = data
        self.id = id
        self.retryMilliseconds = retryMilliseconds
    }
}

public struct SSEParser: Sendable {
    private var buffer = Data()

    public init() {}

    public mutating func append(_ chunk: Data) -> [ServerSentEvent] {
        buffer.append(chunk)
        var output: [ServerSentEvent] = []
        while let boundary = eventBoundary(in: buffer) {
            let block = buffer.prefix(boundary.lowerBound)
            buffer.removeSubrange(..<boundary.upperBound)
            if let event = parse(Data(block)) {
                output.append(event)
            }
        }
        return output
    }

    public mutating func finish() -> [ServerSentEvent] {
        defer { buffer.removeAll(keepingCapacity: false) }
        guard !buffer.isEmpty, let event = parse(buffer) else { return [] }
        return [event]
    }

    private func eventBoundary(in data: Data) -> Range<Data.Index>? {
        data.range(of: Data([10, 10])) ?? data.range(of: Data([13, 10, 13, 10]))
    }

    private func parse(_ data: Data) -> ServerSentEvent? {
        let text = String(decoding: data, as: UTF8.self).replacingOccurrences(of: "\r\n", with: "\n")
        var eventName = "message"
        var dataLines: [String] = []
        var id: String?
        var retry: Int?
        for line in text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init) {
            guard !line.isEmpty, !line.hasPrefix(":") else { continue }
            let parts = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
            let field = String(parts[0])
            let rawValue = parts.count == 2 ? String(parts[1]) : ""
            let value = rawValue.hasPrefix(" ") ? String(rawValue.dropFirst()) : rawValue
            switch field {
            case "event": eventName = value
            case "data": dataLines.append(value)
            case "id": id = value
            case "retry": retry = Int(value)
            default: break
            }
        }
        guard !dataLines.isEmpty else { return nil }
        return ServerSentEvent(event: eventName, data: dataLines.joined(separator: "\n"), id: id, retryMilliseconds: retry)
    }
}

public protocol SSEStreaming: Sendable {
    func events(for request: URLRequest) -> AsyncThrowingStream<ServerSentEvent, Error>
}

public final class URLSessionSSEStreamer: NSObject, SSEStreaming, URLSessionDataDelegate, @unchecked Sendable {
    private struct Connection {
        var parser = SSEParser()
        let continuation: AsyncThrowingStream<ServerSentEvent, Error>.Continuation
    }

    private let lock = NSLock()
    private var connections: [Int: Connection] = [:]
    private lazy var session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)

    override public init() {
        super.init()
    }

    public func events(for request: URLRequest) -> AsyncThrowingStream<ServerSentEvent, Error> {
        AsyncThrowingStream { continuation in
            let task = session.dataTask(with: request)
            lock.withLock { connections[task.taskIdentifier] = Connection(continuation: continuation) }
            continuation.onTermination = { [weak self, weak task] _ in
                task?.cancel()
                guard let self else { return }
                _ = lock.withLock { self.connections.removeValue(forKey: task?.taskIdentifier ?? -1) }
            }
            task.resume()
        }
    }

    public func urlSession(_: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        let events = lock.withLock { () -> [ServerSentEvent] in
            guard var connection = connections[dataTask.taskIdentifier] else { return [] }
            let events = connection.parser.append(data)
            connections[dataTask.taskIdentifier] = connection
            return events
        }
        let continuation = lock.withLock { connections[dataTask.taskIdentifier]?.continuation }
        events.forEach { continuation?.yield($0) }
    }

    public func urlSession(
        _: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping @Sendable (URLSession.ResponseDisposition) -> Void
    ) {
        guard let response = response as? HTTPURLResponse,
              (200 ..< 300).contains(response.statusCode),
              response.mimeType == "text/event-stream"
        else {
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            let connection = lock.withLock { connections.removeValue(forKey: dataTask.taskIdentifier) }
            connection?.continuation.finish(throwing: APIError.http(status: status, message: "Invalid SSE response", requestID: nil))
            completionHandler(.cancel)
            return
        }
        completionHandler(.allow)
    }

    public func urlSession(_: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        let connection = lock.withLock { connections.removeValue(forKey: task.taskIdentifier) }
        guard var connection else { return }
        connection.parser.finish().forEach { connection.continuation.yield($0) }
        if let error {
            connection.continuation.finish(throwing: error)
        } else {
            connection.continuation.finish()
        }
    }
}

public actor MarketStreamCoordinator {
    public enum Status: Equatable, Sendable { case idle, connecting, connected, backingOff, suspended }
    private let streamer: any SSEStreaming
    private let metrics: NetworkMetrics?
    private var task: Task<Void, Never>?
    private var continuations: [UUID: AsyncStream<ServerSentEvent>.Continuation] = [:]
    private(set) var symbols: Set<String> = []
    public private(set) var status: Status = .idle

    public init(streamer: any SSEStreaming = URLSessionSSEStreamer(), metrics: NetworkMetrics? = nil) {
        self.streamer = streamer
        self.metrics = metrics
    }

    public func subscribe() -> AsyncStream<ServerSentEvent> {
        let id = UUID()
        return AsyncStream { continuation in
            continuations[id] = continuation
            continuation.onTermination = { [weak self] _ in Task { await self?.removeSubscriber(id) } }
        }
    }

    public func connect(request: URLRequest, symbols: Set<String>) {
        guard self.symbols != symbols || task == nil else { return }
        task?.cancel()
        self.symbols = symbols
        guard !symbols.isEmpty else { status = .idle; task = nil; return }
        task = Task { [weak self, streamer, metrics] in
            guard let self else { return }
            var attempt = 0
            while !Task.isCancelled {
                await setStatus(.connecting)
                do {
                    for try await event in streamer.events(for: request) {
                        guard !Task.isCancelled else { return }
                        attempt = 0
                        await setStatus(.connected)
                        await publish(event)
                    }
                } catch is CancellationError { return }
                catch { /* reconnect with bounded backoff */ }
                guard !Task.isCancelled else { return }
                await setStatus(.backingOff)
                await metrics?.recordReconnect()
                let delay = min(UInt64(30_000_000_000), UInt64(500_000_000) << min(attempt, 6))
                attempt += 1
                try? await Task.sleep(nanoseconds: delay)
            }
        }
    }

    public func suspend() {
        task?.cancel(); task = nil; status = .suspended
    }

    public func resume(request: URLRequest) {
        connect(request: request, symbols: symbols)
    }

    public func disconnect() {
        task?.cancel(); task = nil; symbols = []; status = .idle
    }

    private func setStatus(_ value: Status) {
        status = value
    }

    private func publish(_ event: ServerSentEvent) {
        continuations.values.forEach { $0.yield(event) }
    }

    private func removeSubscriber(_ id: UUID) {
        continuations.removeValue(forKey: id)
    }
}

public struct MarketEventOrderingGate: Sendable {
    private var latestBySymbol: [String: Date] = [:]
    public init() {}

    public mutating func accepts(_ event: ServerSentEvent) -> Bool {
        guard let object = try? JSONSerialization.jsonObject(with: Data(event.data.utf8)) as? [String: Any],
              let symbol = object["symbol"] as? String,
              let rawDate = (object["timestamp"] ?? object["received_at"]) as? String,
              let date = Self.parseDate(rawDate)
        else { return true }
        if let latest = latestBySymbol[symbol], date < latest {
            return false
        }
        latestBySymbol[symbol] = date
        return true
    }

    private static func parseDate(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) {
            return date
        }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)
    }
}
