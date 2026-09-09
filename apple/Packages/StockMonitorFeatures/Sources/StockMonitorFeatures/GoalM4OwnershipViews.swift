import StockMonitorDesign
import SwiftUI

/// 公司分析组共享的自选代码上下文：研究端点受全局自选门控，默认代码必须来自自选列表。
@MainActor
@Observable
public final class CompanyTickerContext {
    public private(set) var symbols: [String] = []
    public private(set) var loaded = false
    public private(set) var failed = false

    public init() {}

    /// 测试与预览注入已加载状态。
    public init(symbols: [String], loaded: Bool = true) {
        self.symbols = symbols
        self.loaded = loaded
    }

    public func loadIfNeeded(service: ResearchWorkspaceService) async {
        guard !loaded else { return }
        loaded = true
        do {
            symbols = try await service.watchlistSymbols()
        } catch {
            failed = true
        }
    }

    /// 深链/跨页选中的代码优先；不在自选列表时回退到自选第一只，避免整页 404。
    public func resolve(preferred: String?) -> String? {
        if let preferred, !preferred.isEmpty, symbols.contains(preferred) {
            return preferred
        }
        return symbols.first
    }

    /// 页面首次进入的统一引导：确保自选列表已加载，再解析生效代码。
    public func resolveAfterLoad(service: ResearchWorkspaceService, preferred: String?) async -> String? {
        await loadIfNeeded(service: service)
        return resolve(preferred: preferred)
    }
}

/// 自选代码选择条：替代自由输入，与 Web 的 SnapshotTickerBar 语义一致。
struct CompanySymbolBar: View {
    let context: CompanyTickerContext
    let service: ResearchWorkspaceService
    @Binding var symbol: String
    let initialSymbol: String?
    let onLoad: (String) async -> Void

    var body: some View {
        HStack(spacing: 10) {
            if context.symbols.isEmpty {
                if context.failed {
                    Label("自选列表加载失败", systemImage: "exclamationmark.triangle")
                        .font(.callout).foregroundStyle(.orange)
                    Button("重试") { Task { await bootstrap() } }.buttonStyle(.bordered)
                } else if context.loaded {
                    Text("自选列表为空：请先在自选股页添加证券，公司分析页才有可查询代码。")
                        .font(.callout).foregroundStyle(.secondary)
                } else {
                    ProgressView().controlSize(.small)
                }
            } else {
                Picker("证券", selection: $symbol) {
                    ForEach(context.symbols, id: \.self) { Text($0) }
                }
                .pickerStyle(.menu)
                .frame(width: 130)
                .onChange(of: symbol) { _, value in
                    Task { await onLoad(value) }
                }
                Button("刷新") { Task { await onLoad(symbol) } }.buttonStyle(.bordered)
            }
            Spacer()
        }
    }

    /// 首次进入：加载自选 → 解析默认代码 → 触发一次加载。返回最终生效的代码。
    func bootstrap() async -> String? {
        await context.loadIfNeeded(service: service)
        guard let resolved = context.resolve(preferred: initialSymbol ?? symbol) else { return nil }
        if symbol != resolved {
            symbol = resolved
        } else {
            await onLoad(resolved)
        }
        return resolved
    }
}

// MARK: - 机构持仓（13F + 内部人 + 国会交易）

@MainActor
@Observable
public final class OwnershipModel {
    public enum Tab: String, CaseIterable, Identifiable {
        case holdings13f = "13F 机构"
        case insider = "内部人交易"
        case congress = "国会交易"
        public var id: Self {
            self
        }
    }

    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var tab: Tab = .holdings13f
    public private(set) var holdings: Sec13FPage?
    public private(set) var insider: [SecInsiderItem] = []
    public private(set) var congress: [CongressTradeItem] = []
    public private(set) var symbol: String?
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func select(_ tab: Tab) {
        self.tab = tab
    }

    public func load(symbol: String) async {
        self.symbol = symbol
        state = holdings == nil && insider.isEmpty && congress.isEmpty ? .loading : .refreshing
        do {
            async let holdings = service.sec13F(ticker: symbol)
            async let insider = service.secInsider(ticker: symbol)
            async let congress = service.congressTrades(ticker: symbol)
            let values = try await (holdings, insider, congress)
            self.holdings = values.0
            self.insider = values.1
            self.congress = values.2
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = holdings == nil ? .error : .stale
        }
    }
}

