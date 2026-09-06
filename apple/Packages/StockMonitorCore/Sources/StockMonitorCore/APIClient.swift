import Foundation
#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

public enum HTTPMethod: String, Equatable, Sendable { case get = "GET", post = "POST", put = "PUT", patch = "PATCH", delete = "DELETE" }

public struct EmptyResponse: Codable, Equatable, Sendable {
    public init() {}
}

public enum APIError: Error, Equatable, Sendable {
    case invalidResponse
    case transport(code: Int)
    case http(status: Int, message: String?, requestID: String?)
    case encoding
    case decoding

    public var isOffline: Bool {
        guard case let .transport(code) = self else { return false }
        return [NSURLErrorNotConnectedToInternet, NSURLErrorNetworkConnectionLost, NSURLErrorCannotConnectToHost,
                NSURLErrorCannotFindHost, NSURLErrorTimedOut].contains(code)
    }
}

public struct RetryPolicy: Equatable, Sendable {
    public let maximumAttempts: Int
    public let baseDelayNanoseconds: UInt64

    public init(maximumAttempts: Int = 3, baseDelayNanoseconds: UInt64 = 250_000_000) {
        self.maximumAttempts = max(1, maximumAttempts)
        self.baseDelayNanoseconds = baseDelayNanoseconds
    }

    func delay(forAttempt attempt: Int) -> UInt64 {
        baseDelayNanoseconds * UInt64(1 << min(attempt, 6))
    }
}

