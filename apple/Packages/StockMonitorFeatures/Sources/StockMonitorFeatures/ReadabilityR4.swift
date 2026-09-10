import Foundation
import Observation
import StockMonitorCore
import StockMonitorDesign
import SwiftUI

// MARK: - 涨跌标签（R4.0：符号 + 数值 + 可访问描述，颜色不是唯一编码）

struct ChangeLabel: View {
    let value: Double?

    var body: some View {
        if let value, value.isFinite {
            HStack(alignment: .firstTextBaseline, spacing: StockMonitorSpacing.xSmall) {
                Image(systemName: arrowSymbol)
                    .font(.caption.weight(.bold))
                    .accessibilityHidden(true)
                Text(value.formatted(.number.precision(.fractionLength(2)).sign(strategy: .always())) + "%")
            }
            .monospacedDigit()
            .foregroundStyle(color)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("\(directionText) \(value.formatted(.number.precision(.fractionLength(2)).sign(strategy: .always()))) 百分比")
        } else {
            Text(FinancialValueFormatter.unavailable).foregroundStyle(.secondary)
        }
    }

    private var arrowSymbol: String {
        switch value {
        case let .some(change) where change > 0: "arrow.up"
        case let .some(change) where change < 0: "arrow.down"
        default: "minus"
        }
    }

    private var directionText: String {
        switch value {
        case let .some(change) where change > 0: "上涨"
        case let .some(change) where change < 0: "下跌"
        default: "持平"
        }
    }

    private var color: Color {
        switch value {
        case let .some(change) where change > 0: StockMonitorChartPalette.positive
        case let .some(change) where change < 0: StockMonitorChartPalette.negative
        default: .secondary
        }
    }
}

// MARK: - 对齐的市场指数条（R4.0）

/// 指数名称、价格与涨跌在同一个 Grid 中对齐；涨跌同时有点数与百分比。
struct IndexMetricStrip: View {
    let indices: [MarketIndex]

    var body: some View {
        Grid(alignment: .leading, horizontalSpacing: StockMonitorSpacing.medium, verticalSpacing: StockMonitorSpacing.small) {
            ForEach(indices) { index in
                GridRow {
                    Text(index.name)
                        .stockMonitorTypography(.metricLabel)
                        .frame(minWidth: 96, alignment: .leading)
                    Text(index.price.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? FinancialValueFormatter.unavailable)
                        .financialFigures()
                        .gridColumnAlignment(.trailing)
                    changeCell(index)
                }
                Divider()
            }
        }
        .padding(StockMonitorSpacing.medium)
        .stockMonitorSurface(.grouped)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("r4.overview.indices")
    }

    private func changeCell(_ index: MarketIndex) -> some View {
        VStack(alignment: .trailing, spacing: 1) {
            if let points = index.changePoints {
                Text(points.formatted(.number.precision(.fractionLength(2)).sign(strategy: .always())))
                    .financialFigures()
                    .foregroundStyle(points >= 0 ? StockMonitorChartPalette.positive : StockMonitorChartPalette.negative)
            }
            ChangeLabel(value: index.changePercent)
        }
        .gridColumnAlignment(.trailing)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(index.name) 涨跌 \(index.changePercent.map { String(format: "%.2f", $0) } ?? "数据不足") %")
    }
}

// MARK: - 总览首屏四状态（R4.0 纯逻辑）

struct OverviewBreadthMover: Equatable, Sendable {
    let ticker: String
    let changePercent: Double
}

struct OverviewBreadth: Equatable, Sendable {
    var advancing = 0
    var declining = 0
    var unchanged = 0
    var unavailable = 0
    var biggestGainer: OverviewBreadthMover?
    var biggestLoser: OverviewBreadthMover?

    var scanned: Int {
        advancing + declining + unchanged + unavailable
    }
}

enum OverviewSummarizer {
    /// 行情优先级与总览表格一致：实时报价优先，回落到快照价格。
    static func changePercent(stock: DashboardStock, live: RealtimeQuote?) -> Double? {
        if let live, let price = live.price, price.isFinite,
           let close = live.previousClose, close.isFinite, close != 0
        {
            return (price / close - 1) * 100
        }
        return stock.changePercent
    }

