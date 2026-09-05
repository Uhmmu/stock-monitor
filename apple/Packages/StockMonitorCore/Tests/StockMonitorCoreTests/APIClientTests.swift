import Foundation
@testable import StockMonitorCore
import Testing

@Test func decodesTypedContractAndAddsRequestID() async throws {
    let transport = StubTransport([jsonResponse(tokenJSON)])
    let client = try makeClient(transport: transport)
    let result = try await client.post(
        AuthTokens.self,
        path: "/api/auth/login",
        body: LoginRequest(username: "alice", password: "secret", remember: false)
    )
    #expect(result.username == "alice")
    let requests = await transport.requests
    #expect(requests.first?.value(forHTTPHeaderField: "X-Request-ID") != nil)
}

@Test func queryItemsArePercentEncodedAsURLQueryNotPathText() async throws {
    let transport = StubTransport([jsonResponse(#"{"id":1,"username":"alice","role":"user"}"#)])
    let client = try makeClient(transport: transport)
    let _: CurrentUser = try await client.get(
        CurrentUser.self,
        path: "/api/search",
        queryItems: [URLQueryItem(name: "q", value: "Apple & 日本"), URLQueryItem(name: "limit", value: "8")]
    )
    let request = try #require(await transport.requests.first)
    let url = try #require(request.url)
    #expect(request.url?.path == "/api/search")
    #expect(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first?.value == "Apple & 日本")
}

@Test func noContentMutationAcceptsA204Response() async throws {
    let transport = StubTransport([.response(HTTPResponse(data: Data(), statusCode: 204))])
    let client = try makeClient(transport: transport)
    try await client.requestWithoutResponse(
        path: "/api/watchlist/7", method: .delete, body: String?.none, idempotent: true
    )
    let request = try #require(await transport.requests.first)
    #expect(request.httpMethod == "DELETE")
    #expect(request.value(forHTTPHeaderField: "Idempotency-Key") != nil)
}

@Test func errorEnvelopeAndRequestIDArePreserved() async throws {
    let transport = StubTransport([jsonResponse(#"{"detail":"forbidden"}"#, status: 403, headers: ["x-request-id": "req-1"])])
    let client = try makeClient(transport: transport)
    await #expect(throws: APIError.http(status: 403, message: "forbidden", requestID: "req-1")) {
        let _: CurrentUser = try await client.get(CurrentUser.self, path: "/api/auth/me")
    }
}

@Test func idempotentRequestRetriesServerFailure() async throws {
    let transport = StubTransport([
        jsonResponse(#"{"detail":"temporary"}"#, status: 503),
        jsonResponse(#"{"id":1,"username":"alice","role":"user"}"#),
    ])
    let client = try makeClient(transport: transport, attempts: 2)
    let user: CurrentUser = try await client.get(CurrentUser.self, path: "/api/auth/me")
    #expect(user.id == 1)
    #expect(await transport.requestCount() == 2)
}

@Test func rateLimitRetriesAnIdempotentRequest() async throws {
    let transport = StubTransport([
        jsonResponse(#"{"detail":"slow down"}"#, status: 429),
        jsonResponse(#"{"id":1,"username":"alice","role":"user"}"#),
    ])
    let client = try makeClient(transport: transport, attempts: 2)
    let user: CurrentUser = try await client.get(CurrentUser.self, path: "/api/auth/me")
    #expect(user.username == "alice")
    #expect(await transport.requestCount() == 2)
}

@Test func idempotentMutationUsesOneStableKeyAcrossRetries() async throws {
    let transport = StubTransport([
        jsonResponse(#"{"detail":"temporary"}"#, status: 503),
        jsonResponse(#"{"message":"done"}"#),
    ])
    let client = try makeClient(transport: transport, attempts: 2)
    let result = try await client.post(
        MessageResponse.self,
        path: "/api/example",
        body: ["value": "safe"],
        idempotent: true
    )
    #expect(result.message == "done")
    let requests = await transport.requests
    let keys = requests.compactMap { $0.value(forHTTPHeaderField: "Idempotency-Key") }
    #expect(keys.count == 2)
    #expect(Set(keys).count == 1)
}

@Test func timeoutMapsWithoutLeakingRequestBody() async throws {
    let transport = StubTransport([.urlError(NSURLErrorTimedOut)])
    let client = try makeClient(transport: transport, attempts: 1)
    await #expect(throws: APIError.transport(code: NSURLErrorTimedOut)) {
        let _: CurrentUser = try await client.get(CurrentUser.self, path: "/api/auth/me")
    }
}

@Test func certificateFailureIsFailClosed() async throws {
    let code = URLError.serverCertificateUntrusted.rawValue
    let transport = StubTransport([.urlError(code)])
    let client = try makeClient(transport: transport, attempts: 1)
    await #expect(throws: APIError.transport(code: code)) {
        let _: CurrentUser = try await client.get(CurrentUser.self, path: "/api/auth/me")
    }
}

@Test func cancellingARequestPropagatesCancellation() async throws {
    let client = try makeClient(transport: SuspendedTransport(), attempts: 1)
    let request = Task {
        let _: CurrentUser = try await client.get(CurrentUser.self, path: "/api/auth/me")
    }
    request.cancel()
    await #expect(throws: CancellationError.self) {
        try await request.value
    }
}

private actor SuspendedTransport: HTTPTransport {
    func data(for _: URLRequest) async throws -> HTTPResponse {
        try await Task.sleep(nanoseconds: 30_000_000_000)
        return HTTPResponse(data: Data(), statusCode: 200)
    }
}

private func makeClient(transport: some HTTPTransport, attempts: Int = 1) throws -> APIClient {
    let config = try APIConfiguration(baseURL: URL(string: "https://example.com")!, environment: .staging)
    return APIClient(
        configuration: config,
        transport: transport,
        retryPolicy: RetryPolicy(maximumAttempts: attempts, baseDelayNanoseconds: 0)
    )
}
