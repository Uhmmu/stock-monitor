import Charts
import StockMonitorDesign
import SwiftUI

// MARK: - 行业板块 Pulse

@MainActor
@Observable
public final class IndustryPulseModel {
    public enum Tab: String, CaseIterable, Identifiable {
        case overview = "板块概览"
        case aiChain = "AI 产业链"
        case focus = "焦点信号"
        case status = "系统状态"
        public var id: Self {
            self
        }
    }

    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var tab: Tab = .overview
    public private(set) var rangeDays = 90
    public private(set) var overview: IndustryPulseOverview?
    public private(set) var aiChain: IndustryAIPayload?
    public private(set) var focus: IndustryFocusPayload?
    public private(set) var status: IndustrySystemStatus?
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func select(_ tab: Tab) {
        self.tab = tab
    }

    public func load() async {
        state = overview == nil ? .loading : .refreshing
        do {
            async let overview = service.industryOverview(rangeDays: rangeDays)
            async let aiChain = service.industryAIChain(rangeDays: rangeDays)
            async let focus = service.industryFocus(rangeDays: rangeDays)
            async let status = service.industryStatus()
            let values = try await (overview, aiChain, focus, status)
            self.overview = values.0
            self.aiChain = values.1
            self.focus = values.2
            self.status = values.3
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = overview == nil ? .error : .stale
        }
    }

    public func setRange(_ days: Int) async {
        rangeDays = days
        await load()
    }
}

public struct IndustryPulseView: View {
    @State private var model: IndustryPulseModel

    init(model: IndustryPulseModel) {
        _model = State(initialValue: model)
    }

    private var rangeBinding: Binding<Int> {
        Binding(
            get: { model.rangeDays },
            set: { value in updateRange(value) }
        )
    }

