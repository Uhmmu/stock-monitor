import StockMonitorDesign
import SwiftUI

// MARK: - Goal M4.0 路由入口

public struct GoalM4RouteView: View {
    public let route: AppRoute
    @Bindable public var navigation: AppNavigationModel
    public let service: ResearchWorkspaceService
    public let openStock: (String) -> Void
    @State private var tickerContext = CompanyTickerContext()

    public init(route: AppRoute, navigation: AppNavigationModel, service: ResearchWorkspaceService, openStock: @escaping (String) -> Void) {
        self.route = route
        self.navigation = navigation
        self.service = service
        self.openStock = openStock
    }

    public var body: some View {
        switch route {
        case .fundamentals:
            FundamentalsView(model: FundamentalsModel(service: service), tickerContext: tickerContext, symbol: activeSymbol)
        case .financials:
            FinancialsView(model: FinancialsModel(service: service), tickerContext: tickerContext, symbol: activeSymbol)
        case .valuation:
            ValuationView(model: ValuationModel(service: service), tickerContext: tickerContext, symbol: activeSymbol)
        case .compare:
            CompareView(model: CompareModel(service: service), openStock: openStock)
        case .sec:
            SecView(model: SecModel(service: service), tickerContext: tickerContext, symbol: activeSymbol)
        case .ownership:
            OwnershipView(
                model: OwnershipModel(service: service),
                tickerContext: tickerContext,
                symbol: navigation.selectedSymbol
            )
        case .congress:
            CongressView(model: CongressModel(service: service), openStock: openStock)
        case .technical:
            TechnicalAnalysisView(model: TechnicalAnalysisModel(service: service), tickerContext: tickerContext, symbol: activeSymbol)
        case .macro:
            MacroView(model: MacroModel(service: service))
        case .industry:
            IndustryPulseView(model: IndustryPulseModel(service: service))
        case .options:
            OptionsView(model: OptionsModel(service: service))
        case .mood:
            MoodView(model: MoodModel(service: service))
        case .moodLab:
            MoodLabView(model: MoodLabModel(service: service))
        default:
            EmptyView()
        }
    }

    private var activeSymbol: String {
        navigation.selectedSymbol ?? "AAPL"
    }
}

// MARK: - 共享小组件

struct M4SectionHeader: View {
    let title: String
    let subtitle: String?

    init(_ title: String, subtitle: String? = nil) {
        self.title = title
        self.subtitle = subtitle
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.title2.bold())
            if let subtitle {
                Text(subtitle).font(.callout).foregroundStyle(.secondary)
            }
        }
    }
}

/// Debug fallback（R2.1 后主路径禁止使用）：按字母序平铺 JSON 证据。
/// 正常页面一律使用 `SemanticEvidenceView`；新代码只在明确的诊断入口引用本组件。
struct JSONEvidenceView: View {
    let value: JSONValue?

    var body: some View {
        if let value {
            let entries = flattened(value).prefix(24)
            if entries.isEmpty {
                Text("服务端未返回该区块内容").font(.callout).foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(entries, id: \.0) { label, text in
                        HStack(alignment: .firstTextBaseline) {
                            Text(label).foregroundStyle(.secondary)
                            Spacer(minLength: 12)
                            Text(text).monospacedDigit().multilineTextAlignment(.trailing)
                        }.font(.callout)
                    }
                }
            }
        } else {
            Text("数据不足").font(.callout).foregroundStyle(.secondary)
        }
    }

    private func flattened(_ value: JSONValue, prefix: String = "") -> [(String, String)] {
        switch value {
        case let .object(fields):
            fields.sorted { $0.key < $1.key }.flatMap { key, child in
                flattened(child, prefix: prefix.isEmpty ? key : "\(prefix) · \(key)")
            }
        case .array:
            [(prefix, value.displayText)]
        default:
            [(prefix, value.displayText)]
        }
    }
}

struct ConfirmExternalLinkButton: View {
    let url: URL
    @State private var confirming = false
    @Environment(\.openURL) private var openURL

