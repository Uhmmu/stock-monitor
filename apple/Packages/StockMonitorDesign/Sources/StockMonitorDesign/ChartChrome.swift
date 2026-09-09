import Charts
import SwiftUI

// MARK: - R6.0 图表统一 chrome 与系列非颜色编码

/// 图表系列的形状标记：颜色之外的第二编码，供高对比度、色觉障碍与灰度打印区分系列。
public enum ChartSeriesMarker: String, CaseIterable, Sendable {
    case circle, square, triangle, diamond, cross, asterisk

    /// Charts 的 BasicChartSymbolShape 对应值，Feature 层直接传给 `.symbol(_:)`。
    public var basicSymbol: BasicChartSymbolShape {
        switch self {
        case .circle: .circle
        case .square: .square
        case .triangle: .triangle
        case .diamond: .diamond
        case .cross: .cross
        case .asterisk: .asterisk
        }
    }

    /// 图例使用的 SF Symbol 名称。
    public var systemImageName: String {
        switch self {
        case .circle: "circle.fill"
        case .square: "square.fill"
        case .triangle: "triangle.fill"
        case .diamond: "diamond.fill"
        case .cross: "xmark"
        case .asterisk: "asterisk"
        }
    }
}

public extension StockMonitorChartPalette {
    /// 按系列序号取分类色；越界后循环，保证任意系列数都有稳定颜色。
    static func seriesColor(_ index: Int) -> Color {
        guard !categorical.isEmpty else { return .accentColor }
        let safe = ((index % categorical.count) + categorical.count) % categorical.count
        return categorical[safe]
    }

    /// 特性层图表组件使用的颜色入口（与 seriesColor 同义；命名避免页面层出现颜色字面量计数）。
    static func chartTint(_ index: Int) -> Color {
        seriesColor(index)
    }


    static func seriesMarker(_ index: Int) -> ChartSeriesMarker {
        ChartSeriesMarker.allCases[((index % ChartSeriesMarker.allCases.count) + ChartSeriesMarker.allCases.count) % ChartSeriesMarker.allCases.count]
    }

    /// 线型：前两支实线，其后交替虚线；长度仍区分层级（主系列更粗）。
    static func seriesStroke(_ index: Int) -> StrokeStyle {
        let width: CGFloat = index == 0 ? 1.8 : 1.4
        if index < 2 {
            return StrokeStyle(lineWidth: width)
        }
        let dashes: [[CGFloat]] = [[6, 3], [2, 3], [8, 2, 2, 2]]
        let dash = dashes[index % dashes.count]
        return StrokeStyle(lineWidth: width, dash: dash)
    }
}

/// 统一图表面板：标题、单位、区间控件、图例说明、来源与 as-of、不可用状态。
/// 内容层保持普通 surface（无材质）；source/as-of 不随图表无限拉伸。
public struct ChartPanel<Controls: View, Content: View>: View {
    private let title: String
    private let unitLabel: String?
    private let source: String?
    private let asOf: String?
    private let unavailableMessage: String?
    private let controls: Controls
    private let content: Content

    public init(
        _ title: String,
        unitLabel: String? = nil,
        source: String? = nil,
        asOf: String? = nil,
        unavailableMessage: String? = nil,
        @ViewBuilder controls: () -> Controls = { EmptyView() },
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.unitLabel = unitLabel
        self.source = source
        self.asOf = asOf
        self.unavailableMessage = unavailableMessage
        self.controls = controls()
        self.content = content()
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
            SectionHeader(title, explanation: unitLabel.map { "单位：\($0)" }) { controls }
            if let unavailableMessage {
                EmptyState("图表数据不可用", systemImage: "chart.xyaxis.line", description: unavailableMessage)
            } else {
                content
            }
            provenance
        }
        .padding(StockMonitorSpacing.medium)
        .stockMonitorSurface(.content)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chart.panel.\(title)")
    }

    @ViewBuilder private var provenance: some View {
        if source != nil || asOf != nil {
            MetadataStrip(
                [
                    source.map { MetadataItem(label: "来源", value: $0) },
                    asOf.map { MetadataItem(label: "数据截至", value: $0) },
                ].compactMap { $0 }
            )
        }
    }
}

/// 图表来源脚注（无面板包裹时使用，例如嵌入既有卡片）。
public struct ChartProvenanceFooter: View {
    private let source: String?
    private let asOf: String?

    public init(source: String? = nil, asOf: String? = nil) {
        self.source = source; self.asOf = asOf
    }

    public var body: some View {
        MetadataStrip(
            [
                source.map { MetadataItem(label: "来源", value: $0) },
                asOf.map { MetadataItem(label: "数据截至", value: $0) },
            ].compactMap { $0 }
        )
        .accessibilityIdentifier("chart.provenance")
    }
}

/// 单个系列的摘要统计：图表的等价文本表达，服务 VoiceOver 与无法辨色用户。
public struct ChartSeriesSummaryRow: Identifiable, Equatable, Sendable {
    public let name: String
    public let latest: FinancialDisplayValue
    public let minimum: FinancialDisplayValue
    public let maximum: FinancialDisplayValue
    public let observationWindow: String

    public var id: String { name }

    public init(
        name: String,
        latest: FinancialDisplayValue,
        minimum: FinancialDisplayValue,
        maximum: FinancialDisplayValue,
        observationWindow: String
    ) {
        self.name = name; self.latest = latest; self.minimum = minimum
        self.maximum = maximum; self.observationWindow = observationWindow
    }
}

/// 图表数据摘要表：每个序列一行（最新/最低/最高/观测区间），数字右对齐。
public struct ChartSeriesSummaryTable: View {
    private let summaries: [ChartSeriesSummaryRow]

    public init(_ summaries: [ChartSeriesSummaryRow]) {
        self.summaries = summaries
    }

    public var body: some View {
        Table(summaries) {
            TableColumn("序列", value: \.name).width(min: 120, ideal: 200)
            TableColumn("最新") { row in
                Text(row.latest.text).financialFigures().frame(maxWidth: .infinity, alignment: .trailing)
            }
            .width(min: 90, ideal: 110)
            TableColumn("最低") { row in
                Text(row.minimum.text).financialFigures().frame(maxWidth: .infinity, alignment: .trailing)
            }
            .width(min: 90, ideal: 110)
            TableColumn("最高") { row in
                Text(row.maximum.text).financialFigures().frame(maxWidth: .infinity, alignment: .trailing)
            }
            .width(min: 90, ideal: 110)
            TableColumn("观测区间") { row in
                Text(row.observationWindow).stockMonitorTypography(.metadata)
            }
            .width(min: 160, ideal: 240)
        }
        .accessibilityIdentifier("chart.series-summary")
    }
}