    static func breadth(stocks: [DashboardStock], liveQuotes: [String: RealtimeQuote]) -> OverviewBreadth {
        var result = OverviewBreadth()
        for stock in stocks {
            guard let change = changePercent(stock: stock, live: liveQuotes[stock.ticker]) else {
                result.unavailable += 1
                continue
            }
            switch change {
            case ..<0: result.declining += 1
            case 0: result.unchanged += 1
            default: result.advancing += 1
            }
            if change > (result.biggestGainer?.changePercent ?? -.infinity) {
                result.biggestGainer = OverviewBreadthMover(ticker: stock.ticker, changePercent: change)
            }
            if change < (result.biggestLoser?.changePercent ?? .infinity) {
                result.biggestLoser = OverviewBreadthMover(ticker: stock.ticker, changePercent: change)
            }
        }
        return result
    }
}

/// 首屏四类核心状态：市场、组合、自选、异动；不滚动即可读取。
struct OverviewCoreStateStrip: View {
    let marketOpen: Bool
    let marketSession: String?
    let portfolioReturnPercent: Double?
    let portfolioConfigured: Bool
    let breadth: OverviewBreadth
    let alertCount: Int
    let latestAlertDescription: String?

    var body: some View {
        MetricGrid([
            .init(
                id: "overview.market",
                label: "市场状态",
                value: FinancialDisplayValue(text: marketOpen ? "交易中" : "休市", qualifier: marketSessionLabel),
                status: marketOpen ? .live : .neutral
            ),
            .init(
                id: "overview.portfolio",
                label: "组合回报",
                value: portfolioReturnPercent.map {
                    FinancialValueFormatter.percent($0 / 100, precision: 2)
                } ?? FinancialDisplayValue(text: portfolioConfigured ? "—" : "未配置", qualifier: portfolioConfigured ? "数据不足" : "尚未设置基准"),
                status: (portfolioReturnPercent ?? 0) >= 0 ? .positive : .negative
            ),
            .init(
                id: "overview.watchlist",
                label: "自选涨跌",
                value: FinancialDisplayValue(
                    text: "\(breadth.advancing)↑ \(breadth.declining)↓",
                    qualifier: breadth.unavailable > 0 ? "另有 \(breadth.unavailable) 只缺报价" : "共 \(breadth.scanned) 只"
                ),
                status: breadth.unavailable > 0 ? .warning : .neutral
            ),
            .init(
                id: "overview.alerts",
                label: "最新异动",
                value: FinancialDisplayValue(text: alertCount > 0 ? "\(alertCount) 条" : "无", qualifier: latestAlertDescription),
                status: alertCount > 0 ? .warning : .live
            ),
        ])
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("r4.overview.core-states")
    }

    private var marketSessionLabel: String? {
        guard let marketSession, !marketSession.isEmpty else { return nil }
        return marketSession
    }
}

// MARK: - 异动分组（R4.0 纯逻辑）

/// 当日代表异动按周期与幅度分桶；目标价触发单独归类，不与波动混排。
struct AlertSeverityBuckets: Equatable, Sendable {
    var notableDayMoves: [MovementAlert] = []
    var intradayMoves: [MovementAlert] = []
    var briefMoves: [MovementAlert] = []
    var priceTargets: [MovementAlert] = []
    var unclassified: [MovementAlert] = []

    var isEmpty: Bool {
        notableDayMoves.isEmpty && intradayMoves.isEmpty && briefMoves.isEmpty && priceTargets.isEmpty && unclassified.isEmpty
    }
}

enum AlertGrouper {
    /// `day` 周期且幅度 ≥ 该值视为显著当日异动，置顶展示。
    static let notableDayMovePercent: Double = 5