    var body: some View {
        Button("原文", systemImage: "arrow.up.right.square") { confirming = true }
            .buttonStyle(.borderless)
            .confirmationDialog("打开外部网站？", isPresented: $confirming) {
                Button("打开 \(url.host ?? url.absoluteString)") { openURL(url) }
                Button("取消", role: .cancel) {}
            } message: { Text(url.host ?? url.absoluteString) }
    }
}

// MARK: - 基本面

@MainActor
@Observable
public final class FundamentalsModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var response: FundamentalsResponse?
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func load(symbol: String) async {
        state = response == nil ? .loading : .refreshing
        do {
            response = try await service.fundamentals(ticker: symbol)
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = response == nil ? .error : .stale
        }
    }
}

public struct FundamentalsView: View {
    @State private var model: FundamentalsModel
    @State private var symbol = ""
    let initialSymbol: String?
    let tickerContext: CompanyTickerContext

    init(model: FundamentalsModel, tickerContext: CompanyTickerContext, symbol: String?) {
        _model = State(initialValue: model)
        _symbol = State(initialValue: symbol ?? "")
        initialSymbol = symbol
        self.tickerContext = tickerContext
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack {
                        M4SectionHeader("基本面指标", subtitle: "Yahoo 为主数据源，Finnhub 仅作可选补充")
                        Spacer()
                        CompanySymbolBar(
                            context: tickerContext,
                            service: model.service,
                            symbol: $symbol,
                            initialSymbol: initialSymbol
                        ) { value in
                            await model.load(symbol: value)
                        }
                    }
                    if let response = model.response {
                        headerStrip(response)
                        metricsGrid(response.metrics)
                        if let rating = response.rating {
                            ratingSection(rating)
                        } else {
                            Text("评级数据不足").foregroundStyle(.secondary)
                        }
                        sourceStrip(response.sourceSupport)
                    }
                }
                .padding(24)
            }
            .refreshable { await model.load(symbol: symbol) }
        }
        .navigationTitle("基本面")
        .task {
            guard let resolved = await tickerContext.resolveAfterLoad(service: model.service, preferred: initialSymbol) else { return }
            symbol = resolved
            await model.load(symbol: resolved)
        }
        .onChange(of: initialSymbol) { _, value in
            guard let value, tickerContext.symbols.contains(value) else { return }
            symbol = value
            Task { await model.load(symbol: value) }
        }
        .overlay(alignment: .top) { FeatureErrorBanner(error: model.error).padding() }
        .accessibilityIdentifier("m4.fundamentals")
    }

    private func headerStrip(_ response: FundamentalsResponse) -> some View {
        HStack(spacing: 16) {
            LabeledContent("证券", value: response.ticker)
            LabeledContent("查询时间", value: String(response.asOf.prefix(19).replacingOccurrences(of: "T", with: " ")))
            LabeledContent("模式", value: response.dataMode)
        }
        .font(.callout)
    }

    private func metricsGrid(_ metrics: [FundamentalsMetric]) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 220))], spacing: 10) {
            ForEach(metrics) { metric in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(metric.label).font(.callout)
                        Spacer()
                        Text(metric.source ?? "—").font(.caption2).foregroundStyle(.secondary)
                    }
                    Text(metric.value.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
                        .font(.title3.monospacedDigit().weight(.semibold))
                        .foregroundStyle(metric.value == nil ? .secondary : .primary)
                }
                .padding(12)
                .background(.background.secondary, in: .rect(cornerRadius: 10))
            }
        }
    }

    private func ratingSection(_ rating: AnalystRating) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            M4SectionHeader("分析师评级", subtitle: rating.period.map { "周期 \($0)" })
            HStack(spacing: 18) {
                LabeledContent("强力买入", value: "\(rating.strongBuy)")
                LabeledContent("买入", value: "\(rating.buy)")
                LabeledContent("持有", value: "\(rating.hold)")
                LabeledContent("卖出", value: "\(rating.sell)")
                LabeledContent("强力卖出", value: "\(rating.strongSell)")
            }
            .monospacedDigit()
        }
        .padding(14)
        .background(.background.secondary, in: .rect(cornerRadius: 10))
    }

    private func sourceStrip(_ support: SourceSupport) -> some View {
        HStack(spacing: 12) {
            SemanticStatusLabel("Yahoo", status: support.yahoo ? .live : .unavailable)
            SemanticStatusLabel("Finnhub 补充", status: support.finnhub ? .live : .unavailable)
            Text("百分比与市值单位由服务端归一化，客户端不重复换算").font(.caption).foregroundStyle(.secondary)
        }
    }
}

