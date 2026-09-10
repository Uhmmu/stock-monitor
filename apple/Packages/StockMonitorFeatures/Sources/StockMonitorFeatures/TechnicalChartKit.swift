import Charts
import StockMonitorDesign
import SwiftUI

// MARK: - 时间解析（服务端序列使用 ISO 日期或日期时间字符串）

public enum ChartTime {
    public static func parse(_ raw: String) -> Date? {
        let dateTime = ISO8601DateFormatter()
        dateTime.formatOptions = [.withInternetDateTime]
        if let value = dateTime.date(from: raw) {
            return value
        }
        let dateOnly = ISO8601DateFormatter()
        dateOnly.formatOptions = [.withFullDate]
        return dateOnly.date(from: raw)
    }

    public static func day(_ raw: String) -> Date? {
        parse(String(raw.prefix(10)))
    }

    /// R6.0：图表 as-of 统一格式（UTC 日粒度）。
    public static func formatDay(_ date: Date) -> String {
        dayFormatter.string(from: date)
    }

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .iso8601)
        formatter.timeZone = TimeZone(identifier: "UTC")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()
}

/// 图表使用日历日本身作为 X 轴；把所有蜡烛时间归一到 UTC 零点，避免时区偏移引起的空档。
public enum ChartDomain {
    public static func normalize(_ date: Date) -> Date {
        Calendar(identifier: .iso8601).startOfDay(for: date)
    }
}

public struct TimedCandle: Equatable, Sendable, Identifiable {
    public let date: Date
    public let candle: ChartCandle

    public var id: Date {
        date
    }
}

public struct TimedPoint: Equatable, Sendable, Identifiable {
    public let date: Date
    public let value: Double

    public var id: Date {
        date
    }
}

/// 离开主线程的数据准备与派生图层计算。
public enum CandlePreparation {
    public static func timedCandles(from candles: [ChartCandle]) -> [TimedCandle] {
        candles.compactMap { candle in
            guard let date = ChartTime.day(candle.time) else { return nil }
            return TimedCandle(date: ChartDomain.normalize(date), candle: candle)
        }
        .sorted { $0.date < $1.date }
    }

    public static func timedPoints(from points: [MovingAveragePoint]) -> [TimedPoint] {
        points.compactMap { point in
            guard let date = ChartTime.day(point.time) else { return nil }
            return TimedPoint(date: ChartDomain.normalize(date), value: point.value)
        }
        .sorted { $0.date < $1.date }
    }

    /// 可视窗口的摆动高低点 → 展示用支撑/阻力参考线。仅做图形呈现，不构成服务端结论。
    public static func swingLevels(in candles: [TimedCandle], window: Int = 3) -> [Double] {
        guard candles.count > window * 2 else { return [] }
        var levels: [Double] = []
        for index in candles.indices where index >= window && index < candles.count - window {
            let slice = candles[(index - window) ... (index + window)]
            let high = slice.map(\.candle.high)
            let low = slice.map(\.candle.low)
            if candles[index].candle.high == high.max() {
                levels.append(candles[index].candle.high)
            }
            if candles[index].candle.low == low.min() {
                levels.append(candles[index].candle.low)
            }
        }
        return mergeLevels(levels)
    }

    private static func mergeLevels(_ levels: [Double], tolerance: Double = 0.01) -> [Double] {
        guard !levels.isEmpty else { return [] }
        let sorted = levels.sorted()
        var clustered: [Double] = [sorted[0]]
        var sums: [Double] = [sorted[0]]
        var counts = [1]
        for value in sorted.dropFirst() {
            let index = sums.count - 1
            let reference = sums[index] / Double(counts[index])
            if abs(value - reference) / max(abs(reference), .leastNormalMagnitude) <= tolerance {
                sums[index] += value
                counts[index] += 1
            } else {
                clustered.append(value)
                sums.append(value)
                counts.append(1)
            }
        }
        return zip(sums, counts).map { $0 / Double($1) }.sorted()
    }

    /// Fibonacci 回撤（0/23.6/38.2/50/61.8/78.6/100%），基于可视区间高低点。
    public static func fibonacciLevels(in candles: [TimedCandle]) -> [(ratio: Double, price: Double)] {
        guard let high = candles.map(\.candle.high).max(), let low = candles.map(\.candle.low).min(), high > low else {
            return []
        }
        return [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1].map { ratio in
            (ratio, high - (high - low) * ratio)
        }
    }

