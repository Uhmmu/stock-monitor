import Foundation

public struct LoginRequest: Codable, Equatable, Sendable {
    public let username: String
    public let password: String
    public let remember: Bool

    public init(username: String, password: String, remember: Bool) {
        self.username = username
        self.password = password
        self.remember = remember
    }
}

public struct RefreshRequest: Codable, Equatable, Sendable {
    public let refreshToken: String

    public init(refreshToken: String) {
        self.refreshToken = refreshToken
    }

    enum CodingKeys: String, CodingKey { case refreshToken = "refresh_token" }
}

public struct AuthTokens: Codable, Equatable, Sendable {
    public let token: String
    public let refreshToken: String
    public let expiresAt: Date
    public let role: String
    public let username: String

    enum CodingKeys: String, CodingKey {
        case token, role, username
        case refreshToken = "refresh_token"
        case expiresAt = "expires_at"
    }
}

public struct CurrentUser: Codable, Equatable, Sendable {
    public let id: Int
    public let username: String
    public let role: String
}

public struct SessionIdentity: Equatable, Sendable {
    public let username: String
    public let role: String

    public init(username: String, role: String) {
        self.username = username
        self.role = role
    }
}

public struct MessageResponse: Codable, Equatable, Sendable {
    public let message: String
}

public struct ErrorEnvelope: Codable, Equatable, Sendable {
    public let detail: String
}
