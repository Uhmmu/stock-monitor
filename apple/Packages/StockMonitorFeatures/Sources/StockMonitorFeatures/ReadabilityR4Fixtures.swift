import Foundation
import StockMonitorDesign
import SwiftUI

// MARK: - R4 离线视觉夹具（确定性像素基线；与生产页面共用同一布局组件）

enum R4FixtureData {
    static let marketOpen = MarketStatus(isOpen: true, session: "regular", checkedAt: "2026-09-10T09:30:00Z")
    static let marketClosed = MarketStatus(isOpen: false, session: "closed", checkedAt: "2026-09-10T09:30:00Z")

    static func stock(
        _ ticker: String, name: String?, price: Double?, previous: Double?,
        source: String? = "tiingo", updatedAt: String? = "2026-09-10T09:30:00Z"
    ) -> DashboardStock {
        DashboardStock(
            ticker: ticker, price: price, previousClose: previous, priceSource: source,
            updatedAt: updatedAt, volume: nil, volumeRatio: nil, volumeLabel: nil, companyName: name
        )
    }

    static var overviewStocks: [DashboardStock] {
        [
            stock("MSFT", name: "Microsoft Corporation", price: 421.90, previous: 418.32),
            stock("NVDA", name: "NVIDIA Corporation", price: 128.44, previous: 125.02),
            stock("1578.T", name: "日本邮船株式会社 Nakamura Congress Fleet", price: 3145, previous: 3187),
            stock("PDD", name: "PDD Holdings Inc.", price: nil, previous: nil),
        ]
    }

    static var indices: [MarketIndex] {
        [
            MarketIndex(symbol: "^GSPC", name: "标普 500", price: 5612.44, previousClose: 5596.21, changePoints: 16.23, changePercent: 0.29),
            MarketIndex(
                symbol: "^IXIC", name: "纳斯达克综合",
                price: 17762.10, previousClose: 17843.55, changePoints: -81.45, changePercent: -0.46
            ),
        ]
    }

    static var alerts: [MovementAlert] {
        [
            MovementAlert(id: 1, ticker: "NVDA", period: "day", changePercent: -6.42, triggeredAt: "2026-09-10T10:02:00Z"),
            MovementAlert(id: 2, ticker: "MSFT", period: "1h", changePercent: 2.18, triggeredAt: "2026-09-10T09:44:00Z"),
            MovementAlert(id: 3, ticker: "PDD", period: "20m", changePercent: -1.31, triggeredAt: "2026-09-10T09:21:00Z"),
        ]
    }

    static var investigations: [InvestigationItem] {
        [
            InvestigationItem(
                id: 1, ticker: "NVDA", status: "active", startedAt: "2026-09-10T10:02:00Z",
                endsAt: "2026-09-10T22:02:00Z", nextSearchAt: nil, newsCount: 6, lastError: nil
            ),
            InvestigationItem(
                id: 2, ticker: "MSFT", status: "completed", startedAt: "2026-09-10T09:44:00Z",
                endsAt: "2026-09-10T11:44:00Z", nextSearchAt: nil, newsCount: 11, lastError: nil
            ),
        ]
    }

    static var newsItems: [NewsItem] {
        [
            NewsItem(
                id: 1, ticker: "NVDA", provider: "Finnhub", title: "NVIDIA shares fall as export controls weigh on data-center outlook",
                translatedTitle: "出口管制压制数据中心前景，英伟达股价走低",
                url: "https://example.com/story", source: nil,
                summary: "一份很长的英文摘要，用于验证正文宽度、leading 与段落层级，不会被次要颜色或过小字号吞掉。",
                topic: nil, publishedAt: "2026-09-10T09:58:00Z", foundAt: "2026-09-10T10:00:00Z",
                aiSummary: "**核心事实**：财报指引下调，市场情绪转为谨慎。", aiAnalysis: nil,
                aiSummaryStatus: "ready", aiSummaryGeneratedAt: "2026-09-10T10:05:00Z"
            ),
            NewsItem(
                id: 2, ticker: nil, provider: "Marketaux", title: "Fed officials signal patience on rate cuts",
                translatedTitle: nil, url: nil, source: nil, summary: nil, topic: "宏观",
                publishedAt: "2026-09-10T08:30:00Z", foundAt: "2026-09-10T08:31:00Z",
                aiSummary: nil, aiAnalysis: nil, aiSummaryStatus: "pending", aiSummaryGeneratedAt: nil
            ),
        ]
    }