    /// 大窗口降采样：超出渲染预算时按步长抽样，始终保留首尾。
    public static func downsample(_ candles: [TimedCandle], budget: Int = 420) -> [TimedCandle] {
        guard candles.count > budget else { return candles }
        let stride = Double(candles.count) / Double(budget)
        var sampled: [TimedCandle] = []
        var next = 0.0
        while Int(next) < candles.count {
            sampled.append(candles[Int(next)])
            next += stride
        }
        if let last = candles.last, sampled.last != last {
            sampled.append(last)
        }
        return sampled
    }
}

// MARK: - 通用折线图（宏观、P/E、mood、IV、对比 indexed 共用）

public struct LineSeries: Identifiable, Equatable, Sendable {
    public let name: String
    public let color: Color
    public let points: [TimedPoint]

    public var id: String {
        name
    }

    /// R6.0：颜色由共享 palette 按系列序号分配，调用方不再各自硬编码。
    public init(name: String, paletteIndex: Int, points: [TimedPoint]) {
        self.name = name
        color = StockMonitorChartPalette.chartTint(paletteIndex)
        self.points = points
    }

    public init(name: String, color: Color, points: [TimedPoint]) {
        self.name = name
        self.color = color
        self.points = points
    }
}

/// 折线图序列的等价文本摘要（VoiceOver/色觉障碍用户与图表互为印证）。
public enum LineSeriesSummaryBuilder {
    public static func build(
        series: [LineSeries],
        digits: Int = 2,
        calendar: Calendar = Calendar(identifier: .iso8601)
    ) -> [ChartSeriesSummaryRow] {
        series.map { line in
            let values = line.points.map(\.value)
            let window: String
            if let first = line.points.first?.date, let last = line.points.last?.date {
                let formatter = DateFormatter()
                formatter.calendar = calendar
                formatter.dateFormat = "yyyy-MM-dd"
                window = "\(formatter.string(from: first)) 至 \(formatter.string(from: last))（\(line.points.count) 点）"
            } else {
                window = "无观测点"
            }
            func text(_ value: Double?) -> FinancialDisplayValue {
                value.map { FinancialDisplayValue(text: $0.formatted(.number.precision(.fractionLength(digits)))) }
                    ?? FinancialValueFormatter.missing(.notCollected)
            }
            return ChartSeriesSummaryRow(
                name: line.name,
                latest: text(values.last),
                minimum: text(values.min()),
                maximum: text(values.max()),
                observationWindow: window
            )
        }
    }
}

public struct LineSeriesChart: View {
    package let series: [LineSeries]
    public var unitLabel: String = ""
    public var referenceLines: [(label: String, value: Double)] = []
    /// R6.0：默认展示数据摘要表，图表必须能回答明确问题而非装饰页面。
    public var showsDataSummary = true
    @State private var hoverDate: Date?

    public init(series: [LineSeries], unitLabel: String = "", referenceLines: [(label: String, value: Double)] = []) {
        self.series = series
        self.unitLabel = unitLabel
        self.referenceLines = referenceLines
    }

