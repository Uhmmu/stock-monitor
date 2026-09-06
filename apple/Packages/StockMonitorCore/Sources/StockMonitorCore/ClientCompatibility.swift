import Foundation

public struct ClientCapabilities: Codable, Equatable, Sendable {
    public let apiVersion: String
    public let contractVersion: Int
    public let minimumMacOSClientVersion: String
    public let recommendedMacOSClientVersion: String
    public let capabilities: [String]

    public init(
        apiVersion: String, contractVersion: Int, minimumMacOSClientVersion: String,
        recommendedMacOSClientVersion: String, capabilities: [String]
    ) {
        self.apiVersion = apiVersion
        self.contractVersion = contractVersion
        self.minimumMacOSClientVersion = minimumMacOSClientVersion
        self.recommendedMacOSClientVersion = recommendedMacOSClientVersion
        self.capabilities = capabilities
    }

    enum CodingKeys: String, CodingKey {
        case capabilities
        case apiVersion = "api_version"
        case contractVersion = "contract_version"
        case minimumMacOSClientVersion = "minimum_macos_client_version"
        case recommendedMacOSClientVersion = "recommended_macos_client_version"
    }
}

public enum ClientCompatibilityDecision: Equatable, Sendable {
    case compatible(ClientCapabilities)
    case updateRequired(minimumVersion: String, recommendedVersion: String)
    case serverIncompatible(missingCapabilities: [String])
    case legacyServer
    case unavailable

    public var permitsUse: Bool {
        switch self {
        case .compatible, .legacyServer, .unavailable: true
        case .updateRequired, .serverIncompatible: false
        }
    }
}

public actor ClientCompatibilityService {
    public static let requiredCapabilities: Set<String> = [
        "auth.sessions.v1",
        "market.monitoring.v1",
        "company.research.v1",
        "market.intelligence.v1",
        "ai.workspace.v1",
        "portfolio.workspace.v1",
        "ibkr.server-boundary.v1",
        "crypto.research.v1",
        "quant.internal-paper.v1",
        "administration.role-gated.v1",
    ]

    private let client: APIClient

    public init(client: APIClient) {
        self.client = client
    }

    public func check(currentVersion: String) async -> ClientCompatibilityDecision {
        do {
            let response = try await client.get(ClientCapabilities.self, path: "/api/client-capabilities")
            guard response.contractVersion >= 1 else {
                return .serverIncompatible(missingCapabilities: Self.requiredCapabilities.sorted())
            }
            if Self.compareVersions(currentVersion, response.minimumMacOSClientVersion) == .orderedAscending {
                return .updateRequired(
                    minimumVersion: response.minimumMacOSClientVersion,
                    recommendedVersion: response.recommendedMacOSClientVersion
                )
            }
            let missing = Self.requiredCapabilities.subtracting(response.capabilities).sorted()
            return missing.isEmpty ? .compatible(response) : .serverIncompatible(missingCapabilities: missing)
        } catch APIError.http(status: 404, message: _, requestID: _) {
            // Compatibility metadata was introduced additively. Keep the current
            // app usable during the backend rollout while making legacy state visible.
            return .legacyServer
        } catch {
            // Authentication and resource layers retain their own fail-closed
            // behavior. A transient public handshake failure must not erase a
            // restored session or turn into an availability outage.
            return .unavailable
        }
    }

    public static func compareVersions(_ left: String, _ right: String) -> ComparisonResult {
        let lhs = numericComponents(left)
        let rhs = numericComponents(right)
        for index in 0 ..< max(lhs.count, rhs.count) {
            let leftComponent = index < lhs.count ? lhs[index] : 0
            let rightComponent = index < rhs.count ? rhs[index] : 0
            if leftComponent < rightComponent {
                return .orderedAscending
            }
            if leftComponent > rightComponent {
                return .orderedDescending
            }
        }
        return .orderedSame
    }

    private static func numericComponents(_ version: String) -> [Int] {
        version.split(separator: ".").map { component in
            Int(component.prefix { $0.isNumber }) ?? 0
        }
    }
}