    static var calendarEvents: [CalendarEvent] {
        [
            CalendarEvent(
                id: "e1", eventType: "earnings", symbol: "MSFT", companyName: "Microsoft",
                title: "Microsoft 财报（盘后）", description: nil, eventDate: "2026-09-11",
                eventTime: "16:30", timeStatus: "confirmed", isConfirmed: true, isEstimated: false,
                confidence: nil, impactLevel: "high", primarySource: "Yahoo + Finnhub",
                hasConflict: false, portfolioRelevance: true, watchlistRelevance: true,
                fetchedAt: nil, stale: false, warning: nil
            ),
            CalendarEvent(
                id: "e2", eventType: "dividend_ex_date", symbol: "NVDA", companyName: "NVIDIA",
                title: "NVIDIA 除息日", description: nil, eventDate: "2026-09-11",
                eventTime: nil, timeStatus: "estimated", isConfirmed: false, isEstimated: true,
                confidence: nil, impactLevel: "medium", primarySource: "Yahoo",
                hasConflict: false, portfolioRelevance: false, watchlistRelevance: true,
                fetchedAt: nil, stale: true, warning: nil
            ),
        ]
    }

    static var reports: [ReportSummary] {
        [
            ReportSummary(
                id: 1, ticker: "NVDA", reportType: "movement", title: "NVDA 异动日报",
                model: "gpt-5.4", createdAt: "2026-09-10T10:05:00Z", confidence: "中"
            ),
            ReportSummary(
                id: 2, ticker: "MSFT", reportType: "postmarket", title: "MSFT 收盘点评",
                model: "gpt-5.4", createdAt: "2026-09-09T22:40:00Z", confidence: "高"
            ),
        ]
    }

    static var fundamentalsMetrics: [FundamentalsMetric] {
        [
            FundamentalsMetric(label: "P/E", value: 34.2, source: "yahoo"),
            FundamentalsMetric(label: "P/B", value: 41.8, source: "yahoo"),
            FundamentalsMetric(label: "P/S", value: 26.1, source: "yahoo"),
            FundamentalsMetric(label: "市值(百万)", value: 3_150_000, source: "yahoo"),
            FundamentalsMetric(label: "毛利率 %", value: 75.0, source: "yahoo"),
            FundamentalsMetric(label: "净利率 %", value: 55.4, source: "yahoo"),
            FundamentalsMetric(label: "营收增速 YoY %", value: 40.9, source: "yahoo"),
            FundamentalsMetric(label: "EPS增速 YoY %", value: 58.2, source: "yahoo"),
            FundamentalsMetric(label: "ROE %", value: 91.5, source: "yahoo"),
            FundamentalsMetric(label: "ROA %", value: 62.3, source: "yahoo"),
            FundamentalsMetric(label: "Beta", value: 1.72, source: "yahoo"),
            FundamentalsMetric(label: "52周高", value: 140.24, source: "yahoo"),
            FundamentalsMetric(label: "52周低", value: 86.62, source: "yahoo"),
        ]
    }

    static var quarterlyFinancials: [QuarterlyFinancialRow] {
        [
            QuarterlyFinancialRow(
                fiscalYear: 2026, fiscalPeriod: "Q2", periodEnd: "2026-07-31", filedAt: nil,
                currency: "USD", revenue: 46_743_000_000, eps: 0.81, netIncome: 20_143_000_000,
                operatingIncome: nil, grossMargin: 74.9, netMargin: 43.1, operatingCashFlow: 19_800_000_000,
                freeCashFlow: 17_200_000_000, source: "fmp", syncedAt: nil
            ),
            QuarterlyFinancialRow(
                fiscalYear: 2025, fiscalPeriod: "Q2", periodEnd: "2025-07-31", filedAt: nil,
                currency: "USD", revenue: 30_040_000_000, eps: 0.40, netIncome: 16_599_000_000,
                operatingIncome: nil, grossMargin: 74.3, netMargin: 55.3, operatingCashFlow: 14_200_000_000,
                freeCashFlow: 11_700_000_000, source: "fmp", syncedAt: nil
            ),
            QuarterlyFinancialRow(
                fiscalYear: 2026, fiscalPeriod: "Q1", periodEnd: "2026-04-30", filedAt: nil,
                currency: "USD", revenue: 44_062_000_000, eps: 0.76, netIncome: 18_775_000_000,
                operatingIncome: nil, grossMargin: nil, netMargin: 42.6, operatingCashFlow: nil,
                freeCashFlow: nil, source: "fmp", syncedAt: nil
            ),
        ]
    }