    static func buckets(_ alerts: [MovementAlert]) -> AlertSeverityBuckets {
        var result = AlertSeverityBuckets()
        for alert in alerts.sorted(by: { $0.triggeredAt > $1.triggeredAt }) {
            switch alert.period {
            case "day":
                if abs(alert.changePercent) >= notableDayMovePercent {
                    result.notableDayMoves.append(alert)
                } else {
                    result.intradayMoves.append(alert)
                }
            case "1h":
                result.intradayMoves.append(alert)
            case "20m":
                result.briefMoves.append(alert)
            case "price_target":
                result.priceTargets.append(alert)
            default:
                result.unclassified.append(alert)
            }
        }
        return result
    }

    static func periodTitle(_ period: String) -> String {
        switch period {
        case "20m": "20 分钟"
        case "1h": "1 小时"
        case "day": "当日"
        case "price_target": "目标价"
        default: period
        }
    }

    /// 调查状态中文映射；同 ticker 多条调查时取最新一条。
    static func investigationLookup(_ investigations: [InvestigationItem]) -> [String: (status: String, label: String)] {
        var latest: [String: InvestigationItem] = [:]
        for item in investigations where latest[item.ticker]?.startedAt ?? "" < item.startedAt {
            latest[item.ticker] = item
        }
        return latest.mapValues { item in
            (item.status, statusLabel(item.status))
        }
    }

    static func statusLabel(_ status: String) -> String {
        switch status {
        case "active": "调查中"
        case "reporting": "报告生成中"
        case "completed": "调查完成"
        case "failed": "调查失败"
        default: status
        }
    }

    static func statusSemantic(_ status: String) -> SemanticStatusLabel.Status {
        switch status {
        case "active", "reporting": .info
        case "completed": .live
        case "failed": .danger
        default: .unavailable
        }
    }
}

/// 单条异动行：首行说明"发生了什么"，附周期、幅度与调查状态。
struct AlertSummaryRow: View {
    let alert: MovementAlert
    let investigationLabel: String?
    let investigationSemantic: SemanticStatusLabel.Status
    let openStock: (String) -> Void

    var body: some View {
        Button {
            openStock(alert.ticker)
        } label: {
            HStack(alignment: .firstTextBaseline, spacing: StockMonitorSpacing.regular) {
                VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                    HStack(spacing: StockMonitorSpacing.small) {
                        Text(alert.ticker).fontWeight(.semibold)
                        Text(AlertGrouper.periodTitle(alert.period)).stockMonitorTypography(.metadata)
                        Text(relativeTriggeredText).stockMonitorTypography(.metadata)
                    }
                    HStack(spacing: StockMonitorSpacing.small) {
                        Text(headlineText).stockMonitorTypography(.body)
                        if let investigationLabel {
                            SemanticStatusLabel(investigationLabel, status: investigationSemantic)
                        }
                    }
                }
                Spacer(minLength: StockMonitorSpacing.regular)
                ChangeLabel(value: alert.changePercent)
            }
            .buttonStyle(.plain)
            .padding(.vertical, StockMonitorSpacing.small)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(alert.ticker) \(headlineText)，\(investigationLabel ?? "无调查任务")")
    }

    /// "发生了什么"：方向 + 周期 + 幅度一句话。
    private var headlineText: String {
        let direction = alert.changePercent > 0 ? "上涨" : alert.changePercent < 0 ? "下跌" : "走平"
        return "\(direction) \(abs(alert.changePercent).formatted(.number.precision(.fractionLength(2))))%"
    }

    private var relativeTriggeredText: String {
        String(alert.triggeredAt.prefix(16).replacingOccurrences(of: "T", with: " "))
    }
}

// MARK: - 日历议程（R4.1 纯逻辑）

struct CalendarAgendaDay: Equatable, Sendable, Identifiable {
    let id: String
    let date: String
    let events: [CalendarEvent]
}

struct CalendarEventTypeSemantic: Equatable, Sendable {
    let symbol: String
    let title: String
}

