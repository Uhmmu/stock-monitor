import StockMonitorDesign
import SwiftUI

// MARK: - SEC 数据（filings / events / financials / insider / 13F）

@MainActor
@Observable
public final class SecModel {
    public enum Tab: String, CaseIterable, Identifiable {
        case filings = "文件"
        case events = "事件"
        case financials = "SEC 财务"
        case insider = "内部人交易"
        case holdings13f = "13F 持仓"
        public var id: Self {
            self
        }
    }

    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var tab: Tab = .filings
    public private(set) var filings: [SecFilingItem] = []
    public private(set) var events: [SecEventItem] = []
    public private(set) var financials: [SecFinancialRow] = []
    public private(set) var insider: [SecInsiderItem] = []
    public private(set) var holdings: Sec13FPage?
    public private(set) var refreshQueued = false
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func select(_ tab: Tab) {
        self.tab = tab
    }

    public func load(symbol: String) async {
        state = filings.isEmpty && events.isEmpty && financials.isEmpty && insider.isEmpty && holdings == nil ? .loading : .refreshing
        do {
            async let filings = service.secFilings(ticker: symbol)
            async let events = service.secEvents(ticker: symbol)
            async let financials = service.secFinancials(ticker: symbol)
            async let insider = service.secInsider(ticker: symbol)
            async let holdings = service.sec13F(ticker: symbol)
            let values = try await (filings, events, financials, insider, holdings)
            self.filings = values.0
            self.events = values.1
            self.financials = values.2
            self.insider = values.3
            self.holdings = values.4
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = filings.isEmpty ? .error : .stale
        }
    }

    public func refresh(symbol: String) async {
        do {
            _ = try await service.refreshSecFilings(ticker: symbol)
            refreshQueued = true
        } catch {
            self.error = .from(error)
        }
    }
}

public struct SecView: View {
    @State private var model: SecModel
    @State private var symbol = ""
    /// R6.0：默认排序——文件/内部人按日期降序、SEC 财务按财年降序、13F 按市值降序。
    @State private var filingsSort: [KeyPathComparator<SecFilingItem>] = [
        KeyPathComparator(\.filingDate, order: .reverse),
    ]
    @State private var financialsSort: [KeyPathComparator<SecFinancialRow>] = [
        KeyPathComparator(\.fiscalYear, order: .reverse),
    ]
    @State private var insiderSort: [KeyPathComparator<SecInsiderItem>] = [
        KeyPathComparator(\.transactionDate, order: .reverse),
    ]
    @State private var holdingsSort: [KeyPathComparator<Sec13FHoldingItem>] = [
        KeyPathComparator(\.valueUsd, order: .reverse),
    ]
    let initialSymbol: String?
    let tickerContext: CompanyTickerContext
    let companySummary: CompanySummaryModel