    static var companySummary: CompanyHeaderSummary {
        CompanyHeaderSummary(
            symbol: "NVDA", companyName: "NVIDIA Corporation", price: 128.44, changePercent: 2.74,
            marketOpen: true, marketSession: "regular", priceSource: "tiingo", updatedAt: "2026-09-10T09:30:00Z"
        )
    }
}

// MARK: - R4 离线视觉夹具（确定性像素基线；与生产页面共用同一布局组件）

/// Before：R4 之前的总览布局（重复标题 + 未对齐 LabeledContent + caption 次要色）。
struct R4BeforeOverviewFixture: View {
    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 22) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("市场总览").font(.title2.bold())
                        Text("美股常规交易时段").font(.callout).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text("快照").font(.callout).foregroundStyle(.secondary)
                }
                HStack(spacing: 12) {
                    ForEach(R4FixtureData.indices) { index in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(index.name).font(.caption).foregroundStyle(.secondary)
                            Text(index.price.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
                                .font(.title3.monospacedDigit().weight(.semibold))
                            Text((index.changePercent ?? 0).formatted())
                                .font(.caption).foregroundStyle((index.changePercent ?? 0) > 0 ? .green : .red)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(14)
                        .background(.background.secondary, in: .rect(cornerRadius: 10))
                    }
                }
                HStack(spacing: 18) {
                    LabeledContent("组合", value: "12.34%")
                    LabeledContent("标普 500", value: "8.20%")
                    LabeledContent("纳指 100", value: "10.05%")
                }.monospacedDigit()
                VStack(alignment: .leading, spacing: 8) {
                    Text("最近异动").font(.title2.bold())
                    ForEach(R4FixtureData.alerts) { alert in
                        HStack {
                            Text(alert.ticker).fontWeight(.semibold)
                            Text(alert.period).font(.caption).foregroundStyle(.secondary)
                            Spacer()
                            Text(alert.changePercent.formatted()).foregroundStyle(alert.changePercent > 0 ? .green : .red)
                        }.padding(.vertical, 4)
                    }
                }
            }
            .padding(24)
        }
        .background(StockMonitorCanvas.background)
    }
}

/// After：R4.0 总览首屏——四状态 + 对齐指数条 + 变化与报告。
struct R4AfterOverviewFixture: View {
    var body: some View {
        PageScaffold(width: StockMonitorContentWidth.wide) {
            PageHeader("市场总览", summary: "美股常规交易时段") {
                SemanticStatusLabel("快照", status: .stale)
            }
        } content: {
            OverviewCoreStateStrip(
                marketOpen: true,
                marketSession: "regular",
                portfolioReturnPercent: 12.34,
                portfolioConfigured: true,
                breadth: OverviewSummarizer.breadth(stocks: R4FixtureData.overviewStocks, liveQuotes: [:]),
                alertCount: R4FixtureData.alerts.count,
                latestAlertDescription: "NVDA -6.42%"
            )
            SectionHeader("指数", explanation: "收盘价与涨跌在每一行对齐；涨跌同时提供符号、点数与百分比。")
            IndexMetricStrip(indices: R4FixtureData.indices)
            SectionHeader("值得关注的变化") {
                Button("全部异动") {}
            }
            VStack(alignment: .leading, spacing: 0) {
                ForEach(R4FixtureData.alerts) { alert in
                    AlertSummaryRow(alert: alert, investigationLabel: "调查中", investigationSemantic: .info, openStock: { _ in })
                    Divider()
                }
            }
        }
        .background(StockMonitorCanvas.background)
    }
}

/// After：R4.0 自选股表格（排序/分组/徽标/交替行）。
struct R4AfterWatchlistFixture: View {
    @State private var selection: String?

    private static let stocks: [ManagedStock] = [
        ManagedStock(
            ticker: "MSFT", companyName: "Microsoft Corporation", officialSector: nil, officialIndustry: "软件—基础设施",
            userGroupID: 1, displayOrder: 0, isWatchlisted: true, isPeerReferenced: false, peerReferencedBy: [],
            price: 421.90, changePercent: 0.86, alertEnabled: true,
            threshold20m: nil, threshold1h: nil, thresholdDay: nil, watchlistID: 11
        ),
        ManagedStock(
            ticker: "NVDA", companyName: "NVIDIA Corporation", officialSector: nil, officialIndustry: "半导体",
            userGroupID: 1, displayOrder: 1, isWatchlisted: true, isPeerReferenced: true, peerReferencedBy: ["AMD"],
            price: 128.44, changePercent: 2.74, alertEnabled: false,
            threshold20m: 2.5, threshold1h: nil, thresholdDay: nil, watchlistID: 12
        ),
        ManagedStock(
            ticker: "1578.T", companyName: "日本郵船株式会社 Nakamura Congress Fleet Holdings", officialSector: nil, officialIndustry: "海运",
            userGroupID: nil, displayOrder: 2, isWatchlisted: true, isPeerReferenced: false, peerReferencedBy: [],
            price: nil, changePercent: nil, alertEnabled: true,
            threshold20m: nil, threshold1h: nil, thresholdDay: nil, watchlistID: 13
        ),
    ]