    public init(
        series: [LineSeries],
        unitLabel: String = "",
        referenceLines: [(label: String, value: Double)] = [],
        showsDataSummary: Bool
    ) {
        self.series = series
        self.unitLabel = unitLabel
        self.referenceLines = referenceLines
        self.showsDataSummary = showsDataSummary
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
            chartBody
            seriesLegend
            if showsDataSummary {
                DisclosureGroup("图表数据摘要（非视觉访问）") {
                    ChartSeriesSummaryTable(LineSeriesSummaryBuilder.build(series: series))
                }
                .font(.headline)
                .accessibilityIdentifier("chart.line-series.summary-disclosure")
            }
        }
    }

    private var chartBody: some View {
        Chart {
            ForEach(Array(series.enumerated()), id: \.element.id) { index, line in
                ForEach(line.points) { point in
                    LineMark(
                        x: .value("日期", point.date, unit: .day),
                        y: .value("数值", point.value)
                    )
                    .foregroundStyle(line.color)
                    .lineStyle(StockMonitorChartPalette.seriesStroke(index))
                    .interpolationMethod(.monotone)
                    .symbol(StockMonitorChartPalette.seriesMarker(index).basicSymbol)
                    .symbolSize(index == 0 ? 36 : 24)
                    if hoverDate == point.date {
                        PointMark(
                            x: .value("日期", point.date, unit: .day),
                            y: .value("数值", point.value)
                        )
                        .foregroundStyle(line.color)
                        .symbolSize(90)
                    }
                }
            }
            ForEach(referenceLines, id: \.label) { reference in
                RuleMark(y: .value(reference.label, reference.value))
                    .foregroundStyle(.secondary.opacity(0.6))
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 4]))
                    .annotation(position: .topLeading) {
                        Text("\(reference.label) \(reference.value.formatted(.number.precision(.fractionLength(1))))")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading) { _ in
                AxisGridLine().foregroundStyle(.quaternary)
                AxisValueLabel().font(.system(.caption2, design: .monospaced))
            }
        }
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 6)) { _ in
                AxisGridLine().foregroundStyle(.quaternary)
                AxisValueLabel(format: .dateTime.year().month())
            }
        }
        .chartOverlay { proxy in
            GeometryReader { geometry in
                Rectangle().fill(.clear).contentShape(.rect)
                    .onContinuousHover { phase in
                        switch phase {
                        case let .active(location):
                            hoverDate = date(at: location, proxy: proxy, size: geometry.size)
                        case .ended:
                            hoverDate = nil
                        }
                    }
                    .overlay(alignment: .topLeading) {
                        if let hoverDate {
                            SeriesValueTooltip(
                                title: hoverDate.formatted(.dateTime.year().month().day()),
                                entries: series.map { line in
                                    let nearest = line.points.min {
                                        abs($0.date.timeIntervalSince(hoverDate)) < abs($1.date.timeIntervalSince(hoverDate))
                                    }
                                    return SeriesValueTooltip.Entry(
                                        name: line.name,
                                        color: line.color,
                                        value: nearest.map { $0.value.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足"
                                    )
                                },
                                footnote: unitLabel.isEmpty ? nil : "单位：\(unitLabel)"
                            )
                            .padding(6)
                        }
                    }
            }
        }
        .accessibilityLabel(chartAccessibilitySummary)
    }

    /// 图例 = 形状 + 颜色 + 名称，颜色不是唯一编码。
    private var seriesLegend: some View {
        HStack(spacing: StockMonitorSpacing.regular) {
            ForEach(Array(series.enumerated()), id: \.element.id) { index, line in
                HStack(spacing: StockMonitorSpacing.xSmall) {
                    Image(systemName: StockMonitorChartPalette.seriesMarker(index).systemImageName)
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(line.color)
                        .accessibilityHidden(true)
                    Text(line.name).stockMonitorTypography(.metadata)
                }
                .accessibilityElement(children: .combine)
            }
            if !unitLabel.isEmpty {
                Text(unitLabel).stockMonitorTypography(.microAnnotation)
            }
        }
        .accessibilityIdentifier("chart.line-series.legend")
    }

    private func date(at location: CGPoint, proxy: ChartProxy, size: CGSize) -> Date? {
        if let value = proxy.value(atX: location.x, as: Date.self) {
            return value
        }
        let fraction = max(0, min(1, location.x / max(size.width, 1)))
        guard let start = series.compactMap(\.points.first?.date).min(),
              let end = series.compactMap(\.points.last?.date).max(), end > start else { return nil }
        return start.addingTimeInterval(end.timeIntervalSince(start) * fraction)
    }

    private var chartAccessibilitySummary: String {
        let summaries = series.map { line in
            let values = line.points.map(\.value)
            let latest = values.last.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足"
            return "\(line.name) 最新 \(latest)\(unitLabel)"
        }
        return summaries.joined(separator: "，")
    }
}

/// 图表十字光标 tooltip：标题（日期或期限）+ 每个序列的颜色点、名称与值。
struct SeriesValueTooltip: View {
    struct Entry {
        let name: String
        let color: Color
        let value: String
    }