    init(model: SecModel, tickerContext: CompanyTickerContext, companySummary: CompanySummaryModel, symbol: String?) {
        _model = State(initialValue: model)
        _symbol = State(initialValue: symbol ?? "")
        initialSymbol = symbol
        self.tickerContext = tickerContext
        self.companySummary = companySummary
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            PageScaffold(width: StockMonitorContentWidth.wide) {
                PageHeader("SEC 官方数据", summary: "结构化 filing item 映射；原文与 LLM 不参与事件判定。") {
                    HStack(spacing: StockMonitorSpacing.small) {
                        CompanySymbolBar(
                            context: tickerContext,
                            service: model.service,
                            symbol: $symbol,
                            initialSymbol: initialSymbol
                        ) { value in
                            await model.load(symbol: value)
                        }
                        Button("刷新") { Task { await model.refresh(symbol: symbol) } }
                    }
                }
            } content: {
                CompanyHeaderView(summary: companySummary.summary(for: symbol))
                Picker("数据集", selection: Binding(
                    get: { model.tab },
                    set: { model.select($0) }
                )) {
                    ForEach(SecModel.Tab.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .frame(width: 360)
                FeatureErrorBanner(error: model.error)
                if model.refreshQueued {
                    Label("已排队重新采集，稍后查询可见。", systemImage: "clock.arrow.circlepath")
                        .stockMonitorTypography(.metadata)
                }
                tabContent
            }
        }
        .navigationTitle("SEC")
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
        .accessibilityIdentifier("m4.sec")
    }

    @ViewBuilder
    private var tabContent: some View {
        switch model.tab {
        case .filings: filingsTable
        case .events: eventsTable
        case .financials: financialsTable
        case .insider: insiderTable
        case .holdings13f: holdingsTable
        }
    }

    private var filingsTable: some View {
        Table(model.filings, sortOrder: $filingsSort) {
            TableColumn("日期", sortUsing: KeyPathComparator(\SecFilingItem.filingDate, order: .reverse)) { row in
                Text(row.filingDate ?? "数据不足")
            }
            .width(min: 100, ideal: 120)
            TableColumn("表格") { row in
                Text(row.form).fontWeight(.semibold)
            }
            .width(min: 70, ideal: 90)
            TableColumn("说明") { row in Text(row.formLabel ?? "—") }
                .width(min: 180, ideal: 260)
            TableColumn("事件标签") { row in
                Text(row.eventLabels.joined(separator: "、")).foregroundStyle(row.eventLabels.isEmpty ? .secondary : .primary)
            }
            .width(min: 140, ideal: 200)
            TableColumn("优先级") { row in
                Text(row.priority.map(String.init) ?? "—")
            }
            .width(min: 60, ideal: 80)
            TableColumn("链接") { row in
                if let raw = row.filingUrl, let url = URL(string: raw) {
                    ConfirmExternalLinkButton(url: url)
                } else {
                    Text("数据不足").foregroundStyle(.secondary)
                }
            }
            .width(min: 70, ideal: 90)
        }
        .frame(minHeight: 320)
        .accessibilityIdentifier("r6.sec.filings-table")
    }

    /// R4.2：SEC 事件用 timeline + 证据链接，不再是无序平铺表格。
    @ViewBuilder
    private var eventsTable: some View {
        if model.events.isEmpty {
            EmptyState("暂无 SEC 事件", systemImage: "doc.text.magnifyingglass", description: "近两年没有映射到结构化 filing item 的事件。")
        } else {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(model.events) { event in
                    SecEventTimelineRow(event: event)
                    Divider()
                }
            }
            .accessibilityIdentifier("r4.sec.events")
        }
    }

    private var financialsTable: some View {
        Table(model.financials, sortOrder: $financialsSort) {
            TableColumn("财年", sortUsing: KeyPathComparator(\SecFinancialRow.fiscalYear, order: .reverse)) { row in
                Text(row.fiscalYear.map(String.init) ?? "—")
            }
            .width(min: 60, ideal: 70)
            TableColumn("期间") { row in Text(row.fiscalPeriod ?? "—") }
                .width(min: 60, ideal: 70)
            TableColumn("期末") { row in Text(row.periodEnd ?? "—") }
                .width(min: 100, ideal: 110)
            TableColumn("营收", sortUsing: KeyPathComparator(\SecFinancialRow.revenue, order: .reverse)) { row in
                optionalMoney(row.revenue)
            }
            .width(min: 100, ideal: 120)
            TableColumn("净利润", sortUsing: KeyPathComparator(\SecFinancialRow.netIncome, order: .reverse)) { row in
                optionalMoney(row.netIncome)
            }
            .width(min: 100, ideal: 120)
            TableColumn("EPS 稀释", sortUsing: KeyPathComparator(\SecFinancialRow.epsDiluted, order: .reverse)) { row in
                optionalNumber(row.epsDiluted, 2)
            }
            .width(min: 80, ideal: 100)
            TableColumn("现金", sortUsing: KeyPathComparator(\SecFinancialRow.cashAndEquivalents, order: .reverse)) { row in
                optionalMoney(row.cashAndEquivalents)
            }
            .width(min: 100, ideal: 120)
            TableColumn("总债务", sortUsing: KeyPathComparator(\SecFinancialRow.totalDebt, order: .reverse)) { row in
                optionalMoney(row.totalDebt)
            }
            .width(min: 100, ideal: 120)
            TableColumn("经营现金流", sortUsing: KeyPathComparator(\SecFinancialRow.operatingCashFlow, order: .reverse)) { row in
                optionalMoney(row.operatingCashFlow)
            }
            .width(min: 110, ideal: 130)
        }
        .frame(minHeight: 320)
        .accessibilityIdentifier("r6.sec.financials-table")
    }

