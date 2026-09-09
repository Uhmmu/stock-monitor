@testable import StockMonitorFeatures
import Testing

// MARK: - R4.0 总览纯逻辑

@Test func overviewBreadthCountsAdvanceDeclineAndUnavailable() {
    let stocks = [
        R4FixtureData.stock("AAA", name: nil, price: 10, previous: 9),
        R4FixtureData.stock("BBB", name: nil, price: 8, previous: 9),
        R4FixtureData.stock("CCC", name: nil, price: 5, previous: 5),
        R4FixtureData.stock("DDD", name: nil, price: nil, previous: nil),
    ]
    let breadth = OverviewSummarizer.breadth(stocks: stocks, liveQuotes: [:])
    #expect(breadth.advancing == 1)
    #expect(breadth.declining == 1)
    #expect(breadth.unchanged == 1)
    #expect(breadth.unavailable == 1)
    #expect(breadth.scanned == 4)
    #expect(breadth.biggestGainer?.ticker == "AAA")
    #expect(breadth.biggestLoser?.ticker == "BBB")
}

@Test func overviewBreadthPrefersLiveQuoteOverSnapshot() {
    let stock = R4FixtureData.stock("AAA", name: nil, price: 10, previous: 9)
    let live = RealtimeQuote(
        symbol: "AAA", price: 8, previousClose: 10, timestamp: nil, receivedAt: nil,
        provider: "tiingo", feed: nil, marketSession: nil, isDelayed: nil,
        delayedSeconds: nil, isStale: false, ageSeconds: nil, sourceType: nil
    )
    let change = OverviewSummarizer.changePercent(stock: stock, live: live) ?? 0
    #expect(abs(change + 20) < 0.0001)
    let breadth = OverviewSummarizer.breadth(stocks: [stock], liveQuotes: ["AAA": live])
    #expect(breadth.declining == 1)
    #expect(breadth.biggestLoser?.ticker == "AAA")
}

// MARK: - R4.0 异动分组纯逻辑

private func alert(_ id: Int, ticker: String, period: String, change: Double, at: String) -> MovementAlert {
    MovementAlert(id: id, ticker: ticker, period: period, changePercent: change, triggeredAt: at)
}

@Test func alertGrouperBucketsByPeriodAndMagnitude() {
    let alerts = [
        alert(1, ticker: "NVDA", period: "day", change: -6.4, at: "2026-09-10T10:02:00Z"),
        alert(2, ticker: "MSFT", period: "day", change: 2.1, at: "2026-09-10T09:44:00Z"),
        alert(3, ticker: "AMD", period: "1h", change: 1.2, at: "2026-09-10T09:30:00Z"),
        alert(4, ticker: "PDD", period: "20m", change: -1.3, at: "2026-09-10T09:21:00Z"),
        alert(5, ticker: "TSLA", period: "price_target", change: 0, at: "2026-09-10T08:00:00Z"),
        alert(6, ticker: "MU", period: "weird", change: 3.3, at: "2026-09-10T07:00:00Z"),
    ]
    let buckets = AlertGrouper.buckets(alerts)
    #expect(buckets.notableDayMoves.map(\.ticker) == ["NVDA"])
    #expect(buckets.intradayMoves.map(\.ticker) == ["MSFT", "AMD"])
    #expect(buckets.briefMoves.map(\.ticker) == ["PDD"])
    #expect(buckets.priceTargets.map(\.ticker) == ["TSLA"])
    #expect(buckets.unclassified.map(\.ticker) == ["MU"])
}

@Test func alertGrouperKeepsTimeDescendingOrderWithinBuckets() {
    let alerts = [
        alert(1, ticker: "A", period: "20m", change: 1, at: "2026-09-10T09:00:00Z"),
        alert(2, ticker: "B", period: "20m", change: 2, at: "2026-09-10T10:00:00Z"),
        alert(3, ticker: "C", period: "20m", change: 3, at: "2026-09-10T08:00:00Z"),
    ]
    #expect(AlertGrouper.buckets(alerts).briefMoves.map(\.ticker) == ["B", "A", "C"])
}