public actor APIClient {
    private let configuration: APIConfiguration
    private let transport: any HTTPTransport
    private let retryPolicy: RetryPolicy
    private let metrics: NetworkMetrics?
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    public init(
        configuration: APIConfiguration,
        transport: any HTTPTransport = URLSessionTransport(),
        retryPolicy: RetryPolicy = RetryPolicy(),
        metrics: NetworkMetrics? = nil
    ) {
        self.configuration = configuration
        self.transport = transport
        self.retryPolicy = retryPolicy
        self.metrics = metrics
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        self.encoder = encoder
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let value = try decoder.singleValueContainer().decode(String.self)
            for options: ISO8601DateFormatter.Options in [
                [.withInternetDateTime, .withFractionalSeconds],
                [.withInternetDateTime],
            ] {
                let formatter = ISO8601DateFormatter()
                formatter.formatOptions = options
                if let date = formatter.date(from: value) {
                    return date
                }
            }
            throw try DecodingError.dataCorruptedError(
                in: decoder.singleValueContainer(),
                debugDescription: "Expected an ISO-8601 date"
            )
        }
        self.decoder = decoder
    }

    public func send<Response: Decodable & Sendable>(
        _ responseType: Response.Type,
        path: String,
        method: HTTPMethod,
        body: (some Encodable & Sendable)?,
        queryItems: [URLQueryItem] = [],
        accessToken: String? = nil,
        idempotent: Bool = false
    ) async throws -> Response {
        var request = URLRequest(url: configuration.url(path: path, queryItems: queryItems))
        request.httpMethod = method.rawValue
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(UUID().uuidString, forHTTPHeaderField: "X-Request-ID")
        if let accessToken {
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        if idempotent, method != .get {
            request.setValue(UUID().uuidString, forHTTPHeaderField: "Idempotency-Key")
        }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            do { request.httpBody = try encoder.encode(body) } catch { throw APIError.encoding }
        }

        let mayRetry = idempotent || method == .get
        var attempt = 0
        while true {
            do {
                await metrics?.recordRequest()
                let response = try await transport.data(for: request)
                if (200 ..< 300).contains(response.statusCode) {
                    do {
                        let start = ContinuousClock.now
                        let decoded = try decoder.decode(Response.self, from: response.data)
                        let duration = start.duration(to: .now)
                        let milliseconds = Double(duration.components.seconds) * 1000
                            + Double(duration.components.attoseconds) / 1_000_000_000_000_000
                        await metrics?.recordParse(milliseconds: milliseconds)
                        return decoded
                    } catch {
                        throw APIError.decoding
                    }
                }
                let message = try? decoder.decode(ErrorEnvelope.self, from: response.data).detail
                let requestID = response.headers["x-request-id"] ?? response.headers["X-Request-ID"]
                if shouldRetry(statusCode: response.statusCode, attempt: attempt, allowed: mayRetry) {
                    try await Task.sleep(nanoseconds: retryPolicy.delay(forAttempt: attempt))
                    attempt += 1
                    continue
                }
                throw APIError.http(status: response.statusCode, message: message, requestID: requestID)
            } catch let error as APIError {
                throw error
            } catch let error as URLError {
                if mayRetry, attempt + 1 < retryPolicy.maximumAttempts, error.code == .timedOut {
                    try await Task.sleep(nanoseconds: retryPolicy.delay(forAttempt: attempt))
                    attempt += 1
                    continue
                }
                throw APIError.transport(code: error.errorCode)
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                throw APIError.invalidResponse
            }
        }
    }

    private func shouldRetry(statusCode: Int, attempt: Int, allowed: Bool) -> Bool {
        allowed
            && attempt + 1 < retryPolicy.maximumAttempts
            && (statusCode == 429 || (500 ..< 600).contains(statusCode))
    }

    public func get<Response: Decodable & Sendable>(
        _ responseType: Response.Type, path: String, queryItems: [URLQueryItem] = [], accessToken: String? = nil
    ) async throws -> Response {
        try await send(responseType, path: path, method: .get, body: String?.none, queryItems: queryItems, accessToken: accessToken)
    }

    public func post<Response: Decodable & Sendable>(
        _ responseType: Response.Type, path: String, body: some Encodable & Sendable, accessToken: String? = nil, idempotent: Bool = false
    ) async throws -> Response {
        try await send(responseType, path: path, method: .post, body: body, accessToken: accessToken, idempotent: idempotent)
    }

    public func request<Response: Decodable & Sendable>(
        _ responseType: Response.Type,
        path: String,
        method: HTTPMethod,
        body: (some Encodable & Sendable)?,
        queryItems: [URLQueryItem] = [],
        accessToken: String? = nil,
        idempotent: Bool = false
    ) async throws -> Response {
        try await send(
            responseType,
            path: path,
            method: method,
            body: body,
            queryItems: queryItems,
            accessToken: accessToken,
            idempotent: idempotent
        )
    }

    public func requestWithoutResponse(
        path: String,
        method: HTTPMethod,
        body: (some Encodable & Sendable)?,
        queryItems: [URLQueryItem] = [],
        accessToken: String? = nil,
        idempotent: Bool = false
    ) async throws {
        var request = URLRequest(url: configuration.url(path: path, queryItems: queryItems))
        request.httpMethod = method.rawValue
        request.timeoutInterval = 30
        request.setValue(UUID().uuidString, forHTTPHeaderField: "X-Request-ID")
        if let accessToken {
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        if idempotent, method != .get {
            request.setValue(UUID().uuidString, forHTTPHeaderField: "Idempotency-Key")
        }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            do { request.httpBody = try encoder.encode(body) } catch { throw APIError.encoding }
        }
        do {
            await metrics?.recordRequest()
            let response = try await transport.data(for: request)
            guard (200 ..< 300).contains(response.statusCode) else {
                let message = try? decoder.decode(ErrorEnvelope.self, from: response.data).detail
                throw APIError.http(
                    status: response.statusCode,
                    message: message,
                    requestID: response.headers["x-request-id"] ?? response.headers["X-Request-ID"]
                )
            }
        } catch let error as APIError {
            throw error
        } catch let error as URLError {
            throw APIError.transport(code: error.errorCode)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw APIError.invalidResponse
        }
    }

    public func makeRequest(
        path: String,
        queryItems: [URLQueryItem] = [],
        accessToken: String? = nil,
        accept: String = "application/json"
    ) -> URLRequest {
        var request = URLRequest(url: configuration.url(path: path, queryItems: queryItems))
        request.setValue(accept, forHTTPHeaderField: "Accept")
        request.setValue(UUID().uuidString, forHTTPHeaderField: "X-Request-ID")
        if let accessToken {
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    /// Builds an authenticated streaming request without sending it. This keeps
    /// stream bodies and credentials inside the same API boundary as REST calls.
    public func makeStreamingRequest(
        path: String,
        method: HTTPMethod = .get,
        body: (some Encodable & Sendable)?,
        queryItems: [URLQueryItem] = [],
        accessToken: String? = nil
    ) throws -> URLRequest {
        var request = makeRequest(
            path: path, queryItems: queryItems, accessToken: accessToken,
            accept: "text/event-stream"
        )
        request.httpMethod = method.rawValue
        request.timeoutInterval = 300
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            do { request.httpBody = try encoder.encode(body) } catch { throw APIError.encoding }
        }
        return request
    }
}