// MARK: - 财务报表

@MainActor
@Observable
public final class FinancialsModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var quarterly: [QuarterlyFinancialRow] = []
    public private(set) var statements: FinancialStatementPage?
    public private(set) var frequency = "annual"
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func load(symbol: String, frequency: String) async {
        self.frequency = frequency
        state = quarterly.isEmpty && statements == nil ? .loading : .refreshing
        do {
            async let quarterlyRows = service.financials(ticker: symbol)
            async let statementPage = service.financialStatements(ticker: symbol, frequency: frequency)
            let values = try await (quarterlyRows, statementPage)
            quarterly = values.0
            statements = values.1
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = quarterly.isEmpty ? .error : .stale
        }
    }
}

public struct FinancialsView: View {
    @State private var model: FinancialsModel
    @State private var symbol = ""
    @State private var frequency = "annual"
    @State private var statementKind = StatementKind.income
    let initialSymbol: String?

    enum StatementKind: String, CaseIterable, Identifiable {
        case income = "利润表"
        case balance = "资产负债表"
        case cashFlow = "现金流量表"
        var id: Self {
            self
        }
    }

    let tickerContext: CompanyTickerContext

    init(model: FinancialsModel, tickerContext: CompanyTickerContext, symbol: String?) {
        _model = State(initialValue: model)
        _symbol = State(initialValue: symbol ?? "")
        initialSymbol = symbol
        self.tickerContext = tickerContext
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack {
                        M4SectionHeader("财务数据", subtitle: "季度指标来自最新四期；三表为服务端已存 Yahoo 快照")
                        Spacer()
                        CompanySymbolBar(
                            context: tickerContext,
                            service: model.service,
                            symbol: $symbol,
                            initialSymbol: initialSymbol
                        ) { value in
                            await model.load(symbol: value, frequency: frequency)
                        }
                    }
                    quarterlyTable
                    Divider()
                    HStack {
                        Picker("频率", selection: $frequency) {
                            Text("年度").tag("annual")
                            Text("季度").tag("quarterly")
                        }
                        .pickerStyle(.segmented)
                        .frame(width: 180)
                        .onChange(of: frequency) { _, value in
                            Task { await model.load(symbol: symbol, frequency: value) }
                        }
                        Spacer()
                        if let syncedAt = model.statements?.rows.first?.syncedAt {
                            Text("同步于 \(String(syncedAt.prefix(10)))").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Picker("报表", selection: $statementKind) {
                        ForEach(StatementKind.allCases) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 320)
                    statementSections
                }
                .padding(24)
            }
            .refreshable { await model.load(symbol: symbol, frequency: frequency) }
        }
        .navigationTitle("财务报表")
        .task {
            guard let resolved = await tickerContext.resolveAfterLoad(service: model.service, preferred: initialSymbol) else { return }
            symbol = resolved
            await model.load(symbol: resolved, frequency: frequency)
        }
        .onChange(of: initialSymbol) { _, value in
            guard let value, tickerContext.symbols.contains(value) else { return }
            symbol = value
            Task { await model.load(symbol: value, frequency: frequency) }
        }
        .overlay(alignment: .top) { FeatureErrorBanner(error: model.error).padding() }
        .accessibilityIdentifier("m4.financials")
    }

    private var quarterlyTable: some View {
        VStack(alignment: .leading, spacing: 8) {
            M4SectionHeader("季度关键指标")
            Table(model.quarterly) {
                TableColumn("财季") { row in
                    Text("\(row.fiscalYear.map(String.init) ?? "—") \(row.fiscalPeriod ?? "")")
                }
                TableColumn("期末") { row in Text(row.periodEnd ?? "—") }
                TableColumn("营收") { row in optionalNumber(row.revenue, digits: 0) }
                TableColumn("EPS") { row in optionalNumber(row.eps, digits: 2) }
                TableColumn("净利润") { row in optionalNumber(row.netIncome, digits: 0) }
                TableColumn("毛利率") { row in optionalPercent(row.grossMargin) }
                TableColumn("净利率") { row in optionalPercent(row.netMargin) }
                TableColumn("FCF") { row in optionalNumber(row.freeCashFlow, digits: 0) }
                TableColumn("来源") { row in Text(row.source ?? "数据不足") }
            }
            .frame(minHeight: 150)
        }
    }

    @ViewBuilder
    private var statementSections: some View {
        if let page = model.statements {
            if page.rows.isEmpty {
                Text("该频率暂无报表快照，等待服务端同步").foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(page.rows) { row in
                        DisclosureGroup("\(row.fiscalYear ?? 0) \(row.fiscalPeriod ?? "")（\(row.periodEnd ?? "—")）") {
                            SemanticEvidenceView(value: statementValue(row), domain: .financials)
                                .padding(.top, 8)
                        }
                        .font(.headline)
                    }
                    Text("报表条目由服务端 Yahoo 快照原样呈现，缺失项显示“数据不足”。")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func statementValue(_ row: FinancialStatementRow) -> JSONValue? {
        switch statementKind {
        case .income: row.incomeStatement
        case .balance: row.balanceSheet
        case .cashFlow: row.cashFlow
        }
    }

    private func optionalNumber(_ value: Double?, digits: Int) -> Text {
        Text(value.map { $0.formatted(.number.precision(.fractionLength(digits))) } ?? "数据不足")
            .monospacedDigit()
            .foregroundStyle(value == nil ? .secondary : .primary)
    }

    private func optionalPercent(_ value: Double?) -> Text {
        optionalNumber(value, digits: 1)
    }
}

// MARK: - 估值（cross-model + Historical P/E + Graham）

@MainActor
@Observable
public final class ValuationModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var snapshot: ValuationCrossModel?
    public private(set) var metrics: [CrossModelMetric] = []
    public private(set) var signals: [CrossModelSignal] = []
    public private(set) var consensus: CrossModelConsensus?
    public private(set) var refreshQueued = false
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func load(symbol: String) async {
        state = snapshot == nil ? .loading : .refreshing
        do {
            let value = try await service.crossModel(ticker: symbol)
            snapshot = value
            metrics = (try? value.fields["valuation"]?.decode(as: [CrossModelMetric].self)) ?? []
            signals = (try? value.fields["model_signals"]?.decode(as: [CrossModelSignal].self)) ?? []
            consensus = try? value.fields["consensus"]?.decode(as: CrossModelConsensus.self)
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = snapshot == nil ? .error : .stale
        }
    }

    public func refresh(symbol: String) async {
        do {
            _ = try await service.refreshCrossModel(ticker: symbol)
            refreshQueued = true
        } catch {
            self.error = .from(error)
        }
    }
}

public struct ValuationView: View {
    @State private var model: ValuationModel
    @State private var symbol = ""
    @State private var showingHistory = false
    @State private var showingGraham = false
    let initialSymbol: String?
    let tickerContext: CompanyTickerContext

    init(model: ValuationModel, tickerContext: CompanyTickerContext, symbol: String?) {
        _model = State(initialValue: model)
        _symbol = State(initialValue: symbol ?? "")
        initialSymbol = symbol
        self.tickerContext = tickerContext
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack {
                        M4SectionHeader("多模型估值", subtitle: "读取每日估值快照；页面不在请求期间实时拉取外部数据")
                        Spacer()
                        CompanySymbolBar(
                            context: tickerContext,
                            service: model.service,
                            symbol: $symbol,
                            initialSymbol: initialSymbol
                        ) { value in
                            await model.load(symbol: value)
                        }
                        Button("历史 P/E") { showingHistory = true }
                        Button("Graham 调整") { showingGraham = true }
                    }
                    if model.refreshQueued {
                        Label("已排队刷新，稍后重新查询即可看到新快照", systemImage: "clock.arrow.circlepath")
                            .font(.callout).foregroundStyle(.secondary)
                    }
                    if let snapshot = model.snapshot {
                        snapshotHeader(snapshot)
                        consensusSection
                        signalsSection
                        metricsSection
                        grahamSection(snapshot)
                        extraSections(snapshot)
                        Text("客户端不重算任何估值模型；所有数值、单位与来源以服务端快照为准。")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                .padding(24)
            }
            .refreshable { await model.load(symbol: symbol) }
        }
        .navigationTitle("估值")
        .task {
            guard let resolved = await tickerContext.resolveAfterLoad(service: model.service, preferred: initialSymbol) else { return }
            symbol = resolved
            await model.load(symbol: resolved)
        }
        .onChange(of: initialSymbol) { _, value in
            guard let value, tickerContext.symbols.contains(value) else { return }
            symbol = value
            Task { await model.load(symbol: value) }
        }
        .overlay(alignment: .top) { FeatureErrorBanner(error: model.error).padding() }
        .sheet(isPresented: $showingHistory) {
            HistoricalPESheet(service: model.service, symbol: symbol).frame(minWidth: 720, minHeight: 520)
        }
        .sheet(isPresented: $showingGraham) {
            GrahamLabSheet(service: model.service, snapshot: model.snapshot, symbol: symbol)
                .frame(minWidth: 560, minHeight: 480)
        }
        .accessibilityIdentifier("m4.valuation")
    }

    private func snapshotHeader(_ snapshot: ValuationCrossModel) -> some View {
        HStack(spacing: 16) {
            LabeledContent("快照日期", value: snapshot.snapshotDate ?? "数据不足")
            if let generatedAt = snapshot.generatedAt {
                LabeledContent("生成时间", value: String(generatedAt.prefix(19).replacingOccurrences(of: "T", with: " ")))
            }
            if let aiModel = snapshot.aiModel {
                LabeledContent("AI 模型", value: aiModel)
            }
        }
        .font(.callout)
    }

    @ViewBuilder
    private var consensusSection: some View {
        if let consensus = model.consensus {
            VStack(alignment: .leading, spacing: 8) {
                M4SectionHeader("模型共识")
                HStack(spacing: 18) {
                    LabeledContent("共识公允价值") {
                        Text(consensus.value.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
                            .monospacedDigit()
                    }
                    LabeledContent("快照现价") {
                        Text(consensus.current.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
                            .monospacedDigit()
                    }
                }
                if let items = consensus.items, !items.isEmpty {
                    HStack(spacing: 14) {
                        ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                            LabeledContent(item.label ?? item.key ?? "—") {
                                Text(item.value.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
                                    .monospacedDigit()
                            }
                        }
                    }
                    .font(.callout)
                }
            }
            .padding(14)
            .background(.background.secondary, in: .rect(cornerRadius: 10))
        }
    }

    @ViewBuilder
    private var signalsSection: some View {
        if !model.signals.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                M4SectionHeader("模型信号", subtitle: model.snapshot?.fields["model_conflict"]?.numberValue == 1 ? "模型之间存在分歧" : nil)
                ForEach(model.signals) { signal in
                    HStack {
                        Text(signal.label ?? signal.key)
                        Text(stars(signal.stars)).foregroundStyle(.yellow)
                        Spacer()
                        Text(signal.verdict ?? "数据不足").fontWeight(.medium)
                    }.font(.callout)
                }
            }
            .padding(14)
            .background(.background.secondary, in: .rect(cornerRadius: 10))
        }
    }

    private func stars(_ count: Int?) -> String {
        guard let count, count > 0 else { return "—" }
        return String(repeating: "★", count: count)
    }

    @ViewBuilder
    private var metricsSection: some View {
        if !model.metrics.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                M4SectionHeader("估值指标与同行对比")
                Table(model.metrics) {
                    TableColumn("指标") { row in Text(row.label ?? row.key) }
                    TableColumn("数值") { row in
                        Text(row.value.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
                            .monospacedDigit()
                            .foregroundStyle(row.value == nil ? .secondary : .primary)
                    }
                    TableColumn("单位") { row in Text(row.unit ?? "—") }
                    TableColumn("同行中位") { row in
                        Text(row.peerMedian.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
                            .monospacedDigit()
                            .foregroundStyle(row.peerMedian == nil ? .secondary : .primary)
                    }
                    TableColumn("相对同行") { row in
                        Text(row.comparison ?? (row.peerDeltaPercent.map { "\($0.formatted(.number.precision(.fractionLength(1))))%" } ?? "数据不足"))
                            .monospacedDigit()
                            .foregroundStyle(row.comparison == nil ? .secondary : .primary)
                    }
                }
                .frame(minHeight: 160)
            }
        }
    }

    @ViewBuilder
    private func grahamSection(_ snapshot: ValuationCrossModel) -> some View {
        if let graham = snapshot.fields["graham"] {
            DisclosureGroup("Graham 分析") {
                SemanticEvidenceView(value: graham, domain: .valuation).padding(.top, 8)
            }
            .font(.headline)
        }
    }

    @ViewBuilder
    private func extraSections(_ snapshot: ValuationCrossModel) -> some View {
        let known: Set = ["valuation", "model_signals", "consensus", "graham", "ticker", "company", "as_of"]
        let extras = snapshot.fields.keys.filter { !known.contains($0) }.sorted()
        if !extras.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                M4SectionHeader("快照其它字段", subtitle: "原样呈现服务端证据")
                ForEach(extras, id: \.self) { key in
                    DisclosureGroup(displayKey(key)) {
                        SemanticEvidenceView(value: snapshot.fields[key], domain: .valuation).padding(.top, 6)
                    }
                    .font(.callout)
                }
            }
        }
    }

    private func displayKey(_ key: String) -> String {
        key.replacingOccurrences(of: "_", with: " ").capitalized
    }
}

