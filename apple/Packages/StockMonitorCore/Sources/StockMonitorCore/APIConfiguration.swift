import Foundation

public enum APIEnvironment: String, Sendable {
    case debug
    case staging
    case production
}

public enum ConfigurationError: Error, Equatable, Sendable {
    case invalidBaseURL
    case insecureRemoteURL
}

public struct APIConfiguration: Equatable, Sendable {
    public let baseURL: URL
    public let environment: APIEnvironment

    public init(baseURL: URL, environment: APIEnvironment) throws {
        guard baseURL.host != nil else { throw ConfigurationError.invalidBaseURL }
        let loopbackHosts = ["localhost", "127.0.0.1", "::1"]
        let isExplicitDebugLoopback = environment == .debug && loopbackHosts.contains(baseURL.host ?? "")
        guard baseURL.scheme == "https" || (baseURL.scheme == "http" && isExplicitDebugLoopback) else {
            throw ConfigurationError.insecureRemoteURL
        }
        self.baseURL = baseURL
        self.environment = environment
    }

    public func url(path: String, queryItems: [URLQueryItem] = []) -> URL {
        let url = baseURL.appending(path: path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
        guard !queryItems.isEmpty, var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return url
        }
        components.queryItems = queryItems
        return components.url ?? url
    }

    public static func load(
        bundle: Bundle = .main,
        environment processEnvironment: [String: String] = ProcessInfo.processInfo.environment
    ) throws -> APIConfiguration {
        let rawURL = bundle.object(forInfoDictionaryKey: "StockMonitorAPIBaseURL") as? String
            ?? processEnvironment["STOCK_MONITOR_API_BASE_URL"]
        let rawEnvironment = bundle.object(forInfoDictionaryKey: "StockMonitorAPIEnvironment") as? String
            ?? processEnvironment["STOCK_MONITOR_API_ENVIRONMENT"]
        guard let rawURL,
              let baseURL = URL(string: rawURL),
              let rawEnvironment,
              let environment = APIEnvironment(rawValue: rawEnvironment)
        else {
            throw ConfigurationError.invalidBaseURL
        }
        return try APIConfiguration(baseURL: baseURL, environment: environment)
    }
}