enum CalendarAgendaBuilder {
    static func days(_ events: [CalendarEvent]) -> [CalendarAgendaDay] {
        let grouped = Dictionary(grouping: events, by: \.eventDate)
        return grouped
            .map { key, events in
                CalendarAgendaDay(
                    id: key,
                    date: key,
                    events: events.sorted { ($0.eventTime ?? "") < ($1.eventTime ?? "") }
                )
            }
            .sorted { $0.date < $1.date }
    }

    /// 事件类型同时提供符号与文字；颜色不承担唯一语义。
    static func typeSemantic(_ eventType: String) -> CalendarEventTypeSemantic {
        switch eventType {
        case "earnings": CalendarEventTypeSemantic(symbol: "doc.text.fill", title: "财报")
        case "dividend_ex_date": CalendarEventTypeSemantic(symbol: "banknote", title: "除息日")
        case "dividend_payment_date": CalendarEventTypeSemantic(symbol: "banknote.fill", title: "股息支付")
        case "stock_split": CalendarEventTypeSemantic(symbol: "arrow.triangle.2.circlepath", title: "拆股")
        case "reverse_split": CalendarEventTypeSemantic(symbol: "arrow.triangle.2.circlepath.circle", title: "反向拆股")
        default: CalendarEventTypeSemantic(symbol: "calendar", title: eventType)
        }
    }

    static func impactSemantic(_ level: String) -> SemanticStatusLabel.Status {
        switch level {
        case "critical", "high": .warning
        case "medium": .info
        default: .neutral
        }
    }

    static func impactTitle(_ level: String) -> String {
        switch level {
        case "critical": "影响：关键"
        case "high": "影响：高"
        case "medium": "影响：中"
        default: "影响：低"
        }
    }

    static func confidenceText(_ event: CalendarEvent) -> String? {
        if event.isConfirmed {
            return "已确认"
        }
        if event.isEstimated {
            return "预估"
        }
        return nil
    }
}

struct CalendarAgendaRow: View {
    let event: CalendarEvent
    let openStock: (String) -> Void

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: StockMonitorSpacing.regular) {
            Image(systemName: CalendarAgendaBuilder.typeSemantic(event.eventType).symbol)
                .foregroundStyle(.tint)
                .frame(width: 20)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                HStack(spacing: StockMonitorSpacing.small) {
                    Text(CalendarAgendaBuilder.typeSemantic(event.eventType).title)
                        .fontWeight(.medium)
                    if let symbol = event.symbol {
                        Button(symbol) { openStock(symbol) }
                            .buttonStyle(.plain)
                            .fontWeight(.semibold)
                    } else {
                        Text(event.companyName ?? "市场").stockMonitorTypography(.metadata)
                    }
                    if let confidence = CalendarAgendaBuilder.confidenceText(event) {
                        Text(confidence).stockMonitorTypography(.metadata)
                    }
                }
                Text(event.title).stockMonitorTypography(.body).lineLimit(2)
                HStack(spacing: StockMonitorSpacing.regular) {
                    if let time = event.eventTime, !time.isEmpty {
                        Text("时间 \(time)").stockMonitorTypography(.metadata)
                    }
                    Text("来源 \(event.primarySource)").stockMonitorTypography(.metadata)
                    if event.portfolioRelevance {
                        Text("组合相关").stockMonitorTypography(.metadata)
                    }
                    if event.stale {
                        SemanticStatusLabel("旧缓存", status: .stale)
                    }
                }
            }
            Spacer(minLength: StockMonitorSpacing.regular)
            VStack(alignment: .trailing, spacing: StockMonitorSpacing.xSmall) {
                SemanticStatusLabel(
                    CalendarAgendaBuilder.impactTitle(event.impactLevel),
                    status: CalendarAgendaBuilder.impactSemantic(event.impactLevel)
                )
                if let description = event.warning ?? event.description, !description.isEmpty {
                    Text(description)
                        .stockMonitorTypography(.metadata)
                        .lineLimit(1)
                        .help(description)
                }
            }
        }
        .padding(.vertical, StockMonitorSpacing.small)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(CalendarAgendaBuilder.typeSemantic(event.eventType).title)，\(event.title)")
    }
}

// MARK: - 报告目录（R4.1 纯逻辑）