    var body: some View {
        Table(Self.stocks, selection: $selection) {
            TableColumn("代码") { (stock: ManagedStock) in
                HStack(spacing: StockMonitorSpacing.small) {
                    Text(stock.ticker).fontWeight(.semibold)
                    if stock.isPeerReferenced {
                        Image(systemName: "link").foregroundStyle(.secondary)
                    }
                }
            }
            .width(min: 80, ideal: 100)
            TableColumn("公司") { (stock: ManagedStock) in
                Text(stock.companyName ?? "名称数据不足")
            }
            TableColumn("分组") { (stock: ManagedStock) in
                Text(stock.userGroupID == 1 ? "核心持仓观察" : "未分组").stockMonitorTypography(.metadata)
            }
            TableColumn("价格") { (stock: ManagedStock) in
                Text(stock.price?.formatted(.number.precision(.fractionLength(2))) ?? FinancialValueFormatter.unavailable)
                    .financialFigures()
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
            TableColumn("涨跌") { (stock: ManagedStock) in
                ChangeLabel(value: stock.changePercent)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
            TableColumn("提醒") { (stock: ManagedStock) in
                SemanticStatusLabel(stock.alertEnabled ? "提醒开" : "提醒关", status: stock.alertEnabled ? .live : .unavailable)
            }
        }
        .alternatingRowBackgrounds(.enabled)
        .padding(StockMonitorSpacing.regular)
        .background(StockMonitorCanvas.background)
    }
}

/// After：R4.0 异动中心分组。
struct R4AfterAlertsFixture: View {
    var body: some View {
        PageScaffold {
            PageHeader("异动中心", summary: "首行说明发生了什么；调查状态跟随每条异动。") {
                SemanticStatusLabel("\(R4FixtureData.alerts.count) 条异动", status: .info)
            }
        } content: {
            let buckets = AlertGrouper.buckets(R4FixtureData.alerts)
            let lookup = AlertGrouper.investigationLookup(R4FixtureData.investigations)
            SectionHeader("需要关注", explanation: "当日幅度 ≥ 5% 的代表性异动。")
            alertList(buckets.notableDayMoves, lookup: lookup)
            SectionHeader("盘中异动", explanation: "当日一般幅度与 1 小时窗口触发的异动。")
            alertList(buckets.intradayMoves, lookup: lookup)
            SectionHeader("短时波动", explanation: "20 分钟窗口触发，通常噪音更高。")
            alertList(buckets.briefMoves, lookup: lookup)
            SectionHeader("调查任务", explanation: "每条异动最多关联一个调查；状态由服务端任务推进。")
            TimelineList(R4FixtureData.investigations.map { item in
                TimelineEntry(
                    id: "\(item.id)",
                    title: "\(item.ticker) · \(AlertGrouper.statusLabel(item.status))",
                    timestamp: "2026-09-10 10:02",
                    detail: "已收集 \(item.newsCount) 条新闻",
                    systemImage: item.status == "completed" ? "checkmark.circle.fill" : "circle.dashed"
                )
            })
        }
        .background(StockMonitorCanvas.background)
    }

    private func alertList(_ alerts: [MovementAlert], lookup: [String: (status: String, label: String)]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(alerts) { alert in
                AlertSummaryRow(
                    alert: alert,
                    investigationLabel: lookup[alert.ticker]?.label,
                    investigationSemantic: AlertGrouper.statusSemantic(lookup[alert.ticker]?.status ?? ""),
                    openStock: { _ in }
                )
                Divider()
            }
        }
    }
}

/// After：R4.1 新闻行（标题主导 + 次级 metadata + AI 徽标）。
struct R4AfterNewsFixture: View {
    var body: some View {
        PageScaffold {
            PageHeader("新闻中心", summary: "标题、证券、来源、时间与 AI 状态分层呈现。") {
                SemanticStatusLabel("128 条", status: .info)
            }
        } content: {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(R4FixtureData.newsItems) { item in
                    NewsListRow(item: item, openStock: { _ in })
                    Divider()
                }
            }
        }
        .background(StockMonitorCanvas.background)
    }
}