@MainActor
@Observable
public final class HistoricalPEModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var rangeKey = "5y"
    public private(set) var response: ValuationHistoryResponse?
    public private(set) var series: [TimedPoint] = []
    public private(set) var error: M3FeatureError?
    private let service: ResearchWorkspaceService

    init(service: ResearchWorkspaceService) {
        self.service = service
    }

    func load(symbol: String, range: String) async {
        rangeKey = range
        state = response == nil ? .loading : .refreshing
        do {
            let value = try await service.valuationHistory(ticker: symbol, range: range)
            response = value
            series = value.series.compactMap { point in
                guard let pe = point.pe, let date = ChartTime.day(point.date) else { return nil }
                return TimedPoint(date: ChartDomain.normalize(date), value: pe)
            }
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = response == nil ? .error : .stale
        }
    }
}

struct HistoricalPESheet: View {
    let service: ResearchWorkspaceService
    let symbol: String
    @State private var model: HistoricalPEModel?
    @State private var range = "5y"
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Group {
                if let model {
                    HistoricalPEContent(model: model, range: $range, symbol: symbol)
                } else {
                    ContentUnavailableView("加载中", systemImage: "chart.xyaxis.line")
                }
            }
            .navigationTitle("\(symbol) 历史 P/E")
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() } } }
        }
        .task {
            if model == nil {
                let value = HistoricalPEModel(service: service)
                model = value
                await value.load(symbol: symbol, range: range)
            }
        }
        .onChange(of: range) { _, value in
            guard let model else { return }
            Task { await model.load(symbol: symbol, range: value) }
        }
    }
}

