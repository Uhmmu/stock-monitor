import Charts
import StockMonitorDesign
import SwiftUI

// MARK: - 美国宏观

@MainActor
@Observable
public final class MacroModel {
    public enum Tab: String, CaseIterable, Identifiable {
        case overview = "概览"
        case series = "指标序列"
        case yieldCurve = "收益率曲线"
        case sync = "同步状态"
        public var id: Self {
            self
        }
    }

    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var tab: Tab = .overview
    public private(set) var overview: MacroOverview?
    public private(set) var series: [MacroSeriesRow] = []
    public private(set) var detail: MacroSeriesDetail?
    public private(set) var detailKey: String?
    public private(set) var detailPoints: [TimedPoint] = []
    public private(set) var curve: MacroYieldCurve?
    public private(set) var syncStatus: MacroSyncStatus?
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func select(_ tab: Tab) {
        self.tab = tab
    }

    public func loadOverview() async {
        state = overview == nil ? .loading : .refreshing
        do {
            overview = try await service.macroOverview()
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = overview == nil ? .error : .stale
        }
    }

    public func loadSeries() async {
        do {
            series = try await service.macroSeries()
        } catch {
            self.error = .from(error)
        }
    }

    public func loadDetail(key: String) async {
        detailKey = key
        do {
            let value = try await service.macroSeriesDetail(key: key)
            detail = value
            detailPoints = (value.observations ?? []).compactMap { observation in
                guard let price = observation.value, let date = ChartTime.day(observation.observationDate) else { return nil }
                return TimedPoint(date: ChartDomain.normalize(date), value: price)
            }
        } catch {
            self.error = .from(error)
        }
    }

    public func loadCurve() async {
        do {
            curve = try await service.macroYieldCurve()
        } catch {
            self.error = .from(error)
        }
    }

    public func loadSyncStatus() async {
        do {
            syncStatus = try await service.macroSyncStatus()
        } catch {
            self.error = .from(error)
        }
    }
}

public struct MacroView: View {
    @State private var model: MacroModel
    @State private var selectedSeriesKey: String?

