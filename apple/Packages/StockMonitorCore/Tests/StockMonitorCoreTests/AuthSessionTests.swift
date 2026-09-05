import Foundation
@testable import StockMonitorCore
import Testing

@Test func loginKeepsAccessTokenInMemoryAndRefreshTokenInStore() async throws {
    let transport = StubTransport([jsonResponse(tokenJSON)])
    let store = InMemoryRefreshTokenStore()
    let session = try makeSession(transport: transport, store: store)
    let user = try await session.login(username: "alice", password: "secret", remember: true)
    #expect(user.username == "alice")
    #expect(await store.load() == "refresh-1")
    #expect(await session.state == .authenticated(user))
}

@Test func forbiddenLoginSurfacesTypedFailedState() async throws {
    let transport = StubTransport([jsonResponse(#"{"detail":"pending"}"#, status: 403)])
    let store = InMemoryRefreshTokenStore()
    let session = try makeSession(transport: transport, store: store)
    let expected = APIError.http(status: 403, message: "pending", requestID: nil)
    await #expect(throws: expected) {
        _ = try await session.login(username: "alice", password: "secret", remember: true)
    }
    #expect(await session.state == .failed(expected))
    #expect(await store.load() == nil)
}

@Test func restoreWithoutStoredTokenIsSignedOut() async throws {
    let transport = StubTransport([])
    let session = try makeSession(transport: transport, store: InMemoryRefreshTokenStore())
    await session.restore()
    #expect(await session.state == .signedOut)
}

@Test func offlineRestorePreservesRefreshToken() async throws {
    let transport = StubTransport([.urlError(NSURLErrorNotConnectedToInternet)])
    let store = InMemoryRefreshTokenStore(token: "stored-refresh")
    let session = try makeSession(transport: transport, store: store)
    await session.restore()
    #expect(await session.state == .offline)
    #expect(await store.load() == "stored-refresh")
}

@Test func unauthorizedResponseRefreshesThenRetriesOriginalRequest() async throws {
    let refreshed = """
    {"token":"access-2","refresh_token":"refresh-2","expires_at":"2027-01-01T00:00:00Z",\
    "role":"user","username":"alice"}
    """
    let transport = StubTransport([
        jsonResponse(tokenJSON),
        jsonResponse(#"{"detail":"expired"}"#, status: 401),
        jsonResponse(refreshed),
        jsonResponse(#"{"id":7,"username":"alice","role":"user"}"#),
    ])
    let store = InMemoryRefreshTokenStore()
    let session = try makeSession(transport: transport, store: store)
    _ = try await session.login(username: "alice", password: "secret", remember: true)
    let me: CurrentUser = try await session.authorizedGet(CurrentUser.self, path: "/api/auth/me")
    #expect(me.id == 7)
    #expect(await store.load() == "refresh-2")
}

@Test func concurrentUnauthorizedResponsesShareOneRefresh() async throws {
    let transport = SingleFlightTransport()
    let store = InMemoryRefreshTokenStore()
    let config = try APIConfiguration(baseURL: #require(URL(string: "https://example.com")), environment: .staging)
    let client = APIClient(
        configuration: config,
        transport: transport,
        retryPolicy: RetryPolicy(maximumAttempts: 1, baseDelayNanoseconds: 0)
    )
    let session = AuthSession(client: client, tokenStore: store)
    _ = try await session.login(username: "alice", password: "secret", remember: true)

    async let first: CurrentUser = session.authorizedGet(CurrentUser.self, path: "/api/auth/me")
    async let second: CurrentUser = session.authorizedGet(CurrentUser.self, path: "/api/auth/me")
    let users = try await [first, second]

    #expect(users.allSatisfy { $0.id == 7 })
    #expect(await transport.refreshCount == 1)
}

@Test func rejectedRefreshClearsCredentialsAndPrivateState() async throws {
    let transport = StubTransport([
        jsonResponse(tokenJSON),
        jsonResponse(#"{"detail":"expired"}"#, status: 401),
        jsonResponse(#"{"detail":"refresh rejected"}"#, status: 401),
    ])
    let store = InMemoryRefreshTokenStore()
    let privateDataStore = PrivateDataStoreSpy()
    let config = try APIConfiguration(baseURL: #require(URL(string: "https://example.com")), environment: .staging)
    let client = APIClient(
        configuration: config,
        transport: transport,
        retryPolicy: RetryPolicy(maximumAttempts: 1, baseDelayNanoseconds: 0)
    )
    let session = AuthSession(client: client, tokenStore: store, privateDataStores: [privateDataStore])
    _ = try await session.login(username: "alice", password: "secret", remember: true)

    await #expect(throws: APIError.http(status: 401, message: "refresh rejected", requestID: nil)) {
        let _: CurrentUser = try await session.authorizedGet(CurrentUser.self, path: "/api/auth/me")
    }
    #expect(await store.load() == nil)
    #expect(await privateDataStore.clearCount == 1)
    #expect(await session.state == .signedOut)
}

@Test func logoutClearsLocalCredentialsEvenWhenServerFails() async throws {
    let transport = StubTransport([jsonResponse(tokenJSON), .urlError(NSURLErrorTimedOut)])
    let store = InMemoryRefreshTokenStore()
    let privateDataStore = PrivateDataStoreSpy()
    let config = try APIConfiguration(baseURL: #require(URL(string: "https://example.com")), environment: .staging)
    let client = APIClient(
        configuration: config,
        transport: transport,
        retryPolicy: RetryPolicy(maximumAttempts: 1, baseDelayNanoseconds: 0)
    )
    let session = AuthSession(client: client, tokenStore: store, privateDataStores: [privateDataStore])
    _ = try await session.login(username: "alice", password: "secret", remember: true)
    await session.logout()
    #expect(await store.load() == nil)
    #expect(await privateDataStore.clearCount == 1)
    #expect(await session.state == .signedOut)
}

private func makeSession(transport: StubTransport, store: InMemoryRefreshTokenStore) throws -> AuthSession {
    let config = try APIConfiguration(baseURL: URL(string: "https://example.com")!, environment: .staging)
    let client = APIClient(
        configuration: config,
        transport: transport,
        retryPolicy: RetryPolicy(maximumAttempts: 1, baseDelayNanoseconds: 0)
    )
    return AuthSession(client: client, tokenStore: store)
}