struct ReportOutlineEntry: Equatable, Sendable, Identifiable {
    let id: String
    let level: Int
    let title: String
}

enum ReportOutlineParser {
    /// 提取 1–3 级 markdown 标题作为目录；每行返回值为 nil 表示不是标题。
    static func entries(from markdown: String) -> [ReportOutlineEntry] {
        var results: [ReportOutlineEntry] = []
        for (index, line) in markdown.split(separator: "\n", omittingEmptySubsequences: false).enumerated() {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard trimmed.hasPrefix("#") else { continue }
            let hashes = trimmed.prefix { $0 == "#" }.count
            guard (1 ... 3).contains(hashes) else { continue }
            let title = trimmed.dropFirst(hashes).trimmingCharacters(in: .whitespaces)
            guard !title.isEmpty else { continue }
            results.append(ReportOutlineEntry(id: "heading-\(index)", level: hashes, title: title))
        }
        return results
    }
}

// MARK: - 基本面指标分组（R4.2 纯逻辑）

/// 基本面数值按服务端 label 约定格式化：百分比已乘 100，市值单位为百万。
func fundamentalsDisplayValue(_ metric: FundamentalsMetric) -> FinancialDisplayValue {
    guard let value = metric.value, value.isFinite else {
        return FinancialValueFormatter.missing(metric.source == nil ? .missing : .actual)
    }
    let text: String = if metric.label.hasSuffix("%") {
        value.formatted(.number.precision(.fractionLength(2)).sign(strategy: .always())) + "%"
    } else if metric.label == "市值(百万)" {
        value.formatted(.number.grouping(.automatic).precision(.fractionLength(0)))
    } else if ["P/E", "P/B", "P/S", "Beta"].contains(metric.label) {
        value.formatted(.number.precision(.fractionLength(2))) + (metric.label == "Beta" ? "" : "×")
    } else {
        value.formatted(.number.precision(.fractionLength(2)))
    }
    let qualifier: String? = switch metric.label {
    case "市值(百万)": "百万美元"
    default: nil
    }
    return FinancialDisplayValue(text: text, qualifier: qualifier)
}

enum FundamentalsMetricGroup: String, CaseIterable, Identifiable, Sendable {
    case valuation = "估值"
    case profitability = "盈利能力"
    case growth = "成长性"
    case efficiency = "资本效率"
    case risk = "风险特征"
    case other = "其他指标"

    var id: String {
        rawValue
    }

    /// 服务端 `_METRIC_KEYS` 的 label 集合是稳定契约；新增 label 落入"其他指标"。
    static func group(forLabel label: String) -> FundamentalsMetricGroup {
        switch label {
        case "P/E", "P/B", "P/S", "市值(百万)":
            .valuation
        case "毛利率 %", "净利率 %", "营业利润率 %":
            .profitability
        case "营收增速 YoY %", "EPS增速 YoY %":
            .growth
        case "ROE %", "ROA %":
            .efficiency
        case "Beta", "52周高", "52周低":
            .risk
        default:
            .other
        }
    }

    static func grouped(_ metrics: [FundamentalsMetric]) -> [(FundamentalsMetricGroup, [FundamentalsMetric])] {
        let dictionary = Dictionary(grouping: metrics) { group(forLabel: $0.label) }
        return allCases.compactMap { group in
            let values = dictionary[group] ?? []
            return values.isEmpty ? nil : (group, values)
        }
    }
}

// MARK: - 财报矩阵（R4.2 纯逻辑：指标为行、期间为列、冻结指标列 + 同比）

struct FinancialMatrixColumn: Equatable, Sendable, Identifiable {
    let id: String
    let title: String
    let subtitle: String?
}

struct FinancialMatrixCell: Equatable, Sendable {
    let value: Double?
    /// 与上年同期的同比（仅在能找到同 fiscalPeriod 上年行时计算）。
    let yoyPercent: Double?
}

struct FinancialMatrixRow: Equatable, Sendable, Identifiable {
    enum Kind: Equatable, Sendable {
        case amount
        case count
        case percent
    }

