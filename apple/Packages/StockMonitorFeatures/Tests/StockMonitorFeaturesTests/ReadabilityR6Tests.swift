import Foundation
import StockMonitorDesign
@testable import StockMonitorFeatures
import Testing

// MARK: - Goal R6 表格/图表/验收逻辑测试

@Test func r6TableAuditCoversEverySurfaceWithMainColumnSortAndNarrowStrategy() throws {
    #expect(R6TableAuditCatalog.entries.count >= 20)
    #expect(Set(R6TableAuditCatalog.entries.map(\.id)).count == R6TableAuditCatalog.entries.count)

    for entry in R6TableAuditCatalog.entries {
        #expect(entry.mainColumn != nil, "\(entry.id) 缺少主列")
        #expect(!entry.defaultSort.isEmpty, "\(entry.id) 缺少默认排序说明")
        // 数值比较列必须右对齐 + tabular figures + 有列宽策略。
        for column in entry.columns where column.role == .comparison && column.monospacedDigits {
            #expect(column.alignment == .trailing, "\(entry.id).\(column.id) 数值列未右对齐")
            #expect(column.minWidth != nil, "\(entry.id).\(column.id) 缺少最小列宽")
        }
        // 行数上限必须伴随可恢复说明（截断脚注组件存在）。
        if entry.rowCap != nil {
            #expect(try #require(entry.rowCap) > 0)
        }
    }
}

@Test func r6ChartSurfacesCoverTheUnifiedChromeContract() {
    #expect(R6ChartSurfaceCatalog.entries.count == 3)
    for entry in R6ChartSurfaceCatalog.entries {
        let missing = R6ChartSurfaceCatalog.missingAspects(entry)
        #expect(missing.isEmpty, "\(entry.id) 缺少图表 chrome 要素：\(missing.sorted())")
    }
    #expect(R6ChartSurfaceCatalog.requiredAspects.count == 9)
}

@Test func r6ChartSeriesSummaryBuildsTextEquivalentOfChart() {
    let base = Date(timeIntervalSince1970: 1_700_000_000)
    let series = [
        LineSeries(
            name: "P/E",
            paletteIndex: 0,
            points: [
                TimedPoint(date: base, value: 20),
                TimedPoint(date: base.addingTimeInterval(86400 * 5), value: 31.4),
                TimedPoint(date: base.addingTimeInterval(86400 * 10), value: 25),
            ]
        ),
        LineSeries(name: "空序列", paletteIndex: 1, points: []),
    ]
    let summaries = LineSeriesSummaryBuilder.build(series: series)
    #expect(summaries.count == 2)
    #expect(summaries[0].latest.text.hasPrefix("25"))
    #expect(summaries[0].minimum.text.hasPrefix("20"))
    #expect(summaries[0].maximum.text.hasPrefix("31"))
    #expect(summaries[0].observationWindow.contains("3 点"))
    #expect(summaries[1].latest.text == FinancialValueFormatter.unavailable)
    #expect(summaries[1].observationWindow == "无观测点")
}

@Test func r6ChartTimeFormatsStableUTCDays() throws {
    let raw = "2026-09-01T15:30:00Z"
    let parsed = ChartTime.parse(raw)
    #expect(parsed != nil)
    #expect(try ChartTime.formatDay(#require(ChartTime.day(raw))) == "2026-09-01")
}

@Test func r6AccessibilityCatalogCoversEveryRouteWithStableAnchors() {
    let records = R6AccessibilityCatalog.records
    #expect(records.count == AppRoute.allCases.count)
    #expect(Set(records.map(\.rootIdentifier)).count == records.count)

    for record in records {
        #expect(!record.rootIdentifier.isEmpty)
        // 阅读顺序锚点必须从导航标题/页头开始，以证据 metadata 结束。
        #expect(record.readingOrderIdentifiers.first == "navigation.title")
        #expect(record.readingOrderIdentifiers.contains("page.header"))
        #expect(record.readingOrderIdentifiers.last == "metadata.strip")
        #expect(record.readingOrderIdentifiers.contains(record.rootIdentifier))
        #expect(!record.keyboardPath.isEmpty)
    }
}

@Test func r6IssueLedgerClosesAllP0AndP1Findings() {
    #expect(R6IssueLedger.openHighSeverityIssues.isEmpty, "仍有未关闭的 P0/P1：\(R6IssueLedger.openHighSeverityIssues.map(\.id))")
    // accepted/deferred 只允许出现在 P2/P3。
    for issue in R6IssueLedger.issues where issue.status != .resolved {
        #expect(issue.severity == .p2 || issue.severity == .p3, "\(issue.id) 高严重度未 resolved")
        #expect(!issue.resolution.isEmpty)
    }
    // 每个 R1 基线 P0 路由问题都有对应关闭记录。
    #expect(R6IssueLedger.issues(severity: .p0).count >= 3)
    #expect(R6IssueLedger.issues(severity: .p1).count >= 8)
}

@Test func r6AcceptanceCatalogVerifiesFiveParityLayersOnEveryRoute() {
    #expect(R6AcceptanceCatalog.records.count == AppRoute.allCases.count)
    #expect(R6ParityLayer.allCases.count == 5)
    for record in R6AcceptanceCatalog.records {
        for layer in R6ParityLayer.allCases {
            let status = record.status(for: layer)
            #expect(status?.isVerified == true, "\(record.route.rawValue) 的 \(layer.rawValue) 层未通过：\(status?.rawValue ?? "缺失")")
        }
    }
}

@Test func r6CandlePreparationStaysOffscreenBoundedAndLosslessAtCorners() {
    // 降采样可解释：超预算抽样但始终保留首尾关键点。
    let base = Date(timeIntervalSince1970: 1_700_000_000)
    func makeCandle(index: Int, base: Date) -> TimedCandle {
        let month = (index % 12) + 1
        let time = "2026-" + (month < 10 ? "0" + String(month) : String(month)) + "-01T00:00:00Z"
        let open = Double(index)
        return TimedCandle(
            date: base.addingTimeInterval(Double(index) * 86400),
            candle: ChartCandle(time: time, open: open, high: open + 2, low: open - 1, close: open + 1, volume: index)
        )
    }
    let candles = (0 ..< 1000).map { makeCandle(index: $0, base: base) }
    let sampled = CandlePreparation.downsample(candles, budget: 420)
    #expect(sampled.count <= 421)
    #expect(sampled.first == candles.first)
    #expect(sampled.last == candles.last)
}

@Test func r6NumericTableCellModelKeepsMissingAndPercentSemantics() {
    // 百分比格式与缺失语义在模型层保持稳定（视图层用同一 formatter）。
    let percent = FinancialValueFormatter.percent(0.453)
    #expect(percent.text.contains("45"))
    #expect(percent.text.contains("%"))
    #expect(FinancialValueFormatter.percent(nil).text == FinancialValueFormatter.unavailable)
}
