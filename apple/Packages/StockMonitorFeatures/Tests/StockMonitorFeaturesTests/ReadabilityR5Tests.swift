import Foundation
import StockMonitorCore
@testable import StockMonitorFeatures
import Testing

@Test func r5WorkspacesUseTaskSectionsInsteadOfFlatEndpointCatalogues() {
    let catalog = GoalM5Catalog()
    let portfolio = R5WorkspaceBlueprint.sections(for: catalog.portfolio)
    #expect(portfolio.first?.title == "组合概览")
    #expect(portfolio.contains { $0.title == "分析任务" })

    let ibkr = R5WorkspaceBlueprint.sections(for: catalog.ibkr)
    #expect(ibkr.first?.title == "账户概览")
    #expect(ibkr.contains { $0.title == "现金、费用与 FX" })

    let quant = R5WorkspaceBlueprint.sections(for: catalog.quant)
    #expect(quant.first?.title == "研究定义")
    #expect(quant.contains { $0.title == "回测" })
    #expect(quant.contains { $0.title == "信号与部署" })
}

@Test func r5ContextualDetailsStayHiddenUntilAnEntityIsSelected() {
    let descriptor = GoalM5Catalog().cryptoResearch
    let initial = R5WorkspaceBlueprint.visibleSections(for: descriptor, contextValues: [:])
    #expect(!initial.flatMap(\.endpoints).contains { $0.semantic == "crypto.latest" })

    let selected = R5WorkspaceBlueprint.visibleSections(
        for: descriptor,
        contextValues: ["instrument_id": "42", "asset_id": "7"]
    )
    #expect(selected.flatMap(\.endpoints).contains { $0.semantic == "crypto.latest" })
    #expect(selected.flatMap(\.endpoints).contains { $0.semantic == "crypto.fundamentals" })
}

@Test func r5EntitySelectorsExposeNamesAndKeepIDsAsTransportDetails() {
    let payload: JSONValue = .object([
        "items": .array([
            .object([
                "instrument_id": .number(42), "asset_id": .number(7),
                "display_label": .string("Bitcoin / USDT"), "symbol": .string("BTC-USDT"),
            ]),
            .object([
                "instrument_id": .number(43), "asset_id": .number(8),
                "display_label": .string("Ethereum / USDT"), "symbol": .string("ETH-USDT"),
            ]),
        ]),
    ])
    let instruments = R5EntityOptionExtractor.options(for: "instrument_id", payload: payload)
    #expect(instruments.map(\.id) == ["42", "43"])
    #expect(instruments.map(\.label) == ["Bitcoin / USDT", "Ethereum / USDT"])
    let assets = R5EntityOptionExtractor.options(for: "asset_id", payload: payload)
    #expect(assets.map(\.id) == ["7", "8"])
}

@Test func r5PortfolioSummaryPreservesFXCoverageGap() {
    let metrics = R5WorkspaceSummary.portfolio(R5FixtureData.portfolio)
    #expect(metrics.contains { $0.id == "value" && $0.value.text.contains("USD") })
    #expect(metrics.contains { $0.id == "coverage" })
    let object = R5FixtureData.portfolio.objectValue
    #expect(object["valuation_available"]?.boolValue == false)
    #expect(object["missing_fx"]?.arrayValue.first?.stringValue == "JPY")
}

@Test func r5DiscoveryFunnelKeepsRawVerifiedAndAcceptedCountsSeparate() {
    let metrics = R5WorkspaceSummary.discovery(R5FixtureData.discovery)
    #expect(metrics.first { $0.id == "raw" }?.value.text == "12")
    #expect(metrics.first { $0.id == "verified" }?.value.text == "10")
    #expect(metrics.first { $0.id == "accepted" }?.value.text == "8")
}

@Test func r5PaperRemainsInternalAndNoManualPlaceholderDefaultsExist() {
    let paper = GoalM5Catalog().paper
    #expect(paper.securityNotice?.contains("仅内部模拟器") == true)
    #expect(!paper.endpoints.flatMap(\.placeholders).contains("account_id"))
    #expect(R5WorkspaceBlueprint.contextualFields(for: GoalM5Catalog().cryptoResearch).contains("instrument_id"))
}

@Test func r5HoldingsKeepLocalPriceAndBaseCurrencyAggregationSeparate() throws {
    let rows = R5PortfolioPositionRow.rows(from: R5FixtureData.portfolio)
    let tokyo = try #require(rows.first { $0.symbol == "1578.T" })
    #expect(tokyo.localPrice.text.contains("JPY"))
    #expect(tokyo.baseMarketValue.qualifier == "数据不足")
    #expect(tokyo.weight.qualifier == "数据不足")
}

@Test func r5TradeLogDraftPreservesBrokerFactsAndEncodesReviewFields() throws {
    let payload: JSONValue = .object([
        "id": .number(9), "trade_date": .string("2026-09-09"), "ticker": .string("NVDA"),
        "direction": .string("buy"), "quantity": .number(20), "price": .number(124.8),
        "note": .string("事实摘要"), "content": .string("复盘正文"), "source_type": .string("ibkr_sync"),
        "status": .string("draft"), "table_rows": .array([]), "photo_urls": .array([]),
    ])
    var draft = try #require(TradeLogDraft(payload: payload))
    draft.content = "更新后的复盘正文"
    #expect(draft.sourceType == "ibkr_sync")
    #expect(draft.requestBody.objectValue["ticker"]?.stringValue == "NVDA")
    #expect(draft.requestBody.objectValue["content"]?.stringValue == "更新后的复盘正文")
}

@Test func r5AnalysisJobBuildsAReadableTimeline() {
    let payload: JSONValue = .object([
        "status": .string("completed"), "created_at": .string("2026-09-10T09:00:00Z"),
        "completed_at": .string("2026-09-10T09:02:00Z"),
    ])
    let entries = R5TimelineBuilder.job(payload)
    #expect(entries.map(\.title) == ["任务已提交", "分析完成"])
}
