import Charts
import StockMonitorDesign
import SwiftUI

// MARK: - R6 快照 fixture：图表 chrome、排序表格与 before/after 对照

/// 图表 golden fixture：多序列折线 + 参考线 + 收益率曲线 + 不可用态，
/// 覆盖 palette/形状双编码、tooltip 容器、图例、数据摘要表与 source/as-of chrome。
public struct R6ChartsFixture: View {
    public init() {}

    /// before/after 共用同一数据源，保证对比同数据。
    public static let fixtureSeries: [LineSeries] = {
        let base = Date(timeIntervalSince1970: 1_750_000_000)
        func points(_ transform: (Int) -> Double) -> [TimedPoint] {
            (0 ..< 90).map { index in
                TimedPoint(
                    date: base.addingTimeInterval(Double(index) * 86_400 * 7),
                    value: transform(index)
                )
            }
        }
        return [
            LineSeries(name: "AAPL", paletteIndex: 0, points: points { 100 + Double($0) * 0.42 }),
            LineSeries(name: "MSFT", paletteIndex: 1, points: points { 98 + Double($0) * 0.36 }),
            LineSeries(name: "NVDA", paletteIndex: 2, points: points { 102 + Double($0) * 0.51 }),
        ]
    }()

    public var seriesForBefore: [LineSeries] {
        Self.fixtureSeries
    }

    private let curves: [YieldCurveSnapshot] = [
        YieldCurveSnapshot(
            label: "最新",
            observationDate: "2026-09-08",
            points: [
                YieldCurvePoint(maturity: "3M", value: 3.82),
                YieldCurvePoint(maturity: "2Y", value: 3.54),
                YieldCurvePoint(maturity: "5Y", value: 3.61),
                YieldCurvePoint(maturity: "10Y", value: 3.94),
                YieldCurvePoint(maturity: "30Y", value: 4.31),
            ]
        ),
        YieldCurveSnapshot(
            label: "前一观察日",
            observationDate: "2026-09-05",
            points: [
                YieldCurvePoint(maturity: "3M", value: 3.79),
                YieldCurvePoint(maturity: "2Y", value: 3.49),
                YieldCurvePoint(maturity: "5Y", value: 3.58),
                YieldCurvePoint(maturity: "10Y", value: 3.90),
                YieldCurvePoint(maturity: "30Y", value: 4.28),
            ]
        ),
    ]

    public var body: some View {
        PageScaffold(width: StockMonitorContentWidth.standard) {
            PageHeader("图表统一 chrome", eyebrow: "R6.0", summary: "palette 双编码、tooltip、图例、数据摘要与来源/as-of 一致呈现。") {
                SourceBadge("FMP/Yahoo")
                FreshnessBadge("2026-09-08", stale: false)
            }
        } content: {
            ChartPanel(
                "指数化对比（首日=100）",
                unitLabel: "首日=100",
                source: "已持久化 FMP/Yahoo/估值快照",
                asOf: "2026-09-08"
            ) {
                LineSeriesChart(
                    series: Self.fixtureSeries,
                    unitLabel: "（首日=100）",
                    referenceLines: [("中位", 118.4)]
                )
                .frame(height: 240)
            }
            ChartPanel(
                "期限结构",
                unitLabel: "%",
                source: "Alpha Vantage 日同步",
                asOf: "2026-09-08"
            ) {
                YieldCurveChart(curves: curves)
            }
            ChartPanel("历史 P/E", unitLabel: "倍", unavailableMessage: "EPS 事实尚未采集，已排队同步；稍后重试。") {
                EmptyView()
            }
        }
    }
}

/// 表格 golden fixture：可排序列、右对齐 tabular 数字、主列身份、截断脚注与 alternating rows。
public struct R6TablesFixture: View {
    public init() {}

    private struct HoldingRow: Identifiable {
        let id = UUID()
        let manager: String
        let shares: Double
        let valueUsd: Double
        let change: Double?
        let filingDate: String
    }

    @State private var sortOrder = [KeyPathComparator(\HoldingRow.valueUsd, order: .reverse)]