    let title: String
    let entries: [Entry]
    let footnote: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.caption2.bold())
            ForEach(Array(entries.enumerated()), id: \.offset) { _, entry in
                HStack(spacing: 6) {
                    Circle().fill(entry.color).frame(width: 6, height: 6)
                    Text(entry.name)
                    Spacer(minLength: 6)
                    Text(entry.value).monospacedDigit()
                }
            }
            if let footnote {
                Text(footnote).foregroundStyle(.secondary)
            }
        }
        .font(.caption2.monospacedDigit())
        .padding(8)
        .frame(minWidth: 130)
        .background(.regularMaterial, in: .rect(cornerRadius: 8))
        .accessibilityIdentifier("chart.series-tooltip")
    }
}

// MARK: - K 线主图

public struct CandleChartView: View {
    public let candles: [TimedCandle]
    public let movingAverages: [String: [TimedPoint]]
    public let events: [TechnicalChartEvent]
    public let portfolioCost: Double?
    public let alertPrices: [Double]
    @State private var visibleStart: Date?
    @State private var visibleEnd: Date?
    @State private var hoverCandle: TimedCandle?
    @State private var showMovingAverages = true
    @State private var showSwingLevels = false
    @State private var showFibonacci = false
    @State private var showEvents = true
    @State private var trendLines: [[TrendAnchor]] = []
    @State private var pendingAnchor: TrendAnchor?
    @State private var drawMode = false
    @State private var magnification: CGFloat = 1

    public struct TrendAnchor: Equatable, Sendable {
        public let date: Date
        package let price: Double
    }

    public init(
        candles: [TimedCandle], movingAverages: [String: [TimedPoint]] = [:],
        events: [TechnicalChartEvent] = [], portfolioCost: Double? = nil, alertPrices: [Double] = []
    ) {
        self.candles = candles
        self.movingAverages = movingAverages
        self.events = events
        self.portfolioCost = portfolioCost
        self.alertPrices = alertPrices
    }

    public var body: some View {
        let domain = visibleDomain
        let windowCandles = CandlePreparation.downsample(
            candles.filter { candle in
                (domain.lowerBound ... domain.upperBound).contains(candle.date)
            }
        )
        let swingLevels = showSwingLevels ? CandlePreparation.swingLevels(in: windowCandles) : []
        let fibonacci = showFibonacci ? CandlePreparation.fibonacciLevels(in: windowCandles) : []
        VStack(alignment: .leading, spacing: 10) {
            chartControls
            Chart {
                candleMarks(windowCandles)
                movingAverageMarks
                swingLevelMarks(swingLevels)
                fibonacciMarks(fibonacci)
                costMark
                alertMarks
                eventMarks
                trendLineMarks
            }
            .chartXScale(domain: domain)
            .chartXAxis {
                AxisMarks(values: .automatic(desiredCount: 6)) { _ in
                    AxisGridLine().foregroundStyle(.quaternary)
                    AxisValueLabel(format: .dateTime.year().month())
                }
            }
            .chartYAxis {
                AxisMarks(position: .leading) { _ in
                    AxisGridLine().foregroundStyle(.quaternary)
                    AxisValueLabel().font(.system(.caption2, design: .monospaced))
                }
            }
            .chartLegend(position: .topTrailing, spacing: 6)
            .frame(minHeight: 320)
            .chartOverlay { proxy in
                GeometryReader { geometry in
                    chartInteractionLayer(proxy: proxy, size: geometry.size)
                }
            }
            volumeChart(domain: domain, windowCandles: windowCandles)
        }
    }

    @ChartContentBuilder
    private func candleMarks(_ windowCandles: [TimedCandle]) -> some ChartContent {
        ForEach(windowCandles) { timed in
            RuleMark(
                x: .value("日期", timed.date, unit: .day),
                yStart: .value("最低", timed.candle.low),
                yEnd: .value("最高", timed.candle.high)
            )
            .foregroundStyle(timed.candle.close >= timed.candle.open ? Color.green : Color.red)
            .lineStyle(StrokeStyle(lineWidth: 1))
            RectangleMark(
                x: .value("日期", timed.date, unit: .day),
                yStart: .value("开盘", min(timed.candle.open, timed.candle.close)),
                yEnd: .value("收盘", max(timed.candle.open, timed.candle.close)),
                width: .ratio(0.62)
            )
            .foregroundStyle(timed.candle.close >= timed.candle.open ? Color.green : Color.red)
        }
    }