    private var insiderTable: some View {
        Table(model.insider, sortOrder: $insiderSort) {
            TableColumn("交易日期", sortUsing: KeyPathComparator(\SecInsiderItem.transactionDate, order: .reverse)) { row in
                Text(row.transactionDate ?? "数据不足")
            }
            .width(min: 100, ideal: 120)
            TableColumn("内部人", sortUsing: KeyPathComparator(\SecInsiderItem.insiderName)) { row in
                MainTableCell(row.insiderName ?? "数据不足", subtitle: row.insiderTitle)
            }
            .width(min: 170, ideal: 240)
            TableColumn("代码") { row in Text(row.transactionCode ?? "—") }
                .width(min: 60, ideal: 80)
            TableColumn("股数", sortUsing: KeyPathComparator(\SecInsiderItem.shares, order: .reverse)) { row in
                optionalNumber(row.shares, 0)
            }
            .width(min: 90, ideal: 110)
            TableColumn("价格", sortUsing: KeyPathComparator(\SecInsiderItem.price, order: .reverse)) { row in
                optionalNumber(row.price, 2)
            }
            .width(min: 80, ideal: 100)
            TableColumn("金额", sortUsing: KeyPathComparator(\SecInsiderItem.value, order: .reverse)) { row in
                optionalMoney(row.value)
            }
            .width(min: 90, ideal: 110)
            TableColumn("标记") { row in Text(row.flag ?? "—") }
                .width(min: 70, ideal: 100)
        }
        .frame(minHeight: 320)
        .accessibilityIdentifier("r6.sec.insider-table")
    }

    @ViewBuilder
    private var holdingsTable: some View {
        if let page = model.holdings {
            VStack(alignment: .leading, spacing: 8) {
                MetadataStrip([
                    .init(label: "报告期", value: page.reportPeriod ?? "数据不足"),
                    .init(label: "上期", value: page.prevPeriod ?? "—"),
                ])
                Table(model.holdings?.holdings ?? [], sortOrder: $holdingsSort) {
                    TableColumn("机构", sortUsing: KeyPathComparator(\Sec13FHoldingItem.managerName)) { row in
                        MainTableCell(row.managerName ?? "数据不足")
                    }
                    .width(min: 200, ideal: 300)
                    TableColumn("股数", sortUsing: KeyPathComparator(\Sec13FHoldingItem.shares, order: .reverse)) { row in
                        optionalNumber(row.shares, 0)
                    }
                    .width(min: 90, ideal: 110)
                    TableColumn("市值 USD", sortUsing: KeyPathComparator(\Sec13FHoldingItem.valueUsd, order: .reverse)) { row in
                        optionalMoney(row.valueUsd)
                    }
                    .width(min: 100, ideal: 120)
                    TableColumn("类型") { row in Text(row.putCall ?? "—") }
                        .width(min: 60, ideal: 80)
                    TableColumn("环比变化", sortUsing: KeyPathComparator(\Sec13FHoldingItem.shareChange, order: .reverse)) { row in
                        if let change = row.shareChange {
                            HStack(spacing: StockMonitorSpacing.xSmall) {
                                Image(systemName: change >= 0 ? "arrow.up" : "arrow.down")
                                    .font(.caption.weight(.bold))
                                    .accessibilityHidden(true)
                                Text((change >= 0 ? "+" : "") + change.formatted(.number.precision(.fractionLength(0))))
                                    .financialFigures()
                            }
                            .foregroundStyle(change >= 0 ? StockMonitorChartPalette.positive : StockMonitorChartPalette.negative)
                            .frame(maxWidth: .infinity, alignment: .trailing)
                        } else if row.isNew == true {
                            SemanticStatusLabel("新建仓", status: .info)
                        } else {
                            Text("数据不足").foregroundStyle(.secondary)
                        }
                    }
                    .width(min: 90, ideal: 110)
                    TableColumn("申报日") { row in Text(row.filingDate ?? "—") }
                        .width(min: 90, ideal: 110)
                }
                .frame(minHeight: 260)
                .accessibilityIdentifier("r6.sec.13f-table")
            }
        }
    }

    private func optionalNumber(_ value: Double?, _ digits: Int) -> some View {
        NumericTableCell(value: value, digits: digits)
    }

    private func optionalMoney(_ value: Double?) -> some View {
        NumericTableCell(value: value, digits: 1, compact: true)
    }
}

// MARK: - 个股对比

