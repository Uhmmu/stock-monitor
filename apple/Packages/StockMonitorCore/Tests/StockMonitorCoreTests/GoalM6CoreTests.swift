import Foundation
@testable import StockMonitorCore
import Testing

@Test func compatibilityHandshakeAcceptsCompleteServerContract() async throws {
    let transport = StubTransport([jsonResponse("""
    {"api_version":"0.1.0","contract_version":1,"minimum_macos_client_version":"0.1.0",\
    "recommended_macos_client_version":"0.1.0","capabilities":[\
    "auth.sessions.v1","market.monitoring.v1","company.research.v1","market.intelligence.v1",\
    "ai.workspace.v1","portfolio.workspace.v1","ibkr.server-boundary.v1","crypto.research.v1",\
    "quant.internal-paper.v1","administration.role-gated.v1"]}
    """)])
    let configuration = try APIConfiguration(baseURL: #require(URL(string: "https://example.com")), environment: .production)
    let decision = await ClientCompatibilityService(client: APIClient(configuration: configuration, transport: transport))
        .check(currentVersion: "0.1.0")

    #expect(decision.permitsUse)
    guard case let .compatible(response) = decision else {
        Issue.record("expected compatible response")
        return
    }
    #expect(response.contractVersion == 1)
}

@Test func compatibilityHandshakeBlocksOldClientAndMissingCapabilities() async throws {
    let oldClientTransport = StubTransport([jsonResponse("""
    {"api_version":"0.2.0","contract_version":1,"minimum_macos_client_version":"0.2.0",\
    "recommended_macos_client_version":"0.3.0","capabilities":[]}
    """)])
    let configuration = try APIConfiguration(baseURL: #require(URL(string: "https://example.com")), environment: .production)
    let oldClient = await ClientCompatibilityService(client: APIClient(configuration: configuration, transport: oldClientTransport))
        .check(currentVersion: "0.1.9")
    #expect(oldClient == .updateRequired(minimumVersion: "0.2.0", recommendedVersion: "0.3.0"))
    #expect(!oldClient.permitsUse)

    let missingTransport = StubTransport([jsonResponse("""
    {"api_version":"0.1.0","contract_version":1,"minimum_macos_client_version":"0.1.0",\
    "recommended_macos_client_version":"0.1.0","capabilities":["auth.sessions.v1"]}
    """)])
    let missing = await ClientCompatibilityService(client: APIClient(configuration: configuration, transport: missingTransport))
        .check(currentVersion: "0.1.0")
    guard case let .serverIncompatible(capabilities) = missing else {
        Issue.record("expected a missing-capability decision")
        return
    }
    #expect(capabilities.contains("ibkr.server-boundary.v1"))
    #expect(!missing.permitsUse)
}

@Test func compatibilityHandshakeAllowsVisibleLegacyRolloutAndVersionComparisonIsNumeric() async throws {
    let transport = StubTransport([jsonResponse(#"{"detail":"not found"}"#, status: 404)])
    let configuration = try APIConfiguration(baseURL: #require(URL(string: "https://example.com")), environment: .production)
    let decision = await ClientCompatibilityService(client: APIClient(configuration: configuration, transport: transport))
        .check(currentVersion: "0.1.0")
    #expect(decision == .legacyServer)
    #expect(ClientCompatibilityService.compareVersions("1.10.0", "1.9.9") == .orderedDescending)
    #expect(ClientCompatibilityService.compareVersions("1.0", "1.0.0") == .orderedSame)
}

@Test func supportDiagnosticsExcludePrivateInvestmentAndRequestData() {
    let report = SupportDiagnostics(
        generatedAt: Date(timeIntervalSince1970: 0), appVersion: "0.1.0", buildNumber: "1",
        operatingSystem: "macOS Test", architecture: "arm64", compatibilityState: "compatible",
        metrics: .init(requestCount: 4, cacheHits: 1, streamReconnects: 2, parseMilliseconds: [2, 4], frameHitches: 0)
    ).text.lowercased()

    #expect(report.contains("average_parse_ms: 3.00"))
    #expect(report.contains("no tokens"))
    #expect(!report.contains("bearer"))
    #expect(!report.contains("aapl"))
    #expect(!report.contains("/api/"))
}