    @ChartContentBuilder
    private var movingAverageMarks: some ChartContent {
        if showMovingAverages {
            ForEach(Array(movingAverages.keys.sorted()), id: \.self) { key in
                ForEach(movingAverages[key] ?? []) { point in
                    LineMark(
                        x: .value("均线日期", point.date, unit: .day),
                        y: .value(key, point.value)
                    )
                    .foregroundStyle(by: .value("图层", key))
                    .lineStyle(StrokeStyle(lineWidth: 1.4))
                    .interpolationMethod(.linear)
                }
            }
        }
    }

    @ChartContentBuilder
    private func swingLevelMarks(_ levels: [Double]) -> some ChartContent {
        ForEach(levels, id: \.self) { level in
            RuleMark(y: .value("支撑阻力", level))
                .foregroundStyle(.secondary.opacity(0.55))
                .lineStyle(StrokeStyle(lineWidth: 0.8, dash: [3, 5]))
        }
    }

    @ChartContentBuilder
    private func fibonacciMarks(_ levels: [(ratio: Double, price: Double)]) -> some ChartContent {
        ForEach(levels, id: \.ratio) { level in
            RuleMark(y: .value("Fibonacci", level.price))
                .foregroundStyle(.orange.opacity(0.65))
                .lineStyle(StrokeStyle(lineWidth: 0.8, dash: [6, 4]))
        }
    }

    @ChartContentBuilder
    private var costMark: some ChartContent {
        if let portfolioCost {
            RuleMark(y: .value("持仓成本", portfolioCost))
                .foregroundStyle(.blue)
                .lineStyle(StrokeStyle(lineWidth: 1.2, dash: [8, 4]))
        }
    }

    @ChartContentBuilder
    private var alertMarks: some ChartContent {
        ForEach(alertPrices, id: \.self) { price in
            RuleMark(y: .value("价格提醒", price))
                .foregroundStyle(.orange)
                .lineStyle(StrokeStyle(lineWidth: 1.2, dash: [2, 3]))
        }
    }

    @ChartContentBuilder
    private var eventMarks: some ChartContent {
        if showEvents {
            ForEach(eventDates, id: \.self) { eventDate in
                RuleMark(x: .value("事件", eventDate, unit: .day))
                    .foregroundStyle(Color.secondary.opacity(0.35))
                    .lineStyle(StrokeStyle(lineWidth: 0.8, dash: [2, 2]))
            }
        }
    }

    @ChartContentBuilder
    private var trendLineMarks: some ChartContent {
        ForEach(trendLineIndices, id: \.self) { index in
            ForEach(Array(trendLines[index].enumerated()), id: \.offset) { _, anchor in
                LineMark(
                    x: .value("趋势线", anchor.date, unit: .day),
                    y: .value("趋势线价格", anchor.price)
                )
                .foregroundStyle(by: .value("图层", "趋势线 \(index + 1)"))
                .lineStyle(StrokeStyle(lineWidth: 1.6))
                .symbol(.circle)
            }
        }
    }

    private func chartInteractionLayer(proxy: ChartProxy, size: CGSize) -> some View {
        Rectangle()
            .fill(.clear)
            .contentShape(.rect)
            .gesture(
                DragGesture(minimumDistance: 1)
                    .onChanged { value in
                        handlePan(translation: value.translation.width, width: size.width)
                    }
            )
            .gesture(
                MagnificationGesture()
                    .onChanged { value in handleZoom(scale: value / max(magnification, 0.001)) }
                    .onEnded { _ in magnification = 1 }
            )
            .onContinuousHover { phase in
                switch phase {
                case let .active(location):
                    handleHover(at: location, proxy: proxy, size: size)
                case .ended:
                    hoverCandle = nil
                }
            }
            .onTapGesture { location in
                handleTap(at: location, proxy: proxy, size: size)
            }
            .overlay(alignment: .topLeading) {
                if let hover = hoverCandle {
                    CandleTooltip(
                        candle: hover.candle,
                        eventTitle: eventTitle(for: hover.date)
                    )
                    .padding(6)
                }
            }
    }