@MainActor
@Observable
public final class CompareModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var catalog: CompareCatalog?
    public private(set) var run: CompareRun?
    public private(set) var history: CompareHistoryResponse?
    public private(set) var historyMetricKey: String?
    public private(set) var historySeries: [LineSeries] = []
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func loadCatalog() async {
        do {
            catalog = try await service.compareCatalog()
        } catch {
            self.error = .from(error)
        }
    }

    public func compare(symbols: [String]) async {
        state = run == nil ? .loading : .refreshing
        do {
            run = try await service.compare(symbols: symbols)
            history = nil
            historyMetricKey = nil
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = run == nil ? .error : .stale
        }
    }

    public func loadHistory(symbols: [String], metricKey: String) async {
        do {
            let value = try await service.compareHistory(symbols: symbols, metricKey: metricKey)
            history = value
            historyMetricKey = metricKey
            historySeries = value.series.enumerated().map { index, series in
                LineSeries(
                    name: series.symbol,
                    paletteIndex: index,
                    points: series.points.compactMap { point in
                        guard let raw = point.indexed ?? point.value, let date = ChartTime.day(point.date) else { return nil }
                        return TimedPoint(date: ChartDomain.normalize(date), value: raw)
                    }
                )
            }
            .filter { !$0.points.isEmpty }
        } catch {
            self.error = .from(error)
        }
    }
}

public struct CompareView: View {
    @State private var model: CompareModel
    @State private var symbolText = ""
    @State private var selectedSymbols: [String] = []
    @State private var historyMetricKey = ""
    let openStock: (String) -> Void