@Test func alertInvestigationLookupPrefersLatestStartedAt() {
    let older = InvestigationItem(
        id: 1, ticker: "NVDA", status: "completed", startedAt: "2026-09-09T10:00:00Z",
        endsAt: "2026-09-09T22:00:00Z", nextSearchAt: nil, newsCount: 3, lastError: nil
    )
    let newer = InvestigationItem(
        id: 2, ticker: "NVDA", status: "active", startedAt: "2026-09-10T10:02:00Z",
        endsAt: "2026-09-10T22:02:00Z", nextSearchAt: nil, newsCount: 6, lastError: nil
    )
    let lookup = AlertGrouper.investigationLookup([older, newer])
    #expect(lookup["NVDA"]?.label == "调查中")
    #expect(AlertGrouper.statusLabel("reporting") == "报告生成中")
    #expect(AlertGrouper.statusLabel("failed") == "调查失败")
    #expect(AlertGrouper.periodTitle("20m") == "20 分钟")
    #expect(AlertGrouper.periodTitle("price_target") == "目标价")
}

@Test func watchlistThresholdDraftRejectsNonPositiveValues() {
    var draft = WatchlistThresholdDraft(stock: ManagedStock(
        ticker: "X", companyName: nil, officialSector: nil, officialIndustry: nil,
        userGroupID: nil, displayOrder: 0, isWatchlisted: true, isPeerReferenced: false,
        peerReferencedBy: [], price: nil, changePercent: nil, alertEnabled: true,
        threshold20m: 2.5, threshold1h: nil, thresholdDay: nil, watchlistID: 1
    ))
    #expect(draft.twenty == 2.5)
    #expect(draft.invalidReason == nil)
    draft.dayString = "-1"
    #expect(draft.invalidReason != nil)
    draft.dayString = ""
    #expect(draft.invalidReason == nil)
}

// MARK: - R4.1 日历与报告纯逻辑

@Test func calendarAgendaGroupsAndSortsByDate() {
    let days = CalendarAgendaBuilder.days(R4FixtureData.calendarEvents.reversed())
    #expect(days.count == 1)
    #expect(days[0].date == "2026-09-11")
    #expect(days[0].events.count == 2)
}

@Test func calendarTypeSemanticsUseSymbolPlusText() {
    #expect(CalendarAgendaBuilder.typeSemantic("earnings") == CalendarEventTypeSemantic(symbol: "doc.text.fill", title: "财报"))
    #expect(CalendarAgendaBuilder.typeSemantic("dividend_ex_date").title == "除息日")
    #expect(CalendarAgendaBuilder.typeSemantic("stock_split").title == "拆股")
    #expect(CalendarAgendaBuilder.typeSemantic("unknown_kind") == CalendarEventTypeSemantic(symbol: "calendar", title: "unknown_kind"))
    #expect(CalendarAgendaBuilder.impactTitle("high") == "影响：高")
    #expect(CalendarAgendaBuilder.impactSemantic("high") == .warning)
}

@Test func calendarConfidenceTextDistinguishesConfirmedAndEstimated() {
    #expect(CalendarAgendaBuilder.confidenceText(R4FixtureData.calendarEvents[0]) == "已确认")
    #expect(CalendarAgendaBuilder.confidenceText(R4FixtureData.calendarEvents[1]) == "预估")
}

@Test func reportOutlineParserExtractsHeadingLevels() {
    let markdown = """
    # 结论
    正文一
    ## 关键事实
    - 列表
    ### 深层细节
    #### 太深不进目录
    ## 风险
    """
    let entries = ReportOutlineParser.entries(from: markdown)
    #expect(entries.map(\.title) == ["结论", "关键事实", "深层细节", "风险"])
    #expect(entries.map(\.level) == [1, 2, 3, 2])
}

@Test func reportSectionParserSplitsBodyAndHeadings() {
    let sections = ReportSectionParser.sections(from: "引言正文\n# 标题 A\n内容 A\n## 标题 B\n内容 B")
    #expect(sections.count == 3)
    #expect(sections[0].heading == nil)
    #expect(sections[0].body == "引言正文")
    #expect(sections[1].heading == "标题 A")
    #expect(sections[2].heading == "标题 B")
    #expect(sections[2].body == "内容 B")
}