    private var chartControls: some View {
        HStack(spacing: 10) {
            Toggle("均线", isOn: $showMovingAverages).toggleStyle(.checkbox)
            Toggle("支撑阻力", isOn: $showSwingLevels).toggleStyle(.checkbox)
            Toggle("Fibonacci", isOn: $showFibonacci).toggleStyle(.checkbox)
            Toggle("事件", isOn: $showEvents).toggleStyle(.checkbox)
            Divider().frame(height: 14)
            Button(drawMode ? "画线中（点两点）" : "趋势线") { drawMode.toggle(); pendingAnchor = nil }
                .buttonStyle(.bordered).tint(drawMode ? .purple : .accentColor)
            if !trendLines.isEmpty {
                Button("清除趋势线") { trendLines = []; pendingAnchor = nil }.buttonStyle(.borderless)
            }
            Spacer()
            Button("重置缩放") {
                visibleStart = nil
                visibleEnd = nil
            }
            .buttonStyle(.borderless)
        }
        .font(.callout)
    }

    private func volumeChart(domain: ClosedRange<Date>, windowCandles: [TimedCandle]) -> some View {
        Chart {
            ForEach(windowCandles) { timed in
                BarMark(
                    x: .value("日期", timed.date, unit: .day),
                    y: .value("成交量", Double(timed.candle.volume)),
                    width: .ratio(0.62)
                )
                .foregroundStyle(timed.candle.close >= timed.candle.open ? Color.green.opacity(0.55) : Color.red.opacity(0.55))
            }
        }
        .chartXScale(domain: domain)
        .chartXAxis(.hidden)
        .chartYAxis {
            AxisMarks(position: .leading, values: .automatic(desiredCount: 2)) { _ in
                AxisGridLine().foregroundStyle(.quaternary)
                AxisValueLabel().font(.system(.caption2, design: .monospaced))
            }
        }
        .frame(height: 72)
        .accessibilityLabel("成交量副图，共 \(windowCandles.count) 根K线")
    }

    private var fullDomain: ClosedRange<Date> {
        guard let first = candles.first?.date, let last = candles.last?.date, last > first else {
            let today = ChartDomain.normalize(.now)
            return today ... today
        }
        return first ... last
    }

    private var visibleDomain: ClosedRange<Date> {
        let full = fullDomain
        guard let start = visibleStart, let end = visibleEnd, start < end else { return full }
        let clampedStart = max(start, full.lowerBound)
        let clampedEnd = min(end, full.upperBound)
        guard clampedStart < clampedEnd else { return full }
        return clampedStart ... clampedEnd
    }

    private var eventDates: [Date] {
        events.compactMap { ChartTime.day($0.time) }.map(ChartDomain.normalize)
    }

    private var trendLineIndices: Range<Int> {
        0 ..< trendLines.count
    }

    private func eventTitle(for date: Date) -> String? {
        events.first { ChartTime.day($0.time).map { ChartDomain.normalize($0) } == date }?.title
    }

    private func handlePan(translation: CGFloat, width: CGFloat) {
        let full = fullDomain
        let visible = visibleDomain
        let total = full.upperBound.timeIntervalSince(full.lowerBound)
        guard total > 0, width > 0 else { return }
        let fraction = Double(-translation) / width
        let shift = total * 0.6 * fraction
        let span = visible.upperBound.timeIntervalSince(visible.lowerBound)
        let newStart = min(max(visible.lowerBound.addingTimeInterval(shift), full.lowerBound), full.upperBound.addingTimeInterval(-span))
        let newEnd = newStart.addingTimeInterval(span)
        guard newStart < newEnd else { return }
        visibleStart = newStart
        visibleEnd = newEnd
    }

    private func handleZoom(scale: CGFloat) {
        let full = fullDomain
        let visible = visibleDomain
        let center = visible.lowerBound.addingTimeInterval(visible.duration / 2)
        let span = max(visible.duration / Double(max(scale, 0.1)), 60 * 86400)
        let newStart = center.addingTimeInterval(-span / 2)
        let newEnd = center.addingTimeInterval(span / 2)
        guard newStart < newEnd else { return }
        visibleStart = min(max(newStart, full.lowerBound), full.upperBound)
        visibleEnd = max(min(newEnd, full.upperBound), full.lowerBound)
    }