    init(model: CompareModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model)
        self.openStock = openStock
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    M4SectionHeader("个股对比", subtitle: "2–6 只证券；全部结果来自已持久化数据，不调用外部 provider")
                    symbolPicker
                    if let run = model.run {
                        securitiesStrip(run)
                        compareMatrix(run)
                        winnersSection(run)
                        highlightsSection(run)
                        limitationsSection(run.limitations)
                        historySection(run)
                    } else {
                        ContentUnavailableView("选择证券后开始对比", systemImage: "square.split.2x1")
                    }
                }
                .padding(24)
            }
        }
        .navigationTitle("个股对比")
        .task { await model.loadCatalog() }
        .overlay(alignment: .top) { FeatureErrorBanner(error: model.error).padding() }
        .accessibilityIdentifier("m4.compare")
    }

    private var symbolPicker: some View {
        HStack {
            TextField("输入代码后回车添加", text: $symbolText)
                .textFieldStyle(.roundedBorder)
                .frame(width: 220)
                .onSubmit(addSymbol)
            Button("添加", action: addSymbol).buttonStyle(.bordered)
            Button("开始对比") {
                Task { await model.compare(symbols: selectedSymbols) }
            }
            .buttonStyle(.borderedProminent)
            .disabled(selectedSymbols.count < 2)
            ForEach(selectedSymbols, id: \.self) { symbol in
                Button {
                    selectedSymbols.removeAll { $0 == symbol }
                } label: {
                    Label(symbol, systemImage: "xmark.circle.fill")
                }
                .buttonStyle(.bordered)
                .tint(.secondary)
            }
            Spacer()
        }
    }

    private func addSymbol() {
        let value = symbolText.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        symbolText = ""
        guard !value.isEmpty, selectedSymbols.count < 6, !selectedSymbols.contains(value) else { return }
        selectedSymbols.append(value)
    }

    private func securitiesStrip(_ run: CompareRun) -> some View {
        HStack(spacing: 16) {
            ForEach(run.securities) { security in
                Button {
                    openStock(security.symbol)
                } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(security.symbol).fontWeight(.semibold)
                        Text(security.name ?? "名称数据不足").font(.caption).lineLimit(1)
                        Text("\(security.sector ?? "行业数据不足") · \(security.currency ?? "—")")
                            .font(.caption2).foregroundStyle(.secondary)
                    }
                    .padding(10)
                    .background(.background.secondary, in: .rect(cornerRadius: 8))
                    .subtleHoverHighlight()
                }
                .buttonStyle(ImmediatePressButtonStyle())
            }
        }
    }

    private func compareMatrix(_ run: CompareRun) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            M4SectionHeader("指标矩阵", subtitle: "最佳/最差仅在同一比较集合内判定")
            ScrollView(.horizontal) {
                Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 6) {
                    GridRow {
                        Text("指标").font(.caption.bold()).foregroundStyle(.secondary)
                        ForEach(run.securities) { security in
                            Button(security.symbol) { openStock(security.symbol) }
                                .buttonStyle(.plain).font(.caption.bold())
                        }
                    }
                    ForEach(run.metrics) { row in
                        GridRow {
                            Text(row.definition.label)
                                .font(.callout)
                                .help(row.definition.tooltip ?? row.definition.label)
                            ForEach(run.securities) { security in
                                CompareCellView(cell: row.cells[security.symbol], unit: row.definition.unit)
                            }
                        }
                        if let warning = row.comparisonWarning {
                            GridRow {
                                Text(warning).font(.caption2).foregroundStyle(.orange)
                                    .gridCellColumns(run.securities.count + 1)
                            }
                        }
                    }
                }
                .padding(12)
            }
        }
        .padding(14)
        .background(.background.secondary, in: .rect(cornerRadius: 10))
    }

    @ViewBuilder
    private func winnersSection(_ run: CompareRun) -> some View {
        if !run.categoryWinners.isEmpty {
            DisclosureGroup("类别优胜") {
                ForEach(run.categoryWinners) { winner in
                    HStack {
                        Text(winner.category).foregroundStyle(.secondary)
                        Spacer()
                        if let symbol = winner.symbol {
                            Button(symbol) { openStock(symbol) }.buttonStyle(.plain).fontWeight(.semibold)
                        } else {
                            Text("并列：\(winner.ties.joined(separator: "、"))")
                        }
                    }
                    .font(.callout).padding(.vertical, 2)
                }
            }
            .font(.headline)
        }
    }

    private func highlightsSection(_ run: CompareRun) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            M4SectionHeader("优势与短板（前 5 项）")
            HStack(alignment: .top, spacing: 20) {
                ForEach(run.highlights) { highlight in
                    VStack(alignment: .leading, spacing: 6) {
                        Button(highlight.symbol) { openStock(highlight.symbol) }.buttonStyle(.plain).fontWeight(.semibold)
                        ForEach(highlight.strengths, id: \.key) { item in
                            Label(item.label, systemImage: "arrow.up.circle").font(.caption).foregroundStyle(.green)
                        }
                        ForEach(highlight.weaknesses, id: \.key) { item in
                            Label(item.label, systemImage: "arrow.down.circle").font(.caption).foregroundStyle(.red)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
    }

    @ViewBuilder
    private func historySection(_ run: CompareRun) -> some View {
        let historyMetrics = model.catalog?.metrics.filter { $0.supportsHistory == true } ?? []
        VStack(alignment: .leading, spacing: 8) {
            M4SectionHeader("历史序列", subtitle: "仅来自已持久化的 FMP/Yahoo/估值快照，不补抓数据")
            if historyMetrics.isEmpty {
                Text("指标目录尚未加载").foregroundStyle(.secondary)
            } else {
                Picker("指标", selection: $historyMetricKey) {
                    Text("选择指标").tag("")
                    ForEach(historyMetrics) { Text($0.label).tag($0.key) }
                }
                .frame(width: 300)
                Button("查看序列") {
                    Task {
                        await model.loadHistory(symbols: selectedSymbols, metricKey: historyMetricKey)
                    }
                }
                .disabled(historyMetricKey.isEmpty)
                if let history = model.history, !model.historySeries.isEmpty {
                    ChartPanel(
                        "历史序列图表",
                        unitLabel: history.mode == "indexed" ? "首日=100" : nil,
                        source: "已持久化 FMP/Yahoo/估值快照",
                        asOf: model.historySeries.compactMap(\.points.last?.date).max().map(ChartTime.formatDay)
                    ) {
                        LineSeriesChart(
                            series: model.historySeries,
                            unitLabel: history.mode == "indexed" ? "（首日=100）" : ""
                        )
                        .frame(height: 260)
                    }
                } else if model.history != nil {
                    Text("数据不足：该指标暂无历史序列。").foregroundStyle(.secondary)
                }
            }
        }
        .padding(14)
        .background(.background.secondary, in: .rect(cornerRadius: 10))
    }

    @ViewBuilder
    private func limitationsSection(_ limitations: [String]) -> some View {
        if !limitations.isEmpty {
            DisclosureGroup("解读边界") {
                ForEach(Array(limitations.enumerated()), id: \.offset) { _, item in
                    Text("· " + item).font(.caption).foregroundStyle(.secondary)
                }
            }
            .font(.headline)
        }
    }
}

struct CompareCellView: View {
    let cell: CompareCell?
    let unit: String?

    var body: some View {
        if let cell {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(cell.value.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
                        .monospacedDigit()
                        .foregroundStyle(cell.value == nil ? .secondary : .primary)
                    if cell.isBest == true {
                        Image(systemName: "crown.fill").font(.caption2).foregroundStyle(.yellow)
                    }
                    if cell.isWorst == true {
                        Image(systemName: "arrow.down.circle").font(.caption2).foregroundStyle(.red)
                    }
                }
                if let status = cell.status, status != "available" {
                    Text(statusLabel(status)).font(.caption2).foregroundStyle(.secondary)
                }
                if let rank = cell.rank, let percentile = cell.percentile {
                    Text("排名 \(rank) · 分位 \(percentile.formatted(.number.precision(.fractionLength(0))))%")
                        .font(.caption2).foregroundStyle(.secondary).monospacedDigit()
                }
            }
        } else {
            Text("数据不足").foregroundStyle(.secondary)
        }
    }

    private func statusLabel(_ status: String) -> String {
        switch status {
        case "missing": "缺失"
        case "stale": "过期"
        case "unsupported": "不适用"
        case "insufficient": "数据不足"
        default: status
        }
    }
}

// MARK: - 公众人物交易

@MainActor
@Observable
public final class CongressModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var figures: [CongressFigure] = []
    public private(set) var detail: CongressFigureDetail?
    public private(set) var selectedSlug: String?
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func load() async {
        state = figures.isEmpty ? .loading : .refreshing
        do {
            figures = try await service.congressFigures()
            state = .ready
            error = nil
            if selectedSlug == nil, let first = figures.first {
                await select(first.slug)
            }
        } catch {
            self.error = .from(error)
            state = figures.isEmpty ? .error : .stale
        }
    }

    public func select(_ slug: String) async {
        selectedSlug = slug
        do {
            detail = try await service.congressFigure(slug: slug)
        } catch {
            self.error = .from(error)
        }
    }
}