    init(model: MacroModel) {
        _model = State(initialValue: model)
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    M4SectionHeader("美国宏观", subtitle: "Alpha Vantage 日同步；缺值显示数据不足")
                    Spacer()
                    Picker("分区", selection: Binding(get: { model.tab }, set: { model.select($0) })) {
                        ForEach(MacroModel.Tab.allCases) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented).frame(width: 380)
                    Button("刷新") { Task { await reload() } }
                }
                .padding(20)
                FeatureErrorBanner(error: model.error).padding(.horizontal, 20)
                Group {
                    switch model.tab {
                    case .overview: overviewTab
                    case .series: seriesTab
                    case .yieldCurve: curveTab
                    case .sync: syncTab
                    }
                }
                .padding(.horizontal, 20).padding(.bottom, 20)
            }
        }
        .navigationTitle("美国宏观")
        .task { await model.loadOverview() }
        .accessibilityIdentifier("m4.macro")
    }

    private func reload() async {
        switch model.tab {
        case .overview: await model.loadOverview()
        case .series:
            await model.loadSeries()
            if let key = selectedSeriesKey {
                await model.loadDetail(key: key)
            }
        case .yieldCurve: await model.loadCurve()
        case .sync: await model.loadSyncStatus()
        }
    }

    @ViewBuilder
    private var overviewTab: some View {
        if let overview = model.overview {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 16) {
                        if let latest = overview.latestObservationDate {
                            LabeledContent("最新观察", value: latest)
                        }
                        if let status = overview.lastAttemptStatus {
                            LabeledContent("最近同步", value: status)
                        }
                        if let success = overview.lastSuccessfulSyncAt {
                            LabeledContent("上次成功", value: String(success.prefix(19).replacingOccurrences(of: "T", with: " ")))
                        }
                    }.font(.callout)
                    cardSection("宏观卡片", overview.cards)
                    cardSection("曲线分析", overview.curveAnalysis)
                    cardSection("序列摘要", overview.summaries)
                    cardSection("数据源与用量", overview.source)
                    DisclosureGroup("完整性与免责声明") {
                        SemanticEvidenceView(value: overview.integrity, domain: .macro).padding(.top, 6)
                        if let disclaimer = overview.disclaimer {
                            Text(disclaimer).font(.caption).foregroundStyle(.secondary).padding(.top, 4)
                        }
                    }
                    .font(.headline)
                }
            }
        } else {
            ContentUnavailableView("暂无宏观数据", systemImage: "globe.americas")
        }
    }

    private func cardSection(_ title: String, _ value: JSONValue?) -> some View {
        DisclosureGroup(title) {
            SemanticEvidenceView(value: value, domain: .macro).padding(.top, 8)
        }
        .font(.headline)
    }

    private var seriesTab: some View {
        HSplitView {
            List(model.series, selection: $selectedSeriesKey) { row in
                VStack(alignment: .leading, spacing: 2) {
                    Text(row.nameZh ?? row.nameEn ?? row.seriesKey).fontWeight(.medium)
                    HStack {
                        Text(row.current?.displayText ?? "数据不足").font(.caption).monospacedDigit()
                        Text(row.observationDate ?? "").font(.caption2).foregroundStyle(.secondary)
                        if let status = row.dataStatus, status != "available" {
                            SemanticStatusLabel(status == "insufficient" ? "数据不足" : status, status: .unavailable)
                        }
                    }
                }.tag(row.seriesKey)
            }
            .frame(minWidth: 260, idealWidth: 320)
            .task {
                if model.series.isEmpty {
                    await model.loadSeries()
                }
            }
            .onChange(of: selectedSeriesKey) { _, key in
                if let key {
                    Task { await model.loadDetail(key: key) }
                }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let detail = model.detail {
                        M4SectionHeader(detail.nameZh ?? detail.seriesKey ?? "指标详情", subtitle: detail.seriesKey)
                        if model.detailPoints.count >= 2 {
                            LineSeriesChart(series: [LineSeries(name: detail.nameZh ?? "数值", color: .accentColor, points: model.detailPoints)])
                                .frame(height: 260)
                        } else {
                            Text("数据不足：该序列没有足够观察值。").foregroundStyle(.secondary)
                        }
                        latestStrip(detail)
                        DisclosureGroup("如何解读") {
                            SemanticEvidenceView(value: detail.interpretation, domain: .macro).padding(.top, 6)
                        }
                        .font(.headline)
                        DisclosureGroup("新鲜度与派生序列") {
                            SemanticEvidenceView(value: detail.freshness, domain: .macro).padding(.top, 6)
                            SemanticEvidenceView(value: detail.derivedSeries, domain: .macro).padding(.top, 6)
                        }
                        .font(.headline)
                    } else {
                        ContentUnavailableView("选择左侧指标", systemImage: "chart.line.uptrend.xyaxis")
                    }
                }.padding(20)
            }.frame(minWidth: 420)
        }
    }

    private func latestStrip(_ detail: MacroSeriesDetail) -> some View {
        HStack(spacing: 18) {
            LabeledContent("最新值") {
                Text(detail.latest?.displayText ?? "数据不足").monospacedDigit()
            }
            LabeledContent("前一观察期") {
                Text(detail.previous?.displayText ?? "数据不足").monospacedDigit()
            }
            if let status = detail.dataStatus {
                LabeledContent("状态", value: status)
            }
        }.font(.callout)
    }

    @ViewBuilder
    private var curveTab: some View {
        if let curve = model.curve {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    M4SectionHeader("收益率曲线", subtitle: "最新与前一观察日的国债期限结构")
                    Chart {
                        ForEach(curve.curves) { snapshot in
                            ForEach(Array(snapshot.points.enumerated()), id: \.offset) { _, point in
                                LineMark(
                                    x: .value("期限", point.maturity),
                                    y: .value("收益率 %", point.value ?? 0)
                                )
                                .foregroundStyle(by: .value("曲线", snapshot.label))
                                .lineStyle(StrokeStyle(lineWidth: 1.8))
                                .interpolationMethod(.catmullRom)
                                if let value = point.value {
                                    PointMark(
                                        x: .value("期限", point.maturity),
                                        y: .value("收益率 %", value)
                                    )
                                    .foregroundStyle(by: .value("曲线", snapshot.label))
                                    .symbolSize(24)
                                }
                            }
                        }
                    }
                    .chartXAxis {
                        AxisMarks { _ in
                            AxisValueLabel().font(.caption)
                        }
                    }
                    .frame(height: 300)
                    SemanticEvidenceView(value: curve.spreads, domain: .macro)
                    Text(curve.disclaimer ?? "").font(.caption).foregroundStyle(.secondary)
                }.padding(20)
            }
            .task {
                if model.curve == nil {
                    await model.loadCurve()
                }
            }
        } else {
            ContentUnavailableView("收益率曲线数据不足", systemImage: "chart.dots.scatter")
                .task {
                    if model.curve == nil {
                        await model.loadCurve()
                    }
                }
        }
    }

    @ViewBuilder
    private var syncTab: some View {
        if let status = model.syncStatus {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(spacing: 16) {
                        if let next = status.nextScheduledSync {
                            LabeledContent("计划同步", value: next)
                        }
                        if let last = status.lastAttemptStatus {
                            LabeledContent("最近尝试", value: last)
                        }
                    }.font(.callout)
                    SemanticEvidenceView(value: status.usage, domain: .macro)
                    DisclosureGroup("同步运行历史") {
                        SemanticEvidenceView(value: status.runs, domain: .macro).padding(.top, 6)
                    }
                    .font(.headline)
                }.padding(20)
            }
            .task {
                if model.syncStatus == nil {
                    await model.loadSyncStatus()
                }
            }
        } else {
            ContentUnavailableView("同步状态数据不足", systemImage: "arrow.triangle.2.circlepath")
                .task {
                    if model.syncStatus == nil {
                        await model.loadSyncStatus()
                    }
                }
        }
    }
}