    let id: String
    let label: String
    let kind: Kind
    let cells: [FinancialMatrixCell]
}

struct FinancialMatrix: Equatable, Sendable {
    let columns: [FinancialMatrixColumn]
    let rows: [FinancialMatrixRow]
    let currency: String?

    var isEmpty: Bool {
        columns.isEmpty || rows.isEmpty
    }
}

/// 单行矩阵定义：指标名 + 取值 keyPath + 展示类型。
struct FinancialMatrixRowDefinition {
    let label: String
    let value: KeyPath<QuarterlyFinancialRow, Double?>
    let kind: FinancialMatrixRow.Kind
}

enum FinancialMatrixBuilder {
    static func build(quarters: [QuarterlyFinancialRow], limit: Int = 6) -> FinancialMatrix {
        let sorted = quarters.sorted { ($0.periodEnd ?? "") > ($1.periodEnd ?? "") }
        let latest = sorted.prefix(limit)
        let columns: [FinancialMatrixColumn] = latest.map { row in
            FinancialMatrixColumn(
                id: row.id,
                title: "\(row.fiscalYear.map(String.init) ?? "—") \(row.fiscalPeriod ?? "")",
                subtitle: row.periodEnd
            )
        }
        let definitions: [FinancialMatrixRowDefinition] = [
            .init(label: "营业收入", value: \.revenue, kind: .amount),
            .init(label: "EPS", value: \.eps, kind: .count),
            .init(label: "净利润", value: \.netIncome, kind: .amount),
            .init(label: "经营利润", value: \.operatingIncome, kind: .amount),
            .init(label: "毛利率", value: \.grossMargin, kind: .percent),
            .init(label: "净利率", value: \.netMargin, kind: .percent),
            .init(label: "经营现金流", value: \.operatingCashFlow, kind: .amount),
            .init(label: "自由现金流", value: \.freeCashFlow, kind: .amount),
        ]
        let rows: [FinancialMatrixRow] = definitions.map { definition in
            FinancialMatrixRow(
                id: definition.label,
                label: definition.label,
                kind: definition.kind,
                cells: latest.map { row in
                    FinancialMatrixCell(
                        value: row[keyPath: definition.value],
                        yoyPercent: yoyPercent(row: row, quarters: quarters, value: definition.value)
                    )
                }
            )
        }
        return FinancialMatrix(
            columns: columns,
            rows: rows,
            currency: latest.first?.currency
        )
    }

    /// 同比只在"同 fiscalPeriod 的上一个财年"存在且两侧都有值时给出。
    static func yoyPercent(
        row: QuarterlyFinancialRow,
        quarters: [QuarterlyFinancialRow],
        value: KeyPath<QuarterlyFinancialRow, Double?>
    ) -> Double? {
        guard let period = row.fiscalPeriod, let year = row.fiscalYear,
              let current = row[keyPath: value],
              let prior = quarters.first(where: { $0.fiscalPeriod == period && $0.fiscalYear == year - 1 })?[keyPath: value],
              prior != 0
        else { return nil }
        return (current / prior - 1) * 100
    }
}