private struct HistoricalPEContent: View {
    @Bindable var model: HistoricalPEModel
    @Binding var range: String
    let symbol: String

    var body: some View {
        ResourceStateView(state: model.state) {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    FeatureErrorBanner(error: model.error)
                    Picker("区间", selection: $range) {
                        Text("3 年").tag("3y")
                        Text("5 年").tag("5y")
                        Text("10 年").tag("10y")
                        Text("最大").tag("max")
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 320)
                    if let response = model.response {
                        if response.status == "syncing" {
                            Label("EPS 事实尚未采集，已排队同步；稍后重试。", systemImage: "clock.arrow.circlepath")
                                .foregroundStyle(.secondary)
                        } else if model.series.isEmpty {
                            Text("数据不足：该证券暂无有效 P/E 序列（如 TTM 为负或国际代码无 SEC 数据）。")
                                .foregroundStyle(.secondary)
                        } else {
                            statsRow(response)
                            LineSeriesChart(
                                series: [LineSeries(name: "P/E", color: .accentColor, points: model.series)],
                                referenceLines: referenceLines(response)
                            )
                            .frame(height: 280)
                            Text("TTM 为当时已公开的最近四个连续财季之和；亏损期（TTM≤0）不出现在序列中。")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                .padding(20)
            }
        }
    }

    private func statsRow(_ response: ValuationHistoryResponse) -> some View {
        HStack(spacing: 18) {
            LabeledContent("当前 P/E") {
                Text(response.current?.pe.map { $0.formatted(.number.precision(.fractionLength(1))) } ?? "N/M")
                    .monospacedDigit()
            }
            LabeledContent("中位") { optionalStat(response.statistics?.median) }
            LabeledContent("P25") { optionalStat(response.statistics?.p25) }
            LabeledContent("P75") { optionalStat(response.statistics?.p75) }
            if let percentile = response.statistics?.percentile {
                LabeledContent("分位") {
                    Text(percentile.formatted(.number.precision(.fractionLength(0))) + "%").monospacedDigit()
                }
            }
        }
        .font(.callout)
    }

    private func optionalStat(_ value: Double?) -> Text {
        Text(value.map { $0.formatted(.number.precision(.fractionLength(1))) } ?? "数据不足")
            .monospacedDigit()
            .foregroundStyle(value == nil ? .secondary : .primary)
    }

    private func referenceLines(_ response: ValuationHistoryResponse) -> [(label: String, value: Double)] {
        guard let stats = response.statistics else { return [] }
        return [("中位", stats.median), ("P25", stats.p25), ("P75", stats.p75)]
    }
}

@MainActor
@Observable
public final class GrahamLabModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var result: JSONValue?
    public private(set) var error: M3FeatureError?
    private let service: ResearchWorkspaceService

