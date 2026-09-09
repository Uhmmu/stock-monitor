import StockMonitorDesign
import SwiftUI

// MARK: - 技术分析模型

@MainActor
@Observable
public final class TechnicalAnalysisModel {
    public enum Interval: String, CaseIterable, Identifiable {
        case day = "日"
        case week = "周"
        case month = "月"
        public var id: Self {
            self
        }
    }

    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var detail: TechnicalAnalysisDetail?
    public private(set) var interval: Interval = .week
    public private(set) var pendingAlert = false
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func select(_ interval: Interval) {
        self.interval = interval
    }

    public var candles: [TimedCandle] {
        CandlePreparation.timedCandles(from: detail?.chartSeries?[interval.rawValue]?.candles ?? [])
    }

    public var movingAverages: [String: [TimedPoint]] {
        let raw = detail?.chartSeries?[interval.rawValue]?.movingAverages ?? [:]
        return raw.mapValues { CandlePreparation.timedPoints(from: $0) }
    }

    public var alertPrices: [Double] {
        (detail?.priceAlerts ?? []).filter(\.enabled).map(\.targetPrice)
    }

    public var hasChartData: Bool {
        detail?.chartDataStatus == "ready" && !candles.isEmpty
    }

    public func load(symbol: String) async {
        state = detail == nil ? .loading : .refreshing
        do {
            detail = try await service.technicalAnalysis(symbol: symbol)
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = detail == nil ? .error : .stale
        }
    }

    public func createAlert(symbol: String, target: Double, direction: String) async {
        pendingAlert = true
        defer { pendingAlert = false }
        do {
            let alert = try await service.createPriceAlert(symbol: symbol, targetPrice: target, direction: direction)
            var updated = detail?.priceAlerts ?? []
            updated.removeAll { $0.id == alert.id }
            updated.insert(alert, at: 0)
            detail?.priceAlerts = updated
        } catch {
            self.error = .from(error)
        }
    }

    public func deleteAlert(symbol: String, alert: TechnicalPriceAlert) async {
        do {
            try await service.deletePriceAlert(symbol: symbol, alertID: alert.id)
            detail?.priceAlerts?.removeAll { $0.id == alert.id }
        } catch {
            self.error = .from(error)
        }
    }
}

// MARK: - 技术分析视图

public struct TechnicalAnalysisView: View {
    @State private var model: TechnicalAnalysisModel
    @State private var symbol = ""
    @State private var newAlertTarget = ""
    @State private var newAlertDirection = "above"
    let initialSymbol: String?
    let tickerContext: CompanyTickerContext
    let companySummary: CompanySummaryModel