/// After：R4.1 日历议程（类型符号 + 文字 + 影响徽标）。
struct R4AfterCalendarFixture: View {
    var body: some View {
        PageScaffold {
            PageHeader("投资日历", summary: "按日议程分组；事件类型同时提供符号与文字。") {
                SemanticStatusLabel("2 条事件", status: .info)
            }
        } content: {
            ForEach(CalendarAgendaBuilder.days(R4FixtureData.calendarEvents)) { day in
                SectionHeader(day.date, explanation: "\(day.events.count) 条事件")
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(day.events) { event in
                        CalendarAgendaRow(event: event, openStock: { _ in })
                        Divider()
                    }
                }
            }
        }
        .background(StockMonitorCanvas.background)
    }
}

/// After：R4.1 报告阅读（目录 + 元信息 + 复制/回证券）。
struct R4AfterReportsFixture: View {
    private static let detail = ReportDetail(
        id: 1, ticker: "NVDA", reportType: "movement",
        title: "NVDA 异动日报：出口管制与数据中心预期",
        content: """
        # 结论
        短期承压来源是出口管制预期，而非基本面恶化。

        # 关键事实
        - 数据中心营收指引下调 4%
        - 毛利率保持 74% 以上

        ## 风险
        政策落地节奏不确定；长期需求未见拐点。

        # 附录
        数据截至 2026-09-10 收盘。
        """,
        model: "gpt-5.4", createdAt: "2026-09-10T10:05:00Z"
    )

    var body: some View {
        HSplitView {
            VStack(spacing: 0) {
                HStack(spacing: StockMonitorSpacing.small) {
                    TextField("搜索标题或代码", text: .constant(""))
                        .textFieldStyle(.roundedBorder)
                    Text("2 份").stockMonitorTypography(.metadata)
                }
                .padding(StockMonitorSpacing.regular)
                Divider()
                List([R4FixtureData.reports[0]]) { report in
                    ReportListRow(report: report).tag(report.id)
                }
            }.frame(width: 300)
            ReportReaderView(report: Self.detail, openStock: { _ in })
        }
        .background(StockMonitorCanvas.background)
    }
}

/// Before：R4 之前的公司页（均匀指标卡墙 + caption2 来源）。
struct R4BeforeCompanyFixture: View {
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Text("基本面指标").font(.title2.bold())
                    Spacer()
                    Text("NVDA").font(.callout)
                }
                HStack(spacing: 16) {
                    LabeledContent("证券", value: "NVDA")
                    LabeledContent("查询时间", value: "2026-09-10 09:30")
                }.font(.callout)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 220))], spacing: 10) {
                    ForEach(R4FixtureData.fundamentalsMetrics) { metric in
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(metric.label).font(.callout)
                                Spacer()
                                Text(metric.source ?? "—").font(.caption2).foregroundStyle(.secondary)
                            }
                            Text(metric.value.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
                                .font(.title3.monospacedDigit().weight(.semibold))
                        }
                        .padding(12)
                        .background(.background.secondary, in: .rect(cornerRadius: 10))
                    }
                }
            }
            .padding(24)
        }
        .background(StockMonitorCanvas.background)
    }
}

/// After：R4.2 公司头 + 基本面分组 + 财报矩阵。
struct R4AfterCompanyFixture: View {
    var body: some View {
        PageScaffold(width: StockMonitorContentWidth.wide) {
            PageHeader("基本面", summary: "按估值、盈利、成长、效率与风险分组；Yahoo 为主数据源。") {
                Text("NVDA").stockMonitorTypography(.metadata)
            }
        } content: {
            CompanyHeaderView(summary: R4FixtureData.companySummary)
            ForEach(FundamentalsMetricGroup.grouped(R4FixtureData.fundamentalsMetrics).prefix(3), id: \.0) { group, values in
                SectionHeader(group.rawValue)
                MetricGrid(values.map { metric in
                    MetricItem(
                        id: metric.label,
                        label: metric.label,
                        value: fundamentalsDisplayValue(metric),
                        status: metric.value == nil ? .unavailable : .neutral
                    )
                })
            }
            SectionHeader("季度关键指标", explanation: "最新期间在最左；同比仅在存在上年同季数据时显示。")
            FinancialMatrixTable(matrix: FinancialMatrixBuilder.build(quarters: R4FixtureData.quarterlyFinancials))
        }
        .background(StockMonitorCanvas.background)
    }
}
