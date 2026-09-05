import Foundation
@testable import StockMonitorCore
import Testing

@Test func productionRequiresHTTPS() throws {
    #expect(throws: ConfigurationError.insecureRemoteURL) {
        try APIConfiguration(baseURL: #require(URL(string: "http://example.com")), environment: .production)
    }
    _ = try APIConfiguration(baseURL: #require(URL(string: "https://example.com")), environment: .production)
}

@Test func debugHTTPIsLimitedToLoopback() throws {
    _ = try APIConfiguration(baseURL: #require(URL(string: "http://127.0.0.1:8000")), environment: .debug)
    #expect(throws: ConfigurationError.insecureRemoteURL) {
        try APIConfiguration(baseURL: #require(URL(string: "http://192.168.1.10:8000")), environment: .debug)
    }
}

@Test func commandLineBuildCanLoadExplicitEnvironment() throws {
    let configuration = try APIConfiguration.load(environment: [
        "STOCK_MONITOR_API_BASE_URL": "http://127.0.0.1:8000",
        "STOCK_MONITOR_API_ENVIRONMENT": "debug",
    ])
    #expect(configuration.baseURL.absoluteString == "http://127.0.0.1:8000")
}