    init(model: TechnicalAnalysisModel, tickerContext: CompanyTickerContext, companySummary: CompanySummaryModel, symbol: String?) {
        _model = State(initialValue: model)
        _symbol = State(initialValue: symbol ?? "")
        initialSymbol = symbol
        self.tickerContext = tickerContext
        self.companySummary = companySummary
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            PageScaffold(width: StockMonitorContentWidth.wide) {
                PageHeader("技术分析", summary: "图表为主、关键指标侧栏；打开图表不触发任何上游行情或付费请求。") {
                    CompanySymbolBar(
                        context: tickerContext,
                        service: model.service,
                        symbol: $symbol,
                        initialSymbol: initialSymbol
                    ) { value in
                        await model.load(symbol: value)
                    }
                }
            } content: {
                CompanyHeaderView(summary: companySummary.summary(for: symbol))
                if let detail = model.detail {
                    headerStrip(detail)
                    intervalPicker
                    chartWithSideMetrics(detail)
                    chartFootnote
                    accessibilitySummary(detail)
                    alertSection
                    analysisSection(detail)
                    eventsSection(detail)
                }
            }
            .refreshable { await model.load(symbol: symbol) }
        }
        .navigationTitle("技术分析")
        .task {
            await companySummary.loadIfNeeded()
            guard let resolved = await tickerContext.resolveAfterLoad(service: model.service, preferred: initialSymbol) else { return }
            symbol = resolved
            await model.load(symbol: resolved)
        }
        .onChange(of: initialSymbol) { _, value in
            guard let value, tickerContext.symbols.contains(value) else { return }
            symbol = value
            Task { await model.load(symbol: value) }
        }
        .overlay(alignment: .top) { FeatureErrorBanner(error: model.error).padding(StockMonitorSpacing.regular) }
        .accessibilityIdentifier("m4.technical")
    }

    private func headerStrip(_ detail: TechnicalAnalysisDetail) -> some View {
        HStack(spacing: StockMonitorSpacing.regular) {
            SemanticStatusLabel("状态：\(statusLabel(detail.status))", status: detail.status == "ready" ? .live : .stale)
            if let generatedAt = detail.generatedAt {
                Text("生成于 \(String(generatedAt.prefix(10)))").stockMonitorTypography(.metadata)
            }
            if detail.stale == true {
                SemanticStatusLabel("数据过期", status: .warning)
            }
            if let source = detail.chartDataSource {
                Text("图表数据：\(source)").stockMonitorTypography(.metadata)
            }
        }
    }

    /// R4.2：图表占主列，关键指标放在侧栏，解释不再堆在图下。
    private func chartWithSideMetrics(_ detail: TechnicalAnalysisDetail) -> some View {
        HStack(alignment: .top, spacing: StockMonitorSpacing.regular) {
            chartSection(detail)
                .frame(maxWidth: .infinity, alignment: .leading)
            sideMetrics(detail)
                .frame(width: 210, alignment: .topLeading)
        }
    }

    private func sideMetrics(_ detail: TechnicalAnalysisDetail) -> some View {
        let candles = model.candles
        var items: [MetricItem] = []
        if let latest = candles.last {
            items.append(.init(label: "最新收盘", value: FinancialDisplayValue(text: two(latest.candle.close)), status: .neutral))
        }
        if let high = candles.map(\.candle.high).max() {
            items.append(.init(label: "区间最高", value: FinancialDisplayValue(text: two(high)), status: .neutral))
        }
        if let low = candles.map(\.candle.low).min() {
            items.append(.init(label: "区间最低", value: FinancialDisplayValue(text: two(low)), status: .neutral))
        }
        items.append(.init(label: "K 线数量", value: FinancialDisplayValue(text: "\(candles.count) 根（\(model.interval.rawValue)线）"), status: .neutral))
        if let cost = detail.portfolioCost {
            items.append(.init(
                label: "持仓成本",
                value: FinancialDisplayValue(
                    text: two(cost.averageCost),
                    qualifier: "\(cost.currency ?? "") × \(cost.quantity.formatted(.number.precision(.fractionLength(0))))"
                ),
                status: .info
            ))
        }
        items.append(.init(
            label: "价格提醒",
            value: FinancialDisplayValue(text: "\(model.alertPrices.count) 条生效"),
            status: model.alertPrices.isEmpty ? .neutral : .warning
        ))
        return VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
            SectionHeader("关键指标")
            VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                ForEach(items) { item in
                    VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                        Text(item.label).stockMonitorTypography(.metricLabel)
                        Text(item.value.text).financialFigures()
                        if let qualifier = item.value.qualifier {
                            Text(qualifier).stockMonitorTypography(.microAnnotation)
                        }
                    }
                }
            }
            .padding(StockMonitorSpacing.medium)
            .stockMonitorSurface(.grouped)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("r4.technical.side-metrics")
    }

    private var chartFootnote: some View {
        Text("拖动平移、双指缩放、悬停查看十字光标；支撑阻力与 Fibonacci 基于当前可视区间计算，仅作图形参考，不构成服务端结论。")
            .stockMonitorTypography(.metadata)
    }

    private var intervalPicker: some View {
        Picker("周期", selection: Binding(
            get: { model.interval },
            set: { model.select($0) }
        )) {
            ForEach(TechnicalAnalysisModel.Interval.allCases) { Text($0.rawValue).tag($0) }
        }
        .pickerStyle(.segmented)
        .frame(width: 200)
    }

    @ViewBuilder
    private func chartSection(_ detail: TechnicalAnalysisDetail) -> some View {
        if model.hasChartData {
            CandleChartView(
                candles: model.candles,
                movingAverages: model.movingAverages,
                events: detail.events ?? [],
                portfolioCost: detail.portfolioCost?.averageCost,
                alertPrices: model.alertPrices
            )
            .padding(12)
            .background(.background.secondary, in: .rect(cornerRadius: 12))
            Text("拖动平移、双指缩放、悬停查看十字光标；支撑阻力与 Fibonacci 基于当前可视区间计算，仅作图形参考，不构成服务端结论。")
                .font(.caption).foregroundStyle(.secondary)
        } else if detail.chartDataStatus == "insufficient" {
            ContentUnavailableView {
                Label("图表数据不足", systemImage: "chart.xyaxis.line")
            } description: {
                Text(chartReason(detail.chartDataReason))
            }
        } else {
            ContentUnavailableView("等待技术图表生成", systemImage: "hourglass")
        }
    }

    private func chartReason(_ reason: String?) -> String {
        switch reason {
        case "historical_data_unavailable": "历史价格尚未同步，请等待服务端采集。"
        default: reason ?? "图表数据不足"
        }
    }

    private func statusLabel(_ status: String) -> String {
        switch status {
        case "ready": "就绪"
        case "pending": "生成中"
        default: status
        }
    }

    private func accessibilitySummary(_ detail: TechnicalAnalysisDetail) -> some View {
        DisclosureGroup("图表数据摘要（非视觉访问）") {
            let candles = model.candles
            if candles.isEmpty {
                Text("数据不足").foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    Text(summaryText(candles)).font(.callout)
                    if let cost = detail.portfolioCost {
                        Text("持仓成本 \(cost.averageCost.formatted(.number.precision(.fractionLength(2)))) \(cost.currency ?? "") × \(cost.quantity.formatted())")
                            .font(.callout)
                    }
                    ForEach(Array(candles.suffix(30).reversed())) { timed in
                        LabeledContent(String(timed.candle.time.prefix(10))) {
                            Text("开\(two(timed.candle.open)) 高\(two(timed.candle.high)) 低\(two(timed.candle.low)) 收\(two(timed.candle.close)) 量\(timed.candle.volume)")
                        }
                        .font(.caption.monospacedDigit())
                    }
                }.padding(.top, 6)
            }
        }
        .font(.headline)
    }

    private func summaryText(_ candles: [TimedCandle]) -> String {
        guard let latest = candles.last else { return "数据不足" }
        let highs = candles.map(\.candle.high)
        let lows = candles.map(\.candle.low)
        return "最近收盘 \(two(latest.candle.close))；区间最高 \(two(highs.max() ?? 0))、最低 \(two(lows.min() ?? 0))；共 \(candles.count) 根K线（\(model.interval.rawValue)线）。"
    }

    private func two(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(2)))
    }

    private var alertSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            M4SectionHeader("价格提醒", subtitle: "服务端评估触发，客户端只读写提醒配置")
            HStack {
                TextField("目标价", text: $newAlertTarget).textFieldStyle(.roundedBorder).frame(width: 110)
                Picker("方向", selection: $newAlertDirection) {
                    Text("上穿").tag("above")
                    Text("下穿").tag("below")
                }
                .pickerStyle(.menu)
                .frame(width: 110)
                Button("添加提醒") {
                    if let target = Double(newAlertTarget), target > 0 {
                        Task {
                            await model.createAlert(symbol: symbol, target: target, direction: newAlertDirection)
                            newAlertTarget = ""
                        }
                    }
                }
                .buttonStyle(.bordered)
                .disabled(Double(newAlertTarget) == nil || model.pendingAlert)
                if model.pendingAlert {
                    ProgressView().controlSize(.small)
                }
            }
            let alerts = model.detail?.priceAlerts ?? []
            if alerts.isEmpty {
                Text("暂无价格提醒").foregroundStyle(.secondary)
            } else {
                Table(alerts) {
                    TableColumn("目标价") { alert in
                        Text(alert.targetPrice.formatted(.number.precision(.fractionLength(2)))).monospacedDigit()
                    }
                    TableColumn("方向") { alert in
                        Text(alert.direction == "above" ? "上穿" : "下穿")
                    }
                    TableColumn("状态") { alert in
                        SemanticStatusLabel(
                            alert.triggeredAt != nil ? "已触发" : (alert.enabled ? "监控中" : "停用"),
                            status: alert.triggeredAt != nil ? .warning : .live
                        )
                    }
                    TableColumn("创建于") { alert in
                        Text(alert.createdAt.map { String($0.prefix(10)) } ?? "—")
                    }
                    TableColumn("") { alert in
                        Button("删除", role: .destructive) {
                            Task { await model.deleteAlert(symbol: symbol, alert: alert) }
                        }.buttonStyle(.borderless)
                    }
                }
                .frame(minHeight: 120)
            }
        }
        .padding(14)
        .background(.background.secondary, in: .rect(cornerRadius: 10))
    }

    @ViewBuilder
    private func analysisSection(_ detail: TechnicalAnalysisDetail) -> some View {
        if let analysis = detail.analysis {
            DisclosureGroup("服务端技术分析结论") {
                SemanticEvidenceView(value: analysis, domain: .technical).padding(.top, 8)
            }
            .font(.headline)
        }
    }

    @ViewBuilder
    private func eventsSection(_ detail: TechnicalAnalysisDetail) -> some View {
        let events = detail.events ?? []
        if !events.isEmpty {
            DisclosureGroup("图表事件（\(events.count)）") {
                Table(events) {
                    TableColumn("日期") { event in
                        Text(String(event.time.prefix(10)))
                    }
                    TableColumn("类型") { event in
                        Text(event.type)
                    }
                    TableColumn("说明") { event in
                        Text(event.title ?? event.label ?? "—")
                    }
                    TableColumn("来源") { event in
                        if let raw = event.href, let url = URL(string: raw), raw.hasPrefix("http") {
                            ConfirmExternalLinkButton(url: url)
                        } else {
                            Text("内部深链").foregroundStyle(.secondary)
                        }
                    }
                }
                .frame(minHeight: 140)
                .padding(.top, 8)
            }
            .font(.headline)
        }
    }
}