    private let rows: [HoldingRow] = [
        .init(manager: "Vanguard Group Inc", shares: 1_523_400_000, valueUsd: 352_100_000_000, change: 4_120_000, filingDate: "2026-08-14"),
        .init(manager: "BlackRock Fund Advisors", shares: 934_800_000, valueUsd: 215_900_000_000, change: -2_310_000, filingDate: "2026-08-14"),
        .init(manager: "Fidelity Management & Research Company", shares: 421_600_000, valueUsd: 97_400_000_000, change: nil, filingDate: "2026-08-14"),
        .init(manager: "State Street Global Advisors（非常长的机构名称用于截断验证）", shares: 388_100_000, valueUsd: 89_600_000_000, change: 890_000, filingDate: "2026-08-12"),
        .init(manager: "Geode Capital Management LLC", shares: 296_700_000, valueUsd: 68_500_000_000, change: 1_240_000, filingDate: "2026-08-12"),
    ]

    public var body: some View {
        PageScaffold(width: StockMonitorContentWidth.standard) {
            PageHeader("13F 机构持仓", eyebrow: "R6.0", summary: "主列承载机构身份，数值右对齐 + tabular figures，环比用符号+文字。") {
                FreshnessBadge("报告期 2026-06-30", stale: true)
            }
        } content: {
            SectionHeader("机构持仓", explanation: "13F 季度快照，滞后约 45 天；默认按市值降序，点击列头重排。")
            Table(rows, sortOrder: $sortOrder) {
                TableColumn("机构", sortUsing: KeyPathComparator(\HoldingRow.manager)) { row in
                    MainTableCell(row.manager)
                }
                .width(min: 200, ideal: 300)
                TableColumn("股数", sortUsing: KeyPathComparator(\HoldingRow.shares, order: .reverse)) { row in
                    NumericTableCell(value: row.shares, digits: 0)
                }
                .width(min: 90, ideal: 110)
                TableColumn("市值 USD", sortUsing: KeyPathComparator(\HoldingRow.valueUsd, order: .reverse)) { row in
                    NumericTableCell(value: row.valueUsd, digits: 1, compact: true)
                }
                .width(min: 100, ideal: 120)
                TableColumn("环比", sortUsing: KeyPathComparator(\HoldingRow.change, order: .reverse)) { row in
                    if let change = row.change {
                        HStack(spacing: StockMonitorSpacing.xSmall) {
                            Image(systemName: change >= 0 ? "arrow.up" : "arrow.down")
                                .font(.caption.weight(.bold))
                                .accessibilityHidden(true)
                            Text((change >= 0 ? "+" : "") + change.formatted(.number.precision(.fractionLength(0))))
                                .financialFigures()
                        }
                        .foregroundStyle(change >= 0 ? StockMonitorChartPalette.positive : StockMonitorChartPalette.negative)
                        .frame(maxWidth: .infinity, alignment: .trailing)
                    } else {
                        Text("数据不足").foregroundStyle(.secondary)
                    }
                }
                .width(min: 90, ideal: 110)
                TableColumn("申报日") { row in
                    Text(row.filingDate)
                }
                .width(min: 90, ideal: 110)
            }
            .alternatingRowBackgrounds(.enabled)
            .frame(minHeight: 220)
            .accessibilityIdentifier("r6.fixture.13f-table")
            TableTruncationFooter(shown: 5, total: 1_204)
        }
    }
}

/// Before fixture：R6 之前的裸图表形态（无统一 chrome、单一颜色、无摘要）。
public struct R6ChartBeforeFixture: View {
    public init() {}

    public var body: some View {
        PageScaffold(width: StockMonitorContentWidth.standard) {
            PageHeader("图表（改造前）", eyebrow: "R6.0 before", summary: "裸 Chart：无单位/来源/as-of、颜色单编码、无 tooltip、无等价数据表。")
        } content: {
            BeforeBareChart()
                .frame(height: 240)
                .padding(StockMonitorSpacing.medium)
                .stockMonitorSurface(.content)
        }
    }
}

/// 与 LineSeriesChart 相同数据源的裸形态，用于 before/after 同数据对比。
struct BeforeBareChart: View {
    var body: some View {
        Chart {
            ForEach(R6ChartsFixture().seriesForBefore) { line in
                ForEach(line.points) { point in
                    LineMark(
                        x: .value("日期", point.date, unit: .day),
                        y: .value("数值", point.value)
                    )
                    .foregroundStyle(by: .value("序列", line.name))
                    .lineStyle(StrokeStyle(lineWidth: 1.8))
                    .interpolationMethod(.monotone)
                }
            }
        }
    }
}