    init(service: ResearchWorkspaceService) {
        self.service = service
    }

    func recalculate(symbol: String, growthRate: Double?, aaaYield: Double?, normalizedEps: Double?) async {
        state = .loading
        do {
            result = try await service.grahamOverrides(
                ticker: symbol,
                request: GrahamOverrideRequest(growthRate: growthRate, aaaYield: aaaYield, normalizedEps: normalizedEps)
            )
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = result == nil ? .error : .stale
        }
    }
}

struct GrahamLabSheet: View {
    let service: ResearchWorkspaceService
    let snapshot: ValuationCrossModel?
    let symbol: String
    @State private var growthRate = ""
    @State private var aaaYield = ""
    @State private var normalizedEps = ""
    @State private var model: GrahamLabModel?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("原始 Graham 输入") {
                    SemanticEvidenceView(value: snapshot?.fields["graham"]?.objectValue["inputs"], domain: .valuation)
                }
                Section("覆盖输入（留空则沿用快照值）") {
                    TextField("增长率 %（如 8.5）", text: $growthRate)
                    TextField("AAA 企业债收益率 %（如 4.4）", text: $aaaYield)
                    TextField("归一化 EPS（如 6.2）", text: $normalizedEps)
                    Text("重算只使用最新快照输入，不访问第三方，也不覆盖原始快照。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section("重算结果") {
                    FeatureErrorBanner(error: model?.error)
                    SemanticEvidenceView(value: model?.result, domain: .valuation)
                }
            }
            .formStyle(.grouped)
            .navigationTitle("\(symbol) Graham 调整")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("重算") {
                        Task {
                            if model == nil {
                                model = GrahamLabModel(service: service)
                            }
                            await model?.recalculate(
                                symbol: symbol,
                                growthRate: Double(growthRate),
                                aaaYield: Double(aaaYield),
                                normalizedEps: Double(normalizedEps)
                            )
                        }
                    }
                }
            }
        }
    }
}