public struct CongressView: View {
    @State private var model: CongressModel
    /// R6.0：人物交易默认按交易日期降序。
    @State private var tradesSort: [KeyPathComparator<CongressTradeItem>] = [
        KeyPathComparator(\.transactionDate, order: .reverse),
    ]
    let openStock: (String) -> Void

    init(model: CongressModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model)
        self.openStock = openStock
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            HSplitView {
                List(model.figures, selection: Binding(
                    get: { model.selectedSlug },
                    set: { value in
                        if let value {
                            Task { await model.select(value) }
                        }
                    }
                )) { figure in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(figure.displayName).fontWeight(.medium)
                            Text(figure.kind ?? "").font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if figure.hasPositions == true {
                            Image(systemName: "chart.pie").foregroundStyle(.secondary)
                        }
                    }.tag(figure.slug)
                }
                .frame(minWidth: 240, idealWidth: 300)
                ScrollView {
                    detailContent.padding(24)
                }
                .frame(minWidth: 420)
            }
        }
        .navigationTitle("公众人物交易")
        .task { await model.load() }
        .overlay(alignment: .top) { FeatureErrorBanner(error: model.error).padding() }
        .accessibilityIdentifier("m4.congress")
    }

    @ViewBuilder
    private var detailContent: some View {
        if let detail = model.detail {
            VStack(alignment: .leading, spacing: 18) {
                M4SectionHeader(detail.displayName, subtitle: detail.kind ?? "")
                if let note = detail.note {
                    Text(note).font(.callout).foregroundStyle(.secondary)
                }
                positionsSection(detail)
                movesSection(detail)
                tradesSection(detail)
            }.frame(maxWidth: 860, alignment: .leading)
        } else {
            ContentUnavailableView("选择一位人物", systemImage: "person.crop.rectangle.stack")
        }
    }

    @ViewBuilder
    private func positionsSection(_ detail: CongressFigureDetail) -> some View {
        if !detail.positions.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                M4SectionHeader("持仓", subtitle: detail.positionsArePercent == true ? "按百分比披露" : "按金额披露")
                ForEach(detail.positions.prefix(20)) { position in
                    HStack {
                        if let ticker = position.ticker {
                            Button(ticker) { openStock(ticker) }.buttonStyle(.plain).subtleHoverHighlight().fontWeight(.semibold).subtleHoverHighlight()
                        } else {
                            Text(position.assetName ?? "—")
                        }
                        Text(position.category ?? "").font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        Text(position.value.formatted(detail.positionsArePercent == true ? .number.precision(.fractionLength(1)) : .number.notation(.compactName)))
                            .monospacedDigit()
                        Text(detail.positionsArePercent == true ? "%" : "").monospacedDigit().foregroundStyle(.secondary)
                    }.font(.callout).padding(.vertical, 2)
                }
                if detail.positions.count > 20 {
                    Text("仅展示前 20 项（共 \(detail.positions.count) 项）").font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(14)
            .background(.background.secondary, in: .rect(cornerRadius: 10))
        }
    }

    @ViewBuilder
    private func movesSection(_ detail: CongressFigureDetail) -> some View {
        if let moves = detail.moves {
            DisclosureGroup("调仓看板") {
                SemanticEvidenceView(value: moves, domain: .congress).padding(.top, 8)
            }
            .font(.headline)
        }
    }

    private func tradesSection(_ detail: CongressFigureDetail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            M4SectionHeader("交易时间线", subtitle: "\(detail.trades.count) 条记录")
            Table(detail.trades, sortOrder: $tradesSort) {
                TableColumn("交易日期", sortUsing: KeyPathComparator(\CongressTradeItem.transactionDate, order: .reverse)) { row in
                    Text(row.transactionDate ?? "数据不足")
                }
                .width(min: 100, ideal: 120)
                TableColumn("代码") { trade in
                    if let ticker = trade.ticker {
                        Button(ticker) { openStock(ticker) }.buttonStyle(.plain).subtleHoverHighlight()
                    } else {
                        Text("—")
                    }
                }
                .width(min: 70, ideal: 90)
                TableColumn("资产") { row in
                    MainTableCell(row.assetName ?? "—")
                }
                .width(min: 160, ideal: 220)
                TableColumn("方向") { row in Text(row.transactionType ?? "—") }
                    .width(min: 90, ideal: 120)
                TableColumn("金额区间") { row in Text(row.amountLabel ?? "数据不足") }
                    .width(min: 120, ideal: 150)
                TableColumn("申报日") { row in Text(row.filingDate ?? "—") }
                    .width(min: 100, ideal: 120)
                TableColumn("迟报") { trade in
                    if trade.isLate == true {
                        Text("迟报").foregroundStyle(.orange)
                    } else {
                        Text("—").foregroundStyle(.secondary)
                    }
                }
                .width(min: 60, ideal: 70)
            }
            .frame(minHeight: 220)
            .accessibilityIdentifier("r6.congress.trades-table")
        }
    }
}