    private func handleHover(at location: CGPoint, proxy: ChartProxy, size: CGSize) {
        let date = resolvedDate(at: location, proxy: proxy, size: size)
        guard let date else {
            hoverCandle = nil
            return
        }
        hoverCandle = candles.min {
            abs($0.date.timeIntervalSince(date)) < abs($1.date.timeIntervalSince(date))
        }
    }

    private func handleTap(at location: CGPoint, proxy: ChartProxy, size: CGSize) {
        guard drawMode else { return }
        let date = resolvedDate(at: location, proxy: proxy, size: size)
        guard let date, let price = resolvedPrice(at: location, proxy: proxy),
              let nearest = candles.min(by: {
                  abs($0.date.timeIntervalSince(date)) < abs($1.date.timeIntervalSince(date))
              })
        else { return }
        let anchor = TrendAnchor(date: nearest.date, price: price)
        if let pending = pendingAnchor {
            if pending.date != anchor.date {
                trendLines.append([pending, anchor])
            }
            pendingAnchor = nil
        } else {
            pendingAnchor = anchor
        }
    }

    private func resolvedDate(at location: CGPoint, proxy: ChartProxy, size: CGSize) -> Date? {
        if let value = proxy.value(atX: location.x, as: Date.self) {
            return value
        }
        let fraction = max(0, min(1, location.x / max(size.width, 1)))
        let visible = visibleDomain
        return visible.lowerBound.addingTimeInterval(visible.duration * fraction)
    }

    private func resolvedPrice(at location: CGPoint, proxy: ChartProxy) -> Double? {
        if let value = proxy.value(atY: location.y, as: Double.self) {
            return value
        }
        return nil
    }
}

private extension ClosedRange<Date> {
    var duration: TimeInterval {
        upperBound.timeIntervalSince(lowerBound)
    }
}

public struct CandleTooltip: View {
    public let candle: ChartCandle
    public let eventTitle: String?

    public var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(String(candle.time.prefix(10))).font(.caption2.bold())
            LabeledContent("开", value: candle.open.formatted(.number.precision(.fractionLength(2))))
            LabeledContent("高", value: candle.high.formatted(.number.precision(.fractionLength(2))))
            LabeledContent("低", value: candle.low.formatted(.number.precision(.fractionLength(2))))
            LabeledContent("收", value: candle.close.formatted(.number.precision(.fractionLength(2))))
            LabeledContent("量", value: candle.volume.formatted(.number.notation(.compactName)))
            if let eventTitle {
                Label(eventTitle, systemImage: "bookmark").font(.caption2).foregroundStyle(.secondary)
            }
        }
        .font(.caption2.monospacedDigit())
        .padding(8)
        .background(.regularMaterial, in: .rect(cornerRadius: 8))
        .accessibilityIdentifier("chart.candle-tooltip")
    }
}

// MARK: - 收益率曲线（宏观期限结构专用，R6.0 统一 chrome）

/// 宏观收益率曲线：palette 颜色 + 形状双编码、十字光标 tooltip、图例与数据摘要。
public struct YieldCurveChart: View {
    public let curves: [YieldCurveSnapshot]
    @State private var hoverMaturity: String?