// MARK: - R4.2 基本面与财报纯逻辑

@Test func fundamentalsGroupingMapsServerLabels() {
    #expect(FundamentalsMetricGroup.group(forLabel: "P/E") == .valuation)
    #expect(FundamentalsMetricGroup.group(forLabel: "市值(百万)") == .valuation)
    #expect(FundamentalsMetricGroup.group(forLabel: "净利率 %") == .profitability)
    #expect(FundamentalsMetricGroup.group(forLabel: "EPS增速 YoY %") == .growth)
    #expect(FundamentalsMetricGroup.group(forLabel: "ROA %") == .efficiency)
    #expect(FundamentalsMetricGroup.group(forLabel: "52周低") == .risk)
    #expect(FundamentalsMetricGroup.group(forLabel: "未来新增指标") == .other)
}

@Test func fundamentalsGroupedKeepsDeclaredOrderAndSkipsEmptyGroups() {
    let metrics = [
        FundamentalsMetric(label: "Beta", value: 1.2, source: "yahoo"),
        FundamentalsMetric(label: "P/E", value: 30, source: "yahoo"),
    ]
    let groups = FundamentalsMetricGroup.grouped(metrics)
    #expect(groups.map(\.0) == [.valuation, .risk])
    #expect(groups[0].1.map(\.label) == ["P/E"])
}

@Test func fundamentalsDisplayValueFormatsByLabelConvention() {
    #expect(fundamentalsDisplayValue(FundamentalsMetric(label: "净利率 %", value: 55.4, source: "yahoo")).text == "+55.40%")
    #expect(fundamentalsDisplayValue(FundamentalsMetric(label: "营收增速 YoY %", value: -3.2, source: "yahoo")).text == "-3.20%")
    #expect(fundamentalsDisplayValue(FundamentalsMetric(label: "P/E", value: 34.2, source: "yahoo")).text.hasSuffix("×"))
    #expect(fundamentalsDisplayValue(FundamentalsMetric(label: "Beta", value: 1.72, source: "yahoo")).text == "1.72")
    let missing = fundamentalsDisplayValue(FundamentalsMetric(label: "P/B", value: nil, source: nil))
    #expect(missing.text == "—")
    #expect(missing.qualifier == "数据不足")
}

@Test func financialMatrixBuildsColumnsRowsAndYoY() {
    let matrix = FinancialMatrixBuilder.build(quarters: R4FixtureData.quarterlyFinancials)
    // 期间按期末日期倒序：最新财季在最左。
    #expect(matrix.columns.map(\.title) == ["2026 Q2", "2026 Q1", "2025 Q2"])
    #expect(matrix.currency == "USD")
    let revenue = matrix.rows.first { $0.id == "营业收入" }
    #expect(revenue?.cells[0].value == 46_743_000_000)
    let yoy = (46.743 / 30.040 - 1) * 100
    #expect(abs((revenue?.cells[0].yoyPercent ?? -1) - yoy) < 0.01)
    #expect(revenue?.cells[2].yoyPercent == nil)
    let grossMargin = matrix.rows.first { $0.id == "毛利率" }
    // 2026 Q1 缺毛利率：数值与同比都必须为空，而不是显示为 0。
    #expect(grossMargin?.cells[1].value == nil)
    #expect(grossMargin?.cells[1].yoyPercent == nil)
}

// MARK: - R4.2 公司头上下文

@Test @MainActor func companySummaryModelResolvesWatchlistQuote() async {
    let snapshot = DashboardSnapshot(
        market: R4FixtureData.marketOpen,
        stocks: R4FixtureData.overviewStocks
    )
    let model = await CompanySummaryModel(snapshot: snapshot)
    let summary = model.summary(for: "NVDA")
    #expect(summary?.symbol == "NVDA")
    #expect(summary?.companyName == "NVIDIA Corporation")
    #expect(summary?.price == 128.44)
    #expect(summary?.marketOpen == true)

    let missing = model.summary(for: "UNKNOWN")
    #expect(missing?.price == nil)
    #expect(missing?.marketOpen == true)

    await model.loadIfNeeded()
    let unchanged = model.summary(for: "NVDA")
    #expect(unchanged?.symbol == "NVDA")
}