/// 行列层级 + 冻结指标列 + 右对齐 tabular 数字 + 同比辅助。
struct FinancialMatrixTable: View {
    @Environment(\.interfaceDensity) private var density
    let matrix: FinancialMatrix

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            metricColumn
            ScrollView(.horizontal) {
                Grid(alignment: .topLeading, horizontalSpacing: StockMonitorSpacing.medium, verticalSpacing: 0) {
                    GridRow {
                        ForEach(matrix.columns) { column in
                            VStack(alignment: .trailing, spacing: 1) {
                                Text(column.title).stockMonitorTypography(.metricLabel)
                                if let subtitle = column.subtitle {
                                    Text(subtitle).stockMonitorTypography(.microAnnotation)
                                }
                            }
                            .padding(.vertical, density.rowPadding)
                        }
                    }
                    ForEach(matrix.rows) { row in
                        GridRow {
                            ForEach(row.cells.indices, id: \.self) { index in
                                matrixCell(row, cell: row.cells[index])
                            }
                        }
                        Divider()
                    }
                }
                .padding(.leading, StockMonitorSpacing.small)
            }
        }
        .overlay(alignment: .top) { Divider() }
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("r4.financials.matrix")
    }

    private var metricColumn: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: StockMonitorSpacing.small) {
                Text("指标").stockMonitorTypography(.metricLabel)
                if let currency = matrix.currency, !currency.isEmpty {
                    Text("(\(currency))").stockMonitorTypography(.microAnnotation)
                }
                Spacer(minLength: StockMonitorSpacing.small)
            }
            .padding(.vertical, density.rowPadding)
            ForEach(matrix.rows) { row in
                HStack {
                    Text(row.label).stockMonitorTypography(.body)
                    Spacer(minLength: StockMonitorSpacing.regular)
                }
                .padding(.vertical, density.rowPadding)
                Divider()
            }
        }
        .frame(width: 150, alignment: .leading)
    }

    private func matrixCell(_ row: FinancialMatrixRow, cell: FinancialMatrixCell) -> some View {
        VStack(alignment: .trailing, spacing: 1) {
            if let value = cell.value, value.isFinite {
                Text(format(value, kind: row.kind)).financialFigures()
            } else {
                Text(FinancialValueFormatter.unavailable).foregroundStyle(.secondary)
            }
            if let yoy = cell.yoyPercent, yoy.isFinite {
                Text("同比 \(yoy.formatted(.number.precision(.fractionLength(1)).sign(strategy: .always())))%")
                    .stockMonitorTypography(.microAnnotation)
                    .foregroundStyle(yoy >= 0 ? StockMonitorChartPalette.positive : StockMonitorChartPalette.negative)
            }
        }
        .padding(.vertical, density.rowPadding)
        .frame(minWidth: 96, alignment: .trailing)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(row.label) \(cell.value.map { format($0, kind: row.kind) } ?? "数据不足")"
                + (cell.yoyPercent.map { "，同比 \($0.formatted(.number.precision(.fractionLength(1))))%" } ?? "")
        )
    }

    private func format(_ value: Double, kind: FinancialMatrixRow.Kind) -> String {
        switch kind {
        case .amount:
            magnitudeText(value)
        case .count:
            value.formatted(.number.precision(.fractionLength(2)))
        case .percent:
            value.formatted(.number.precision(.fractionLength(1))) + "%"
        }
    }

    private func magnitudeText(_ value: Double) -> String {
        let magnitude = abs(value)
        switch magnitude {
        case 1_000_000_000...:
            return (value / 1_000_000_000).formatted(.number.precision(.fractionLength(2))) + "B"
        case 1_000_000...:
            return (value / 1_000_000).formatted(.number.precision(.fractionLength(1))) + "M"
        case 1000...:
            return (value / 1000).formatted(.number.precision(.fractionLength(1))) + "K"
        default:
            return value.formatted(.number.precision(.fractionLength(2)))
        }
    }
}

// MARK: - 统一公司头（R4.2）

public struct CompanyHeaderSummary: Equatable, Sendable {
    public let symbol: String
    public let companyName: String?
    public let price: Double?
    public let changePercent: Double?
    public let marketOpen: Bool
    public let marketSession: String?
    public let priceSource: String?
    public let updatedAt: String?

    public init(
        symbol: String, companyName: String?, price: Double?, changePercent: Double?,
        marketOpen: Bool, marketSession: String?, priceSource: String?, updatedAt: String?
    ) {
        self.symbol = symbol
        self.companyName = companyName
        self.price = price
        self.changePercent = changePercent
        self.marketOpen = marketOpen
        self.marketSession = marketSession
        self.priceSource = priceSource
        self.updatedAt = updatedAt
    }
}