    private func updateRange(_ value: Int) {
        Task { await model.setRange(value) }
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    M4SectionHeader("行业板块", subtitle: "板块脉冲、AI 产业链与焦点信号")
                    Spacer()
                    Picker("区间", selection: rangeBinding) {
                        Text("30 天").tag(30)
                        Text("90 天").tag(90)
                        Text("365 天").tag(365)
                    }
                    .pickerStyle(.segmented).frame(width: 220)
                    Picker("分区", selection: Binding(get: { model.tab }, set: { model.select($0) })) {
                        ForEach(IndustryPulseModel.Tab.allCases) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented).frame(width: 380)
                }
                .padding(20)
                FeatureErrorBanner(error: model.error).padding(.horizontal, 20)
                Group {
                    switch model.tab {
                    case .overview: overviewTab
                    case .aiChain: aiChainTab
                    case .focus: focusTab
                    case .status: statusTab
                    }
                }
                .padding(.horizontal, 20).padding(.bottom, 20)
            }
        }
        .navigationTitle("行业板块")
        .task { await model.load() }
        .accessibilityIdentifier("m4.industry")
    }

    @ViewBuilder
    private var overviewTab: some View {
        if let overview = model.overview {
            if overview.status == "unavailable" {
                ContentUnavailableView("行业板块数据不足", systemImage: "square.grid.3x3")
            } else {
                Table(overview.sectors) {
                    TableColumn("板块") { row in
                        Text(row.nameZh ?? row.name ?? row.nodeKey ?? "数据不足").fontWeight(.medium)
                    }
                    TableColumn("脉冲") { row in
                        pulseLabel(row.pulse)
                    }
                    TableColumn("1 日") { row in percentLabel(row.change1d) }
                    TableColumn("5 日") { row in percentLabel(row.change5d) }
                    TableColumn("20 日") { row in percentLabel(row.change20d) }
                    TableColumn("方向") { row in
                        Text(row.direction ?? "—")
                    }
                    TableColumn("信心") { row in
                        Text(row.confidence.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
                            .monospacedDigit()
                    }
                    TableColumn("覆盖") { row in
                        Text(row.coverageQuality.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
                            .monospacedDigit()
                    }
                    TableColumn("状态") { row in
                        SemanticStatusLabel(
                            row.calculationStatus == "READY" ? "就绪" : "覆盖不足",
                            status: row.calculationStatus == "READY" ? .live : .unavailable
                        )
                    }
                }
                .frame(minHeight: 320)
                if let asOf = overview.asOf {
                    Text("数据截至 \(asOf)；代理 ETF：\(overview.sectors.compactMap(\.proxyEtfs).flatMap(\.self).prefix(6).joined(separator: "、"))")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func pulseLabel(_ value: Double?) -> some View {
        Text(value.map { $0.formatted(.number.precision(.fractionLength(1))) } ?? "数据不足")
            .monospacedDigit()
            .foregroundStyle(value == nil ? .secondary : .primary)
            .fontWeight(.semibold)
    }

    private func percentageColor(_ value: Double?) -> Color {
        guard let value else { return .secondary }
        return value >= 0 ? .green : .red
    }

    private func percentLabel(_ value: Double?) -> some View {
        Text(value.map { magnitude in
            magnitude.formatted(.number.precision(.fractionLength(2)).sign(strategy: .always()))
        } ?? "数据不足")
            .monospacedDigit()
            .foregroundStyle(percentageColor(value))
    }

    @ViewBuilder
    private var aiChainTab: some View {
        if let chain = model.aiChain, let groups = chain.groups, !groups.isEmpty {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    M4SectionHeader("AI 产业链", subtitle: "类别 → 环节 → 叶子节点；数值为服务端聚合")
                    ForEach(groups) { category in
                        DisclosureGroup {
                            ForEach(category.groups ?? []) { group in
                                DisclosureGroup {
                                    ForEach(group.groups ?? []) { leaf in
                                        industryRow(leaf, indent: 2)
                                    }
                                } label: {
                                    industryRow(group, indent: 1)
                                }
                            }
                        } label: {
                            industryRow(category, indent: 0)
                        }
                    }
                    if let asOf = chain.asOf {
                        Text("数据截至 \(String(asOf.prefix(10)))").font(.caption).foregroundStyle(.secondary)
                    }
                }.padding(4)
            }
        } else {
            ContentUnavailableView("AI 产业链数据不足", systemImage: "cpu")
        }
    }

    private func industryRow(_ item: IndustryAICategory, indent: Int) -> some View {
        HStack {
            Text(item.nameZh ?? item.name ?? item.nodeKey ?? "数据不足")
                .fontWeight(indent == 0 ? .semibold : .regular)
            Spacer()
            pulseLabel(item.pulse)
            percentLabel(item.change5d)
        }
        .font(calloutFont(indent))
        .padding(.leading, Double(indent) * 18)
    }

    private func calloutFont(_ indent: Int) -> Font {
        indent == 0 ? .headline : .callout
    }

    @ViewBuilder
    private var focusTab: some View {
        if let focus = model.focus {
            if focus.buckets.isEmpty {
                ContentUnavailableView("暂无焦点信号", systemImage: "sparkle.magnifyingglass")
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        M4SectionHeader("焦点信号", subtitle: "按信号类型分桶，数据截至 \(focus.asOf ?? "—")")
                        ForEach(focus.buckets.keys.sorted(), id: \.self) { key in
                            DisclosureGroup("\(key)（\(focus.buckets[key]?.count ?? 0)）") {
                                ForEach(focus.buckets[key] ?? []) { signal in
                                    HStack {
                                        Text(signal.nameZh ?? signal.name ?? signal.nodeKey ?? "数据不足")
                                        if let rank = signal.rank {
                                            Text("#\(rank)").font(.caption).foregroundStyle(.secondary)
                                        }
                                        Spacer()
                                        pulseLabel(signal.score)
                                        percentLabel(signal.change5d)
                                        Text(signal.direction ?? "").font(.caption).foregroundStyle(.secondary)
                                    }
                                    .font(.callout).padding(.vertical, 2)
                                }
                            }
                            .font(.headline)
                        }
                    }.padding(4)
                }
            }
        }
    }

    @ViewBuilder
    private var statusTab: some View {
        if let status = model.status {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    M4SectionHeader("系统状态")
                    JSONEvidenceView(value: status.marketData)
                    HStack(spacing: 16) {
                        LabeledContent("待复核种子替换", value: "\(status.replacementPending ?? 0)")
                    }.font(.callout)
                    DisclosureGroup("最近同步运行") {
                        JSONEvidenceView(value: status.latestRun).padding(.top, 6)
                    }
                    .font(.headline)
                }.padding(4)
            }
        }
    }
}