public struct OwnershipView: View {
    @State private var model: OwnershipModel
    @State private var symbol = ""
    /// R6.0：三张表默认排序——13F 按市值降序、内部人/国会按交易日期降序，列头可再排序。
    @State private var holdingsSort: [KeyPathComparator<Sec13FHoldingItem>] = [
        KeyPathComparator(\.valueUsd, order: .reverse)
    ]
    @State private var insiderSort: [KeyPathComparator<SecInsiderItem>] = [
        KeyPathComparator(\.transactionDate, order: .reverse)
    ]
    @State private var congressSort: [KeyPathComparator<CongressTradeItem>] = [
        KeyPathComparator(\.transactionDate, order: .reverse)
    ]
    let initialSymbol: String?
    let tickerContext: CompanyTickerContext
    let companySummary: CompanySummaryModel

    init(model: OwnershipModel, tickerContext: CompanyTickerContext, companySummary: CompanySummaryModel, symbol: String?) {
        _model = State(initialValue: model)
        _symbol = State(initialValue: symbol ?? "")
        initialSymbol = symbol
        self.tickerContext = tickerContext
        self.companySummary = companySummary
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            PageScaffold(width: StockMonitorContentWidth.wide) {
                PageHeader("机构持仓", summary: "13F 机构持仓、SEC 内部人交易与国会交易聚合视图。") {
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
                Picker("数据集", selection: Binding(
                    get: { model.tab },
                    set: { model.select($0) }
                )) {
                    ForEach(OwnershipModel.Tab.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .frame(width: 300)
                FeatureErrorBanner(error: model.error)
                tabContent
            }
        }
        .navigationTitle("机构持仓")
        .task {
            await companySummary.loadIfNeeded()
            if let resolved = await bootstrapSymbol() {
                await model.load(symbol: resolved)
            }
        }
        .onChange(of: initialSymbol) { _, value in
            guard let value, tickerContext.symbols.contains(value), value != symbol else { return }
            symbol = value
            Task { await model.load(symbol: value) }
        }
        .accessibilityIdentifier("m4.ownership")
    }

    private func bootstrapSymbol() async -> String? {
        await tickerContext.loadIfNeeded(service: model.service)
        return tickerContext.resolve(preferred: initialSymbol ?? symbol).map { resolved in
            if symbol != resolved {
                symbol = resolved
            }
            return resolved
        }
    }

    @ViewBuilder
    private var tabContent: some View {
        switch model.tab {
        case .holdings13f: holdingsTable
        case .insider: insiderTable
        case .congress: congressTable
        }
    }

    @ViewBuilder
    private var holdingsTable: some View {
        if let page = model.holdings {
            if page.holdings.isEmpty {
                ContentUnavailableView("该股暂无 13F 持仓数据", systemImage: "person.3")
            } else {
                VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                    MetadataStrip([
                        .init(label: "报告期", value: page.reportPeriod ?? "数据不足"),
                        .init(label: "上期", value: page.prevPeriod ?? "—"),
                        .init(label: "口径", value: "13F 季度快照，滞后约 45 天"),
                    ])
                    Table(model.holdings?.holdings ?? [], sortOrder: $holdingsSort) {
                        TableColumn("机构", sortUsing: KeyPathComparator(\Sec13FHoldingItem.managerName)) { row in
                            MainTableCell(row.managerName ?? "数据不足")
                        }
                        .width(min: 200, ideal: 300)
                        TableColumn("股数", sortUsing: KeyPathComparator(\Sec13FHoldingItem.shares, order: .reverse)) { row in
                            optionalCount(row.shares)
                        }
                        .width(min: 90, ideal: 110)
                        TableColumn("市值 USD", sortUsing: KeyPathComparator(\Sec13FHoldingItem.valueUsd, order: .reverse)) { row in
                            NumericTableCell(value: row.valueUsd, digits: 1, compact: true)
                        }
                        .width(min: 100, ideal: 120)
                        TableColumn("类型") { row in Text(row.putCall ?? "—") }
                        .width(min: 60, ideal: 80)
                        TableColumn("环比", sortUsing: KeyPathComparator(\Sec13FHoldingItem.shareChange, order: .reverse)) { row in
                            holdingChangeBadge(row)
                        }
                        .width(min: 90, ideal: 110)
                        TableColumn("申报日") { row in Text(row.filingDate ?? "—") }
                        .width(min: 90, ideal: 110)
                    }
                    .alternatingRowBackgrounds(.enabled)
                    .frame(minHeight: 300)
                    .accessibilityIdentifier("r6.ownership.13f-table")
                }
            }
        }
    }

    @ViewBuilder
    private var insiderTable: some View {
        if model.insider.isEmpty {
            ContentUnavailableView("该股暂无内部人交易数据", systemImage: "person.crop.square")
        } else {
            Table(model.insider, sortOrder: $insiderSort) {
                TableColumn("交易日期", sortUsing: KeyPathComparator(\SecInsiderItem.transactionDate, order: .reverse)) { row in
                    Text(row.transactionDate ?? "数据不足")
                }
                .width(min: 100, ideal: 120)
                TableColumn("内部人", sortUsing: KeyPathComparator(\SecInsiderItem.insiderName)) { row in
                    MainTableCell(row.insiderName ?? "数据不足", subtitle: row.insiderTitle)
                }
                .width(min: 180, ideal: 260)
                TableColumn("代码") { row in Text(row.transactionCode ?? "—") }
                .width(min: 60, ideal: 80)
                TableColumn("股数", sortUsing: KeyPathComparator(\SecInsiderItem.shares, order: .reverse)) { row in
                    optionalCount(row.shares)
                }
                .width(min: 90, ideal: 110)
                TableColumn("价格", sortUsing: KeyPathComparator(\SecInsiderItem.price, order: .reverse)) { row in
                    NumericTableCell(value: row.price, digits: 2)
                }
                .width(min: 80, ideal: 100)
                TableColumn("金额", sortUsing: KeyPathComparator(\SecInsiderItem.value, order: .reverse)) { row in
                    NumericTableCell(value: row.value, digits: 1, compact: true)
                }
                .width(min: 90, ideal: 110)
            }
            .alternatingRowBackgrounds(.enabled)
            .frame(minHeight: 300)
            .accessibilityIdentifier("r6.ownership.insider-table")
        }
    }

    @ViewBuilder
    private var congressTable: some View {
        if model.congress.isEmpty {
            ContentUnavailableView("该股暂无国会交易数据", systemImage: "building.columns")
        } else {
            Table(model.congress, sortOrder: $congressSort) {
                TableColumn("交易日期", sortUsing: KeyPathComparator(\CongressTradeItem.transactionDate, order: .reverse)) { row in
                    Text(row.transactionDate ?? "数据不足")
                }
                .width(min: 100, ideal: 120)
                TableColumn("交易人", sortUsing: KeyPathComparator(\CongressTradeItem.filerName)) { row in
                    Text(row.filerName ?? "数据不足")
                }
                .width(min: 140, ideal: 200)
                TableColumn("方向") { row in Text(row.transactionType ?? "—") }
                .width(min: 90, ideal: 120)
                TableColumn("金额区间") { row in Text(row.amountLabel ?? "数据不足") }
                .width(min: 120, ideal: 150)
                TableColumn("申报日") { row in Text(row.filingDate ?? "—") }
                .width(min: 100, ideal: 120)
                TableColumn("迟报") { row in
                    if row.isLate == true {
                        Text("迟报").foregroundStyle(.orange)
                    } else {
                        Text("—").foregroundStyle(.secondary)
                    }
                }
                .width(min: 60, ideal: 70)
            }
            .alternatingRowBackgrounds(.enabled)
            .frame(minHeight: 300)
            .accessibilityIdentifier("r6.ownership.congress-table")
        }
    }

    /// 环比用符号 + 文字徽标表达，颜色不是唯一编码。
    @ViewBuilder
    private func holdingChangeBadge(_ row: Sec13FHoldingItem) -> some View {
        if let change = row.shareChange {
            HStack(spacing: StockMonitorSpacing.xSmall) {
                Image(systemName: change >= 0 ? "arrow.up" : "arrow.down")
                    .font(.caption.weight(.bold))
                    .accessibilityHidden(true)
                Text((change >= 0 ? "+" : "") + change.formatted(.number.precision(.fractionLength(0))))
                    .financialFigures()
            }
            .foregroundStyle(change >= 0 ? StockMonitorChartPalette.positive : StockMonitorChartPalette.negative)
        } else if row.isNew == true {
            SemanticStatusLabel("新建仓", status: .info)
        } else {
            Text("数据不足").foregroundStyle(.secondary)
        }
    }

    private func optionalCount(_ value: Double?) -> some View {
        NumericTableCell(value: value, digits: 0)
    }
}