/// 公司分析组共享的一次性行情/市场上下文；研究端点受自选门控，
/// dashboard 快照必然覆盖当前代码。加载失败只降级公司头，不阻塞业务数据。
@MainActor
@Observable
public final class CompanySummaryModel {
    public private(set) var snapshot: DashboardSnapshot?
    public private(set) var failed = false
    private let service: ResearchWorkspaceService?
    private var loadTask: Task<Void, Never>?

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    /// 测试与视觉夹具注入已就绪快照；不再发起网络请求。
    public init(snapshot: DashboardSnapshot?) {
        service = nil
        self.snapshot = snapshot
    }

    public func loadIfNeeded() async {
        guard snapshot == nil, !failed, loadTask == nil, let service else { return }
        let task = Task { [weak self, service] in
            do {
                let value = try await service.dashboardSnapshot()
                self?.snapshot = value
            } catch {
                self?.failed = true
            }
            self?.loadTask = nil
        }
        loadTask = task
        await task.value
    }

    public func summary(for symbol: String) -> CompanyHeaderSummary? {
        guard let stock = snapshot?.stocks.first(where: { $0.ticker == symbol.uppercased() }) else {
            guard let market = snapshot?.market else { return nil }
            return CompanyHeaderSummary(
                symbol: symbol, companyName: nil, price: nil, changePercent: nil,
                marketOpen: market.isOpen, marketSession: market.session,
                priceSource: nil, updatedAt: nil
            )
        }
        let market = snapshot?.market
        return CompanyHeaderSummary(
            symbol: stock.ticker,
            companyName: stock.companyName,
            price: stock.price,
            changePercent: stock.changePercent,
            marketOpen: market?.isOpen ?? false,
            marketSession: market?.session,
            priceSource: stock.priceSource,
            updatedAt: stock.updatedAt
        )
    }
}

public struct CompanyHeaderView: View {
    let summary: CompanyHeaderSummary?

    public init(summary: CompanyHeaderSummary?) {
        self.summary = summary
    }

    public var body: some View {
        Group {
            if let summary {
                content(summary)
            } else {
                HStack {
                    Label("行情上下文不可用", systemImage: "chart.line.uptrend.xyaxis")
                        .stockMonitorTypography(.metadata)
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(StockMonitorSpacing.medium)
                .stockMonitorSurface(.grouped)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("r4.company.header")
    }

    private func content(_ summary: CompanyHeaderSummary) -> some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                    HStack(spacing: StockMonitorSpacing.small) {
                        Text(summary.symbol).font(.title3.weight(.semibold))
                        SemanticStatusLabel("自选", status: .info)
                        SemanticStatusLabel(
                            summary.marketOpen ? "交易中" : "休市",
                            status: summary.marketOpen ? .live : .neutral
                        )
                    }
                    if let companyName = summary.companyName, !companyName.isEmpty {
                        Text(companyName).stockMonitorTypography(.body)
                    }
                }
                Spacer(minLength: StockMonitorSpacing.regular)
                VStack(alignment: .trailing, spacing: StockMonitorSpacing.xSmall) {
                    Text(
                        summary.price.map { $0.formatted(.number.precision(.fractionLength(2))) }
                            ?? FinancialValueFormatter.unavailable
                    )
                    .font(.system(.title2, design: .rounded, weight: .semibold))
                    .financialFigures()
                    .foregroundStyle(summary.price == nil ? .secondary : .primary)
                    ChangeLabel(value: summary.changePercent)
                }
            }
            MetadataStrip(metadataItems(summary))
        }
        .padding(StockMonitorSpacing.medium)
        .stockMonitorSurface(.grouped)
    }

    private func metadataItems(_ summary: CompanyHeaderSummary) -> [MetadataItem] {
        var items: [MetadataItem] = []
        if let source = summary.priceSource, !source.isEmpty {
            items.append(MetadataItem(label: "行情来源", value: source))
        } else {
            items.append(MetadataItem(label: "行情来源", value: "数据不足"))
        }
        if let updatedAt = summary.updatedAt, !updatedAt.isEmpty {
            items.append(MetadataItem(label: "更新时间", value: String(updatedAt.prefix(19).replacingOccurrences(of: "T", with: " "))))
        }
        return items
    }
}