    public init(curves: [YieldCurveSnapshot]) {
        self.curves = curves
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
            chartBody
            curveLegend
            DisclosureGroup("图表数据摘要（非视觉访问）") {
                ChartSeriesSummaryTable(curveSummaries)
            }
            .font(.headline)
            .accessibilityIdentifier("chart.yield-curve.summary-disclosure")
        }
    }

    private var chartBody: some View {
        Chart {
            ForEach(Array(curves.enumerated()), id: \.element.id) { index, snapshot in
                ForEach(Array(snapshot.points.enumerated()), id: \.offset) { _, point in
                    LineMark(
                        x: .value("期限", point.maturity),
                        y: .value("收益率 %", point.value ?? 0)
                    )
                    .foregroundStyle(StockMonitorChartPalette.chartTint(index))
                    .lineStyle(StockMonitorChartPalette.seriesStroke(index))
                    .interpolationMethod(.catmullRom)
                    .symbol(StockMonitorChartPalette.seriesMarker(index).basicSymbol)
                    .symbolSize(index == 0 ? 36 : 24)
                    if hoverMaturity == point.maturity, let value = point.value {
                        PointMark(
                            x: .value("期限", point.maturity),
                            y: .value("收益率 %", value)
                        )
                        .foregroundStyle(StockMonitorChartPalette.chartTint(index))
                        .symbolSize(90)
                    }
                }
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading) { _ in
                AxisGridLine().foregroundStyle(.quaternary)
                AxisValueLabel().font(.system(.caption2, design: .monospaced))
            }
        }
        .chartXAxis {
            AxisMarks { _ in
                AxisGridLine().foregroundStyle(.quaternary)
                AxisValueLabel().font(.caption2)
            }
        }
        .frame(height: 300)
        .chartOverlay { proxy in
            GeometryReader { geometry in
                Rectangle().fill(.clear).contentShape(.rect)
                    .onContinuousHover { phase in
                        switch phase {
                        case let .active(location):
                            hoverMaturity = maturity(at: location, proxy: proxy, size: geometry.size)
                        case .ended:
                            hoverMaturity = nil
                        }
                    }
                    .overlay(alignment: .topLeading) {
                        if let hoverMaturity {
                            SeriesValueTooltip(
                                title: "期限 \(hoverMaturity)",
                                entries: Array(curves.enumerated()).map { index, snapshot in
                                    let value = snapshot.points.first { $0.maturity == hoverMaturity }?.value
                                    return SeriesValueTooltip.Entry(
                                        name: snapshot.label,
                                        color: StockMonitorChartPalette.chartTint(index),
                                        value: value.map { $0.formatted(.number.precision(.fractionLength(2))) + "%" } ?? "数据不足"
                                    )
                                },
                                footnote: nil
                            )
                            .padding(6)
                        }
                    }
            }
        }
        .accessibilityLabel(accessibilitySummary)
        .accessibilityIdentifier("chart.yield-curve")
    }

    /// 图例 = 形状 + 颜色 + 名称 + 观察日，颜色不是唯一编码。
    private var curveLegend: some View {
        HStack(spacing: StockMonitorSpacing.regular) {
            ForEach(Array(curves.enumerated()), id: \.element.id) { index, snapshot in
                HStack(spacing: StockMonitorSpacing.xSmall) {
                    Image(systemName: StockMonitorChartPalette.seriesMarker(index).systemImageName)
                        .font(.caption2.weight(.bold))
                        .foregroundStyle(StockMonitorChartPalette.chartTint(index))
                        .accessibilityHidden(true)
                    Text("\(snapshot.label)\(snapshot.observationDate.map { "（\($0)）" } ?? "")")
                        .stockMonitorTypography(.metadata)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .accessibilityIdentifier("chart.yield-curve.legend")
    }

    private var curveSummaries: [ChartSeriesSummaryRow] {
        curves.map { snapshot in
            let values = snapshot.points.compactMap(\.value)
            let maturityText = snapshot.points.first { $0.value == values.last }.map(\.maturity)
            func text(_ value: Double?) -> FinancialDisplayValue {
                value.map { FinancialDisplayValue(text: $0.formatted(.number.precision(.fractionLength(2)))) }
                    ?? FinancialValueFormatter.missing(.notCollected)
            }
            return ChartSeriesSummaryRow(
                name: snapshot.label,
                latest: text(values.last),
                minimum: text(values.min()),
                maximum: text(values.max()),
                observationWindow: "期限 \(snapshot.points.first?.maturity ?? "—") 至 \(snapshot.points.last?.maturity ?? "—")"
                    + "；观察日 \(snapshot.observationDate ?? "—")（最新值位于 \(maturityText ?? "—")）"
            )
        }
    }

    private var accessibilitySummary: String {
        curves.map { snapshot in
            let values = snapshot.points.compactMap(\.value)
            let latest = values.last.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足"
            return "\(snapshot.label) 最新 \(latest)%"
        }.joined(separator: "，")
    }

    private func maturity(at location: CGPoint, proxy: ChartProxy, size: CGSize) -> String? {
        if let value = proxy.value(atX: location.x, as: String.self) {
            return value
        }
        let all = curves.flatMap(\.points).map(\.maturity)
        guard !all.isEmpty else { return nil }
        let fraction = max(0, min(1, location.x / max(size.width, 1)))
        let index = min(all.count - 1, Int(fraction * Double(all.count)))
        return all[index]
    }
}
