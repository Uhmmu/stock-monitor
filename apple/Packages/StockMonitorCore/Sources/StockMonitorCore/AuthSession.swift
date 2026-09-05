import Foundation

public protocol PrivateDataClearing: Sendable {
    func clearPrivateData() async
}

public enum AuthState: Equatable, Sendable {
    case signedOut
    case restoring
    case authenticated(SessionIdentity)
    case offline
    case failed(APIError)
}

public actor AuthSession {
    private let client: APIClient
    private let tokenStore: any RefreshTokenStore
    private let privateDataStores: [any PrivateDataClearing]
    private var accessToken: String?
    private var refreshTask: Task<AuthTokens, Error>?
    public private(set) var state: AuthState = .signedOut

    public init(
        client: APIClient,
        tokenStore: any RefreshTokenStore,
        privateDataStores: [any PrivateDataClearing] = []
    ) {
        self.client = client
        self.tokenStore = tokenStore
        self.privateDataStores = privateDataStores
    }

    @discardableResult
    public func login(username: String, password: String, remember: Bool) async throws -> SessionIdentity {
        do {
            let tokens = try await client.post(
                AuthTokens.self,
                path: "/api/auth/login",
                body: LoginRequest(username: username, password: password, remember: remember)
            )
            return try await adopt(tokens)
        } catch let error as APIError {
            state = .failed(error)
            throw error
        }
    }

    public func restore() async {
        state = .restoring
        do {
            guard try await (tokenStore.load()) != nil else {
                state = .signedOut
                return
            }
            _ = try await refresh()
        } catch let error as APIError where error.isOffline {
            state = .offline
        } catch let error as APIError {
            try? await tokenStore.delete()
            state = .failed(error)
        } catch {
            state = .signedOut
        }
    }

    public func logout() async {
        if let refreshToken = try? await tokenStore.load() {
            _ = try? await client.post(
                MessageResponse.self,
                path: "/api/auth/logout",
                body: RefreshRequest(refreshToken: refreshToken),
                idempotent: true
            )
        }
        await clearLocalSession()
    }

    public func authorizedGet<Response: Decodable & Sendable>(
        _ responseType: Response.Type, path: String, queryItems: [URLQueryItem] = []
    ) async throws -> Response {
        guard let accessToken else { throw APIError.http(status: 401, message: nil, requestID: nil) }
        do {
            return try await client.get(responseType, path: path, queryItems: queryItems, accessToken: accessToken)
        } catch APIError.http(status: 401, message: _, requestID: _) {
            _ = try await refresh()
            guard let renewedAccessToken = self.accessToken else {
                throw APIError.http(status: 401, message: nil, requestID: nil)
            }
            return try await client.get(responseType, path: path, queryItems: queryItems, accessToken: renewedAccessToken)
        }
    }

    public func authorizedRequest<Response: Decodable & Sendable>(
        _ responseType: Response.Type,
        path: String,
        method: HTTPMethod,
        body: (some Encodable & Sendable)?,
        queryItems: [URLQueryItem] = [],
        idempotent: Bool = false
    ) async throws -> Response {
        guard let accessToken else { throw APIError.http(status: 401, message: nil, requestID: nil) }
        do {
            return try await client.request(
                responseType, path: path, method: method, body: body,
                queryItems: queryItems, accessToken: accessToken, idempotent: idempotent
            )
        } catch APIError.http(status: 401, message: _, requestID: _) {
            _ = try await refresh()
            guard let renewedAccessToken = self.accessToken else {
                throw APIError.http(status: 401, message: nil, requestID: nil)
            }
            return try await client.request(
                responseType, path: path, method: method, body: body,
                queryItems: queryItems, accessToken: renewedAccessToken, idempotent: idempotent
            )
        }
    }

    public func authorizedRequestWithoutResponse(
        path: String,
        method: HTTPMethod,
        body: (some Encodable & Sendable)?,
        queryItems: [URLQueryItem] = [],
        idempotent: Bool = false
    ) async throws {
        guard let accessToken else { throw APIError.http(status: 401, message: nil, requestID: nil) }
        do {
            try await client.requestWithoutResponse(
                path: path, method: method, body: body,
                queryItems: queryItems, accessToken: accessToken, idempotent: idempotent
            )
        } catch APIError.http(status: 401, message: _, requestID: _) {
            _ = try await refresh()
            guard let renewedAccessToken = self.accessToken else {
                throw APIError.http(status: 401, message: nil, requestID: nil)
            }
            try await client.requestWithoutResponse(
                path: path, method: method, body: body,
                queryItems: queryItems, accessToken: renewedAccessToken, idempotent: idempotent
            )
        }
    }

    public func authorizedSSERequest(path: String, queryItems: [URLQueryItem]) async throws -> URLRequest {
        guard let accessToken else { throw APIError.http(status: 401, message: nil, requestID: nil) }
        return await client.makeRequest(
            path: path, queryItems: queryItems, accessToken: accessToken, accept: "text/event-stream"
        )
    }

    private func refresh() async throws -> SessionIdentity {
        let task: Task<AuthTokens, Error>
        if let refreshTask {
            task = refreshTask
        } else {
            guard let refreshToken = try await tokenStore.load() else {
                throw APIError.http(status: 401, message: nil, requestID: nil)
            }
            task = Task { [client] in
                try await client.post(
                    AuthTokens.self,
                    path: "/api/auth/refresh",
                    body: RefreshRequest(refreshToken: refreshToken)
                )
            }
            refreshTask = task
        }
        do {
            let tokens = try await task.value
            refreshTask = nil
            return try await adopt(tokens)
        } catch {
            refreshTask = nil
            if let apiError = error as? APIError {
                switch apiError {
                case .http(status: 401, message: _, requestID: _),
                     .http(status: 403, message: _, requestID: _):
                    await clearLocalSession()
                default:
                    break
                }
            }
            throw error
        }
    }

    private func adopt(_ tokens: AuthTokens) async throws -> SessionIdentity {
        try await tokenStore.save(tokens.refreshToken)
        accessToken = tokens.token
        let identity = SessionIdentity(username: tokens.username, role: tokens.role)
        state = .authenticated(identity)
        return identity
    }

    private func clearLocalSession() async {
        accessToken = nil
        try? await tokenStore.delete()
        for store in privateDataStores {
            await store.clearPrivateData()
        }
        state = .signedOut
    }
}
