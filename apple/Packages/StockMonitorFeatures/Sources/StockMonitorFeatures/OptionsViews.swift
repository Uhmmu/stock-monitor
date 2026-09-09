import Charts
import StockMonitorDesign
import SwiftUI

// MARK: - 期权研究

@MainActor
@Observable
public final class OptionsModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var overview: OptionsOverview?
    public private(set) var ranking = "activity"
    public private(set) var detail: OptionDetailResponse?
    public private(set) var detailSymbol: String?
    public private(set) var detailExpiration: String?
    public private(set) var ivSeries: [TimedPoint] = []
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func load(ranking: String) async {
        self.ranking = ranking
        state = overview == nil ? .loading : .refreshing
        do {
            overview = try await service.optionsOverview(ranking: ranking)
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = overview == nil ? .error : .stale
        }
    }

    public func loadDetail(symbol: String, expiration: String? = nil) async {
        detailSymbol = symbol
        do {
            let value = try await service.optionDetail(symbol: symbol, expiration: expiration)
            detail = value
            detailExpiration = value.selectedExpiration
            ivSeries = value.history.compactMap { point in
                guard let iv = point.atmIv, let date = ChartTime.day(point.date ?? "") else { return nil }
                return TimedPoint(date: ChartDomain.normalize(date), value: iv)
            }
        } catch {
            self.error = .from(error)
        }
    }
}

public struct OptionsView: View {
    @State private var model: OptionsModel
    @State private var selectedSymbol: String?
    @State private var expiration = ""
    /// R6.0：期权链默认按行权价升序，列可排序、可拖宽。
    @State private var chainSort: [KeyPathComparator<OptionChainRow>] = [
        KeyPathComparator(\.strike, order: .forward)
    ]

    private var rankingBinding: Binding<String> {
        Binding(
            get: { model.ranking },
            set: { value in updateRanking(value) }
        )
    }

    private func updateRanking(_ value: String) {
        Task { await model.load(ranking: value) }
    }

    private func expirationBinding(_ detail: OptionDetailResponse) -> Binding<String> {
        Binding(
            get: { expiration.isEmpty ? (detail.selectedExpiration ?? detail.expirations.first ?? "") : expiration },
            set: { value in updateExpiration(detail, value) }
        )
    }

    private func updateExpiration(_ detail: OptionDetailResponse, _ value: String) {
        expiration = value
        Task { await model.loadDetail(symbol: detail.symbol, expiration: value) }
    }

    private let rankingLabels: [(key: String, label: String)] = [
        ("activity", "活跃度"), ("activity_surge", "活跃度激增"), ("highest_iv", "最高 IV"),
        ("largest_iv_increase", "IV 上升"), ("lowest_put_call", "最低 Put/Call"),
        ("highest_put_call", "最高 Put/Call"), ("largest_skew", "最大偏斜"),
        ("largest_skew_change", "偏斜变化"), ("largest_oi_change", "OI 变化"),
    ]