/// SEC 事件时间线行：条目 → 日期/表格 → 中文摘要 → 原文链接。
struct SecEventTimelineRow: View {
    let event: SecEventItem

    var body: some View {
        HStack(alignment: .top, spacing: StockMonitorSpacing.regular) {
            Image(systemName: "doc.text.magnifyingglass")
                .foregroundStyle(.tint)
                .frame(width: 20)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(event.itemLabel ?? event.itemCode ?? "未分类条目").font(.headline)
                        Spacer()
                        Text("\(event.form ?? "—") · \(event.filingDate ?? "日期数据不足")").stockMonitorTypography(.metadata)
                    }
                    VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                        Text(event.itemLabel ?? event.itemCode ?? "未分类条目").font(.headline)
                        Text("\(event.form ?? "—") · \(event.filingDate ?? "日期数据不足")").stockMonitorTypography(.metadata)
                    }
                }
                Text(event.summaryZh ?? event.text ?? "摘要数据不足")
                    .stockMonitorTypography(.body)
                    .textSelection(.enabled)
                if let status = event.summaryStatus, status != "ready" {
                    SemanticStatusLabel("摘要状态：\(status)", status: .stale)
                }
                if let raw = event.filingUrl, let url = URL(string: raw) {
                    ConfirmExternalLinkButton(url: url)
                }
            }
        }
        .padding(.vertical, StockMonitorSpacing.small)
        .accessibilityElement(children: .combine)
    }
}