    init(model: OptionsModel) {
        _model = State(initialValue: model)
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            HSplitView {
                VStack(spacing: 0) {
                    Picker("排序", selection: rankingBinding) {
                        ForEach(rankingLabels, id: \.key) { Text($0.label).tag($0.key) }
                    }
                    .pickerStyle(.menu).padding(10)
                    List(selection: $selectedSymbol) {
                        let items = model.overview?.rankings[model.ranking] ?? []
                        Section("市场（\(items.count)）") {
                            ForEach(items) { item in
                                optionRow(item).tag(item.symbol)
                            }
                        }
                        let watchlist = model.overview?.watchlist ?? []
                        if !watchlist.isEmpty {
                            Section("自选股（\(watchlist.count)）") {
                                ForEach(watchlist) { item in
                                    optionRow(item).tag(item.symbol)
                                }
                            }
                        }
                    }
                    .onChange(of: selectedSymbol) { _, symbol in
                        if let symbol {
                            expiration = ""
                            Task { await model.loadDetail(symbol: symbol) }
                        }
                    }
                }
                .frame(minWidth: 300, idealWidth: 360)
                ScrollView {
                    detailContent.padding(20)
                }.frame(minWidth: 460)
            }
        }
        .navigationTitle("期权研究")
        .task { await model.load(ranking: "activity") }
        .overlay(alignment: .top) { FeatureErrorBanner(error: model.error).padding() }
        .accessibilityIdentifier("m4.options")
    }

    private func optionRow(_ item: OptionSummaryItem) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(item.symbol).fontWeight(.medium)
                HStack(spacing: 8) {
                    Text(item.label ?? item.assetType ?? "")
                    if let warnings = item.quality?.warnings, !warnings.isEmpty {
                        Label("\(warnings.count) 项警告", systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.orange)
                    }
                }.font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text(item.atmIv.map { "IV \($0.formatted(.number.precision(.fractionLength(1))))%" } ?? "IV 数据不足")
                    .monospacedDigit().font(.callout)
                Text(item.putCallVolumeRatio.map { "P/C \($0.formatted(.number.precision(.fractionLength(2))))" } ?? "P/C 数据不足")
                    .monospacedDigit().font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder
    private var detailContent: some View {
        if let detail = model.detail {
            VStack(alignment: .leading, spacing: 14) {
                M4SectionHeader(detail.symbol, subtitle: "状态 \(detail.status ?? "—") · 提供方 \(detail.provider ?? "—")")
                qualityStrip(detail)
                if !detail.expirations.isEmpty {
                    Picker("到期日", selection: expirationBinding(detail)) {
                        ForEach(detail.expirations, id: \.self) { Text(String($0.prefix(10))).tag($0) }
                    }
                    .pickerStyle(.menu).frame(width: 200)
                }
                if model.ivSeries.count >= 2 {
                    ChartPanel(
                        "ATM IV 历史",
                        unitLabel: "%",
                        source: detail.provider,
                        asOf: model.ivSeries.last.map { String(ChartTime.formatDay($0.date)) },
                        unavailableMessage: nil
                    ) {
                        LineSeriesChart(series: [LineSeries(name: "ATM IV %", paletteIndex: 0, points: model.ivSeries)])
                            .frame(height: 200)
                    }
                } else {
                    Text("IV 历史数据不足（需更多每日快照积累）").font(.callout).foregroundStyle(.secondary)
                }
                chainTable(detail)
                if let limitations = model.overview?.limitations {
                    DisclosureGroup("解读边界") {
                        ForEach(Array(limitations.enumerated()), id: \.offset) { _, item in
                            Text("· " + item).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .font(.headline)
                }
            }.frame(maxWidth: 900, alignment: .leading)
        } else {
            ContentUnavailableView("选择一个标的", systemImage: "function")
        }
    }

    @ViewBuilder
    private func qualityStrip(_ detail: OptionDetailResponse) -> some View {
        if let quality = detail.quality {
            HStack(spacing: 14) {
                SemanticStatusLabel(
                    quality.level ?? "—",
                    status: quality.level == "HIGH" ? .live : quality.level == "MEDIUM" ? .stale : .warning
                )
                if let score = quality.score {
                    LabeledContent("质量分", value: score.formatted(.number.precision(.fractionLength(2))))
                }
                if let coverage = quality.coverage {
                    LabeledContent("覆盖率", value: coverage.formatted(.percent.precision(.fractionLength(0))))
                }
            }.font(.callout)
        }
    }

    private func chainTable(_ detail: OptionDetailResponse) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            M4SectionHeader("期权链", subtitle: "到期 \(detail.selectedExpiration.map { String($0.prefix(10)) } ?? "—") · \(detail.chain.count) 条")
            Table(sortedChain, sortOrder: $chainSort) {
                TableColumn("类型") { item in
                    Text(item.optionType == "call" ? "Call" : "Put")
                        .foregroundStyle(item.optionType == "call" ? StockMonitorChartPalette.positive : StockMonitorChartPalette.negative)
                }
                .width(min: 60, ideal: 70)
                TableColumn("行权价", sortUsing: KeyPathComparator(\OptionChainRow.strike)) { item in
                    NumericTableCell(value: item.strike, digits: 1)
                }
                .width(min: 80, ideal: 95)
                TableColumn("最新") { item in optionalPrice(item.last) }
                .width(min: 80, ideal: 95)
                TableColumn("买价") { item in optionalPrice(item.bid) }
                .width(min: 80, ideal: 90)
                TableColumn("卖价") { item in optionalPrice(item.ask) }
                .width(min: 80, ideal: 90)
                TableColumn("成交量", sortUsing: KeyPathComparator(\OptionChainRow.volume, order: .reverse)) { item in
                    NumericTableCell(value: item.volume, digits: 0)
                }
                .width(min: 70, ideal: 85)
                TableColumn("未平仓", sortUsing: KeyPathComparator(\OptionChainRow.openInterest, order: .reverse)) { item in
                    NumericTableCell(value: item.openInterest, digits: 0)
                }
                .width(min: 70, ideal: 85)
                TableColumn("IV", sortUsing: KeyPathComparator(\OptionChainRow.impliedVolatility, order: .reverse)) { item in
                    NumericTableCell(percent: item.impliedVolatility)
                }
                .width(min: 70, ideal: 85)
                TableColumn("Delta", sortUsing: KeyPathComparator(\OptionChainRow.delta)) { item in
                    NumericTableCell(value: item.delta, digits: 2)
                }
                .width(min: 70, ideal: 85)
            }
            .frame(minHeight: 260)
            .accessibilityIdentifier("r6.options.chain-table")
            if detail.chain.count > 120 {
                TableTruncationFooter(shown: 120, total: detail.chain.count)
            }
        }
    }

    private var sortedChain: [OptionChainRow] {
        Array(model.detail?.chain.prefix(120) ?? []).sorted(using: chainSort)
    }

    private func optionalPrice(_ value: Double?) -> Text {
        Text(value.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
            .monospacedDigit()
            .foregroundStyle(value == nil ? .secondary : .primary)
    }
}
