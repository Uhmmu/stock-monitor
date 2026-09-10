import StockMonitorDesign
import SwiftUI
import UniformTypeIdentifiers
#if os(macOS)
    import AppKit
#endif

// MARK: - 路由入口（R4.0/R4.1 重设计）

public struct GoalM3RouteView: View {
    public let route: AppRoute
    @Bindable public var navigation: AppNavigationModel
    public let service: MarketWorkflowService
    public let openStock: (String) -> Void

    public init(route: AppRoute, navigation: AppNavigationModel, service: MarketWorkflowService, openStock: @escaping (String) -> Void) {
        self.route = route
        self.navigation = navigation
        self.service = service
        self.openStock = openStock
    }

    public var body: some View {
        switch route {
        case .overview:
            OverviewView(model: OverviewModel(service: service), navigate: navigation.navigate, openStock: select)
        case .watchlist:
            WatchlistView(model: WatchlistModel(service: service), navigation: navigation, openStock: select)
        case .alerts:
            ActivityView(model: ActivityModel(service: service), openStock: select)
        case .news:
            NewsCenterView(model: NewsModel(service: service), navigation: navigation, openStock: select)
        case .calendar:
            InvestmentCalendarView(model: CalendarModel(service: service), openStock: select)
        case .reports:
            ReportsView(model: ReportsModel(service: service), openStock: select)
        default:
            ContentUnavailableView(route.title, systemImage: route.systemImage, description: Text("该路由不属于市场工作流。"))
        }
    }

    private func select(_ symbol: String) {
        navigation.selectedSymbol = symbol
        openStock(symbol)
    }
}

struct FeatureErrorBanner: View {
    let error: M3FeatureError?
    var body: some View {
        if let error {
            InlineError("部分数据不可用", message: error.text)
        }
    }
}

// MARK: - 总览（R4.0：首屏四类核心状态，不滚动即可读取）

public struct OverviewView: View {
    @State private var model: OverviewModel
    @Environment(\.stockMonitorWebInspired) private var webInspired
    @State private var exportingQuotes = false
    let navigate: (AppRoute) -> Void
    let openStock: (String) -> Void

    public init(model: OverviewModel, navigate: @escaping (AppRoute) -> Void, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model)
        self.navigate = navigate
        self.openStock = openStock
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            PageScaffold(width: StockMonitorContentWidth.wide) {
                overviewHeader
            } content: {
                FeatureErrorBanner(error: model.error)
                OverviewCoreStateStrip(
                    marketOpen: model.dashboard?.market.isOpen ?? false,
                    marketSession: model.dashboard?.market.session,
                    portfolioReturnPercent: model.benchmark?.portfolioReturnPercent,
                    portfolioConfigured: model.benchmark?.configured ?? false,
                    breadth: breadth,
                    alertCount: model.alerts.count,
                    latestAlertDescription: latestAlertDescription
                )
                indexSection
                notableChangesSection
                latestReportsSection
                quoteSection
            }
            .refreshable { await model.load() }
        }
        .navigationTitle("总览")
        .task { await model.load() }
        .onDisappear { model.stop() }
        .fileExporter(
            isPresented: $exportingQuotes,
            document: QuoteCSVDocument(csv: quoteCSV),
            contentType: .commaSeparatedText,
            defaultFilename: "stock-monitor-quotes"
        ) { _ in }
        .accessibilityIdentifier("m3.overview")
    }

    private var headerSummary: String {
        model.dashboard?.market.isOpen == true ? "美股常规交易时段" : "当前休市或非常规时段"
    }

    @ViewBuilder private var overviewHeader: some View {
        if webInspired {
            WebInspiredHero("市场总览", eyebrow: "Overview", summary: headerSummary) {
                headerStatus
            } actions: {
                Button("查看异动", systemImage: "bell") { navigate(.alerts) }
                    .buttonStyle(.borderedProminent)
            }
        } else {
            PageHeader("市场总览", summary: headerSummary) { headerStatus }
        }
    }

    private var headerStatus: some View {
        HStack(spacing: StockMonitorSpacing.regular) {
            SemanticStatusLabel(model.streamConnected ? "实时连接" : "快照", status: model.streamConnected ? .live : .stale)
            if let lastUpdated = model.lastUpdated {
                Text(lastUpdated, style: .time).stockMonitorTypography(.metadata)
            }
        }
    }

    private var breadth: OverviewBreadth {
        OverviewSummarizer.breadth(stocks: dashboardStocks, liveQuotes: model.liveQuotes)
    }

    private var latestAlertDescription: String? {
        model.alerts.first.map { alert in
            "\(alert.ticker) \(alert.changePercent > 0 ? "+" : "")\(alert.changePercent.formatted(.number.precision(.fractionLength(2))))%"
        }
    }

    @ViewBuilder private var indexSection: some View {
        SectionHeader("指数", explanation: "收盘价与涨跌在每一行对齐；涨跌同时提供符号、点数与百分比。") {
            Button("刷新") { Task { await model.load() } }
        }
        IndexMetricStrip(indices: model.indices)
    }

    @ViewBuilder private var notableChangesSection: some View {
        SectionHeader("值得关注的变化", explanation: "按触发时间倒序；调查状态直接跟随证券。") {
            Button("全部异动") { navigate(.alerts) }
        }
        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
            if let gainer = breadth.biggestGainer {
                moverRow(label: "领涨", mover: gainer)
            }
            if let loser = breadth.biggestLoser {
                moverRow(label: "领跌", mover: loser)
            }
            ForEach(model.alerts.prefix(5)) { alert in
                AlertSummaryRow(
                    alert: alert,
                    investigationLabel: alertInvestigations[alert.ticker]?.label,
                    investigationSemantic: AlertGrouper.statusSemantic(alertInvestigations[alert.ticker]?.status ?? ""),
                    openStock: openStock
                )
            }
            if model.alerts.isEmpty {
                Text("暂无异动").stockMonitorTypography(.metadata)
            }
        }
    }

    private var alertInvestigations: [String: (status: String, label: String)] {
        AlertGrouper.investigationLookup(model.investigations)
    }

    private func moverRow(label: String, mover: OverviewBreadthMover) -> some View {
        Button {
            openStock(mover.ticker)
        } label: {
            HStack(spacing: StockMonitorSpacing.regular) {
                Text(label).stockMonitorTypography(.metricLabel)
                Text(mover.ticker).fontWeight(.semibold)
                Spacer(minLength: StockMonitorSpacing.regular)
                ChangeLabel(value: mover.changePercent)
            }
            .padding(.vertical, StockMonitorSpacing.small)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("自选\(label) \(mover.ticker)")
    }

    @ViewBuilder private var latestReportsSection: some View {
        SectionHeader("最新报告", explanation: "报告中心按时间倒序；点击标题进入全文阅读。") {
            Button("报告中心") { navigate(.reports) }
        }
        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
            ForEach(model.reports.prefix(4)) { report in
                HStack(alignment: .firstTextBaseline, spacing: StockMonitorSpacing.regular) {
                    Text(report.ticker).fontWeight(.semibold)
                    Text(report.title).lineLimit(1)
                    Spacer(minLength: StockMonitorSpacing.regular)
                    if let confidence = report.confidence {
                        Text(confidence).stockMonitorTypography(.metadata)
                    }
                    Text(String(report.createdAt.prefix(10))).stockMonitorTypography(.metadata)
                }
                .padding(.vertical, StockMonitorSpacing.xSmall)
            }
            if model.reports.isEmpty {
                Text("暂无报告").stockMonitorTypography(.metadata)
            }
        }
    }

    @ViewBuilder private var quoteSection: some View {
        SectionHeader("自选行情明细", explanation: "实时报价优先，回落到轮询快照；来源与状态以徽标扫读。") {
            HStack(spacing: StockMonitorSpacing.small) {
                Button("复制", systemImage: "doc.on.doc") { copyQuotes() }
                Button("导出", systemImage: "square.and.arrow.up") { exportingQuotes = true }
            }
        }
        Table(dashboardStocks) {
            TableColumn("代码") { stock in
                Button(stock.ticker) { openStock(stock.ticker) }.buttonStyle(.plain).fontWeight(.semibold)
            }
            .width(min: 60, ideal: 80)
            TableColumn("公司") { stock in
                Text(stock.companyName ?? "—").foregroundStyle(stock.companyName == nil ? .secondary : .primary)
            }
            TableColumn("价格") { stock in
                let live = model.liveQuotes[stock.ticker]
                Text((live?.price ?? stock.price)?.formatted(.number.precision(.fractionLength(2))) ?? FinancialValueFormatter.unavailable)
                    .financialFigures()
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .foregroundStyle((live?.price ?? stock.price) == nil ? .secondary : .primary)
            }
            .width(min: 80, ideal: 96)
            TableColumn("涨跌") { stock in
                ChangeLabel(value: OverviewSummarizer.changePercent(stock: stock, live: model.liveQuotes[stock.ticker]))
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
            .width(min: 80, ideal: 96)
            TableColumn("来源") { stock in
                Text(model.liveQuotes[stock.ticker]?.provider ?? stock.priceSource ?? FinancialValueFormatter.unavailable)
                    .stockMonitorTypography(.metadata)
            }
            TableColumn("状态") { stock in
                let quote = model.liveQuotes[stock.ticker]
                SemanticStatusLabel(quote?.isStale == false ? "Live" : "快照", status: quote?.isStale == false ? .live : .stale)
            }
            .width(min: 70, ideal: 80)
        }
        .frame(minHeight: 220)
    }

    private var dashboardStocks: [DashboardStock] {
        model.dashboard?.stocks ?? []
    }

    private var quoteCSV: String {
        let rows = dashboardStocks.map { stock in
            let quote = model.liveQuotes[stock.ticker]
            let price = quote?.price ?? stock.price
            let change = OverviewSummarizer.changePercent(stock: stock, live: model.liveQuotes[stock.ticker])
            let fields: [String] = [
                stock.ticker,
                stock.companyName ?? "",
                price.map { String($0) } ?? "",
                change.map { String($0) } ?? "",
                quote?.provider ?? stock.priceSource ?? "",
                quote?.isStale == false ? "live" : "snapshot",
            ]
            return fields.map { csvField($0) }.joined(separator: ",")
        }
        return (["ticker,company,price,change_percent,source,state"] + rows).joined(separator: "\n")
    }

    private func csvField(_ value: String) -> String {
        "\"\(value.replacingOccurrences(of: "\"", with: "\"\""))\""
    }

    private func copyQuotes() {
        #if os(macOS)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(quoteCSV, forType: .string)
        #endif
    }
}

private struct QuoteCSVDocument: FileDocument {
    static let readableContentTypes: [UTType] = [.commaSeparatedText]
    let csv: String

    init(csv: String) {
        self.csv = csv
    }

    init(configuration: ReadConfiguration) throws {
        guard let data = configuration.file.regularFileContents,
              let csv = String(data: data, encoding: .utf8)
        else {
            throw CocoaError(.fileReadCorruptFile)
        }
        self.csv = csv
    }

    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper {
        FileWrapper(regularFileWithContents: Data(csv.utf8))
    }
}

// MARK: - 自选股（R4.0：可排序 Table + badge + inspector 编辑）

/// 表格排序键：custom 保持服务端 displayOrder（自选顺序）。
enum WatchlistSortKey: String, CaseIterable, Identifiable, Sendable {
    case custom, symbol, price, change
    var id: String {
        rawValue
    }
}

public struct WatchlistView: View {
    @State private var model: WatchlistModel
    @Bindable private var navigation: AppNavigationModel
    @Environment(\.undoManager) private var undoManager
    let openStock: (String) -> Void
    @State private var groupName = ""
    @State private var showingNewGroup = false
    @State private var showingGroupManager = false
    @State private var removeCandidate: ManagedStock?
    @State private var sortKey: WatchlistSortKey = .custom
    @State private var sortAscending = true
    @State private var groupFilter: Int?
    @State private var thresholdDrafts: [String: WatchlistThresholdDraft] = [:]

    public init(model: WatchlistModel, navigation: AppNavigationModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model)
        self.navigation = navigation
        self.openStock = openStock
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            HSplitView {
                VStack(spacing: 0) {
                    searchBar
                    filterBar
                    stockTable
                    FeatureErrorBanner(error: model.error).padding(StockMonitorSpacing.regular)
                }
                .frame(minWidth: 480)
                selectedDetail.frame(minWidth: 320, idealWidth: 380)
            }
        }
        .navigationTitle("自选股")
        .task {
            restoreInteractionState()
            await model.load()
        }
        .onChange(of: model.searchQuery) { _, _ in model.search() }
        .onChange(of: model.selectedSymbol) { _, symbol in
            navigation.selectedSymbol = symbol
            navigation.rememberSelection(symbol, for: .watchlist)
            Task { await model.loadPeers() }
        }
        .onChange(of: groupFilter) { _, value in
            navigation.updateState(for: .watchlist) { $0.filterQuery = value.map(String.init) ?? "" }
        }
        .onChange(of: sortKey) { _, value in
            navigation.updateState(for: .watchlist) { $0.sortKey = value.rawValue }
        }
        .toolbar {
            ToolbarItem {
                Button("新建分组", systemImage: "folder.badge.plus") { showingNewGroup = true }
            }
            ToolbarItem {
                Button("管理分组", systemImage: "folder") { showingGroupManager = true }
            }
        }
        .alert("新建分组", isPresented: $showingNewGroup) {
            TextField("名称", text: $groupName)
            Button("创建") { let value = groupName; groupName = ""; Task { await model.createGroup(value) } }
            Button("取消", role: .cancel) {}
        }
        .confirmationDialog("从自选股移除？", isPresented: Binding(get: { removeCandidate != nil }, set: {
            if !$0 {
                removeCandidate = nil
            }
        })) {
            Button("移除", role: .destructive) {
                if let stock = removeCandidate {
                    Task { await model.remove(stock, undoManager: undoManager) }
                }; removeCandidate = nil
            }
            Button("取消", role: .cancel) { removeCandidate = nil }
        } message: { Text("可立即使用“编辑 → 撤销”恢复。") }
        .sheet(isPresented: $showingGroupManager) {
            GroupManagerView(
                groups: model.snapshot?.groups ?? [],
                rename: { group, name in Task { await model.renameGroup(group, name: name) } },
                delete: { group in Task { await model.deleteGroup(group) } }
            )
        }
        .accessibilityIdentifier("m3.watchlist")
    }

    private func restoreInteractionState() {
        let state = navigation.state(for: .watchlist)
        model.selectedSymbol = state.selectedIdentifier
        groupFilter = Int(state.filterQuery)
        sortKey = state.sortKey.flatMap(WatchlistSortKey.init(rawValue:)) ?? .custom
    }

    private var filteredStocks: [ManagedStock] {
        let stocks = model.stocks
        let scoped = groupFilter.map { id in stocks.filter { $0.userGroupID == id } } ?? stocks
        let sorted: [ManagedStock] = switch sortKey {
        case .custom:
            scoped.sorted { $0.displayOrder < $1.displayOrder }
        case .symbol:
            scoped.sorted { $0.ticker < $1.ticker }
        case .price:
            scoped.sorted { ($0.price ?? -.infinity) < ($1.price ?? -.infinity) }
        case .change:
            scoped.sorted { ($0.changePercent ?? -.infinity) < ($1.changePercent ?? -.infinity) }
        }
        return sortAscending ? sorted : sorted.reversed()
    }

    private var groupNames: [Int: String] {
        Dictionary(uniqueKeysWithValues: (model.snapshot?.groups ?? []).map { ($0.id, $0.name) })
    }

    private var searchBar: some View {
        VStack(spacing: 0) {
            TextField("搜索代码或公司（支持直接添加）", text: $model.searchQuery)
                .textFieldStyle(.roundedBorder)
                .padding(StockMonitorSpacing.regular)
            if !model.searchResults.isEmpty {
                List(model.searchResults) { candidate in
                    HStack {
                        VStack(alignment: .leading) {
                            Text(candidate.displaySymbol).fontWeight(.semibold)
                            Text(candidate.displayName).stockMonitorTypography(.metadata)
                        }
                        Spacer()
                        Text(candidate.exchange ?? candidate.market ?? "").stockMonitorTypography(.metadata)
                        Button("添加") { Task { await model.add(candidate) } }.buttonStyle(.bordered)
                        if model.selectedSymbol != nil {
                            Button("同行") { Task { await model.addPeer(candidate) } }.buttonStyle(.bordered)
                        }
                    }
                }
                .frame(height: min(CGFloat(model.searchResults.count) * 52, 260))
            }
        }
    }

    private var filterBar: some View {
        HStack(spacing: StockMonitorSpacing.regular) {
            Picker(
                "分组",
                selection: Binding(
                    get: { groupFilter },
                    set: { groupFilter = $0 }
                )
            ) {
                Text("全部分组").tag(Int?.none)
                ForEach(model.snapshot?.groups ?? []) { group in
                    Text(group.name).tag(Int?.some(group.id))
                }
            }
            .pickerStyle(.menu)
            .frame(width: 150)
            Picker("排序", selection: $sortKey) {
                Text("自定义").tag(WatchlistSortKey.custom)
                Text("代码").tag(WatchlistSortKey.symbol)
                Text("价格").tag(WatchlistSortKey.price)
                Text("涨跌").tag(WatchlistSortKey.change)
            }
            .pickerStyle(.menu)
            .frame(width: 120)
            Button {
                sortAscending.toggle()
            } label: {
                Image(systemName: sortAscending ? "arrow.up" : "arrow.down")
            }
            .help(sortAscending ? "升序（点击切换）" : "降序（点击切换）")
            .accessibilityLabel(sortAscending ? "升序排序" : "降序排序")
            Spacer()
            Text("\(filteredStocks.count) 只").stockMonitorTypography(.metadata)
        }
        .padding(.horizontal, StockMonitorSpacing.regular)
        .padding(.bottom, StockMonitorSpacing.small)
        .stockMonitorFilterBar()
        .padding(.horizontal, StockMonitorSpacing.regular)
    }

    private var stockTable: some View {
        Table(filteredStocks, selection: $model.selectedSymbol) {
            TableColumn("代码") { (stock: ManagedStock) in
                tickerCell(stock)
            }
            .width(min: 80, ideal: 100)
            TableColumn("公司") { stock in
                companyCell(stock)
            }
            .width(min: 150, ideal: 240)
            TableColumn("分组") { stock in
                Text(stock.userGroupID.flatMap { groupNames[$0] } ?? "未分组")
                    .stockMonitorTypography(.metadata)
            }
            .width(min: 90, ideal: 110)
            TableColumn("价格") { (stock: ManagedStock) in
                priceCell(stock)
            }
            .width(min: 80, ideal: 96)
            TableColumn("涨跌") { (stock: ManagedStock) in
                ChangeLabel(value: stock.changePercent)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
            .width(min: 84, ideal: 96)
            TableColumn("提醒") { (stock: ManagedStock) in
                alertCell(stock)
            }
            .width(min: 70, ideal: 80)
        }
        .alternatingRowBackgrounds(.enabled)
        .overlay(alignment: .bottom) {
            if model.pendingIDs.count > 1 {
                Label("正在同步 \(model.pendingIDs.count) 项变更", systemImage: "arrow.triangle.2.circlepath")
                    .stockMonitorTypography(.metadata)
                    .padding(StockMonitorSpacing.small)
                    .background(.bar, in: RoundedRectangle(cornerRadius: StockMonitorCornerRadius.badge))
                    .padding(.bottom, StockMonitorSpacing.small)
            }
        }
        .accessibilityIdentifier("r4.watchlist.table")
    }

    private func tickerCell(_ stock: ManagedStock) -> some View {
        HStack(spacing: StockMonitorSpacing.small) {
            Button(stock.ticker) { openStock(stock.ticker) }.buttonStyle(.plain).fontWeight(.semibold)
            if stock.isPeerReferenced {
                Image(systemName: "link")
                    .foregroundStyle(.secondary)
                    .help("被同行样本引用：\(stock.peerReferencedBy.joined(separator: "、"))")
            }
        }
        .contextMenu { rowMenu(stock) }
    }

    private func companyCell(_ stock: ManagedStock) -> some View {
        Text(stock.companyName ?? "名称数据不足")
            .foregroundStyle(stock.companyName == nil ? .secondary : .primary)
            .contextMenu { rowMenu(stock) }
    }

    private func priceCell(_ stock: ManagedStock) -> some View {
        let price = stock.price
        return Text(price?.formatted(.number.precision(.fractionLength(2))) ?? FinancialValueFormatter.unavailable)
            .financialFigures()
            .frame(maxWidth: .infinity, alignment: .trailing)
            .foregroundStyle(price == nil ? .secondary : .primary)
    }

    @ViewBuilder
    private func alertCell(_ stock: ManagedStock) -> some View {
        if stock.alertEnabled {
            SemanticStatusLabel("提醒开", status: .live)
        } else {
            SemanticStatusLabel("提醒关", status: .unavailable)
        }
    }

    @ViewBuilder
    private func rowMenu(_ stock: ManagedStock) -> some View {
        Button("打开公司入口") { openStock(stock.ticker) }
        Menu("移动到分组") {
            ForEach(model.snapshot?.groups ?? []) { group in
                Button(group.name) { Task { await model.assign(stock: stock, to: group.id) } }
            }
        }
        Button(stock.alertEnabled ? "关闭异动提醒" : "开启异动提醒") { Task { await model.setAlert(!stock.alertEnabled, stock: stock) } }
        Divider()
        Button("移除", role: .destructive) { removeCandidate = stock }
    }

    @ViewBuilder
    private var selectedDetail: some View {
        if let symbol = model.selectedSymbol, let stock = model.stocks.first(where: { $0.ticker == symbol }) {
            ScrollView {
                VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
                    VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                        HStack(spacing: StockMonitorSpacing.small) {
                            Text(stock.ticker).font(.title3.weight(.semibold))
                            if model.pendingIDs.contains(stock.watchlistID ?? -1) {
                                ProgressView().controlSize(.small)
                            }
                        }
                        Text(stock.companyName ?? "名称数据不足").stockMonitorTypography(.body)
                        Text(stock.officialIndustry ?? "行业数据不足").stockMonitorTypography(.metadata)
                    }
                    Button("打开公司入口") { openStock(stock.ticker) }
                        .buttonStyle(.borderedProminent)
                    Divider()
                    monitoringSection(stock)
                    Divider()
                    thresholdSection(stock)
                    Divider()
                    peersSection(stock)
                }
                .padding(StockMonitorSpacing.medium)
            }
        } else {
            ContentUnavailableView("选择一只证券", systemImage: "cursorarrow.click", description: Text("在左侧表格中选择后可在此编辑监控、阈值与同行样本。"))
        }
    }

    @ViewBuilder
    private func monitoringSection(_ stock: ManagedStock) -> some View {
        SectionHeader("监控", explanation: "关闭后该证券不再参与行情轮询与异动检测。") {
            if let id = stock.userGroupID {
                Picker(
                    "分组",
                    selection: Binding(
                        get: { id },
                        set: { value in Task { await model.assign(stock: stock, to: value) } }
                    )
                ) {
                    ForEach(model.snapshot?.groups ?? []) { group in
                        Text(group.name).tag(group.id)
                    }
                }
                .pickerStyle(.menu)
                .frame(width: 140)
            }
        }
        HStack(spacing: StockMonitorSpacing.large) {
            Toggle("行情监控", isOn: Binding(
                get: { model.contractItems[stock.watchlistID ?? -1]?.enabled ?? true },
                set: { value in Task { await model.setMonitoring(value, stock: stock) } }
            ))
            Toggle("异动提醒", isOn: Binding(get: { stock.alertEnabled }, set: { value in Task { await model.setAlert(value, stock: stock) } }))
        }
    }

    /// 阈值编辑直接放在 inspector 中，不再跳转独立 Sheet（R4.0 master + detail）。
    @ViewBuilder
    private func thresholdSection(_ stock: ManagedStock) -> some View {
        let draft = thresholdDrafts[stock.ticker] ?? WatchlistThresholdDraft(stock: stock)
        SectionHeader("异动阈值", explanation: "留空沿用服务端默认值；保存后服务端立即生效。") {
            saveThresholdButton(stock, draft: draft)
        }
        HStack(spacing: StockMonitorSpacing.regular) {
            thresholdField("20 分钟 %", text: binding(stock, keypath: \.twentyString))
            thresholdField("1 小时 %", text: binding(stock, keypath: \.hourString))
            thresholdField("当日 %", text: binding(stock, keypath: \.dayString))
        }
        if let reason = draft.invalidReason {
            Text(reason).stockMonitorTypography(.metadata).foregroundStyle(.orange)
        }
    }

    private func saveThresholdButton(_ stock: ManagedStock, draft: WatchlistThresholdDraft) -> some View {
        Button("保存") {
            Task {
                await model.updateThresholds(stock: stock, twentyMinutes: draft.twenty, oneHour: draft.hour, day: draft.day)
                thresholdDrafts[stock.ticker] = nil
            }
        }
        .disabled(draft.invalidReason != nil)
    }

    private func thresholdField(_ label: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
            Text(label).stockMonitorTypography(.metricLabel)
            TextField("默认", text: text)
                .textFieldStyle(.roundedBorder)
                .financialFigures()
        }
    }

    private func binding(_ stock: ManagedStock, keypath: WritableKeyPath<WatchlistThresholdDraft, String>) -> Binding<String> {
        Binding(
            get: {
                let draft = thresholdDrafts[stock.ticker] ?? WatchlistThresholdDraft(stock: stock)
                return draft[keyPath: keypath]
            },
            set: { value in
                var draft = thresholdDrafts[stock.ticker] ?? WatchlistThresholdDraft(stock: stock)
                draft[keyPath: keypath] = value
                thresholdDrafts[stock.ticker] = draft
            }
        )
    }

    @ViewBuilder
    private func peersSection(_ stock: ManagedStock) -> some View {
        SectionHeader("同行样本", explanation: "代码映射完全由服务端 Security 实体决定。")
        VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
            ForEach(model.peers) { peer in
                HStack {
                    Text(peer.ticker).fontWeight(.medium)
                    Text(peer.source == "official" ? "官方" : "手动").stockMonitorTypography(.metadata)
                    Spacer()
                    Button(peer.source == "manual" ? "移除" : (peer.excluded ? "恢复" : "排除")) { Task { await model.togglePeer(peer) } }
                        .buttonStyle(.borderless)
                }
                .padding(.vertical, StockMonitorSpacing.xSmall)
            }
            if model.peers.isEmpty {
                Text("暂无同行数据").stockMonitorTypography(.metadata)
            }
        }
    }
}

/// inspector 内联阈值草稿：nil 表示沿用服务端默认。
struct WatchlistThresholdDraft: Equatable {
    var twentyString = ""
    var hourString = ""
    var dayString = ""

    init(stock: ManagedStock) {
        twentyString = stock.threshold20m.map { String($0) } ?? ""
        hourString = stock.threshold1h.map { String($0) } ?? ""
        dayString = stock.thresholdDay.map { String($0) } ?? ""
    }

    var twenty: Double? {
        Double(twentyString.trimmingCharacters(in: .whitespaces))
    }

    var hour: Double? {
        Double(hourString.trimmingCharacters(in: .whitespaces))
    }

    var day: Double? {
        Double(dayString.trimmingCharacters(in: .whitespaces))
    }

    var invalidReason: String? {
        let values = [twenty, hour, day].compactMap(\.self)
        if values.contains(where: { $0 <= 0 }) {
            return "所有阈值必须大于 0。"
        }
        return nil
    }
}

private struct GroupManagerView: View {
    let groups: [StockGroup]
    let rename: (StockGroup, String) -> Void
    let delete: (StockGroup) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var names: [Int: String] = [:]
    var body: some View {
        NavigationStack {
            Form {
                ForEach(groups) { group in
                    HStack {
                        TextField("分组名称", text: Binding(get: { names[group.id] ?? group.name }, set: { names[group.id] = $0 }))
                        Button("保存") { rename(group, names[group.id] ?? group.name) }
                        Button("删除", role: .destructive) { delete(group) }
                    }
                }
                if groups.isEmpty {
                    Text("尚未创建分组").foregroundStyle(.secondary)
                }
            }.formStyle(.grouped).padding()
                .navigationTitle("管理分组")
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
        }.frame(width: 520, height: 360)
    }
}

// MARK: - 异动中心（R4.0：严重度 + 时间 + 调查状态分组）

public struct ActivityView: View {
    @State private var model: ActivityModel
    let openStock: (String) -> Void
    public init(model: ActivityModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model); self.openStock = openStock
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            PageScaffold(width: StockMonitorContentWidth.wide) {
                PageHeader("异动中心", summary: "首行说明发生了什么；调查状态跟随每条异动。") {
                    SemanticStatusLabel("\(model.alerts.count) 条异动", status: model.alerts.isEmpty ? .live : .info)
                }
            } content: {
                FeatureErrorBanner(error: model.error)
                severitySummary
                alertGroup("需要关注", explanation: notableExplanation, alerts: buckets.notableDayMoves)
                alertGroup("盘中异动", explanation: "当日一般幅度与 1 小时窗口触发的异动。", alerts: buckets.intradayMoves)
                alertGroup("短时波动", explanation: "20 分钟窗口触发，通常噪音更高。", alerts: buckets.briefMoves)
                alertGroup("目标价触发", explanation: "自选价格目标线触发，独立于波动阈值。", alerts: buckets.priceTargets)
                if !buckets.unclassified.isEmpty {
                    alertGroup("其他周期", explanation: nil, alerts: buckets.unclassified)
                }
                investigationsSection
                if model.canLoadMore {
                    Button("加载更多") { Task { await model.load(reset: false) } }.frame(maxWidth: .infinity)
                }
            }
        }
        .navigationTitle("异动中心").task { await model.load() }.accessibilityIdentifier("m3.alerts")
    }

    private var buckets: AlertSeverityBuckets {
        AlertGrouper.buckets(model.alerts)
    }

    private var notableExplanation: String {
        "当日幅度 ≥ \(AlertGrouper.notableDayMovePercent.formatted())% 的代表性异动。"
    }

    private var investigationsByTicker: [String: (status: String, label: String)] {
        AlertGrouper.investigationLookup(model.investigations)
    }

    private func investigationSymbol(_ status: String) -> String {
        switch status {
        case "completed": "checkmark.circle.fill"
        case "failed": "xmark.circle.fill"
        default: "circle.dashed"
        }
    }

    private var severitySummary: some View {
        let running = model.investigations.filter { $0.status == "active" || $0.status == "reporting" }.count
        return MetricGrid([
            .init(
                label: "显著当日",
                value: FinancialDisplayValue(text: "\(buckets.notableDayMoves.count) 条"),
                status: buckets.notableDayMoves.isEmpty ? .live : .warning
            ),
            .init(label: "盘中/短时", value: .init(text: "\(buckets.intradayMoves.count + buckets.briefMoves.count) 条"), status: .neutral),
            .init(label: "调查进行中", value: .init(text: "\(running) 项"), status: running > 0 ? .info : .live),
            .init(label: "目标价触发", value: .init(text: "\(buckets.priceTargets.count) 条"), status: .neutral),
        ])
    }

    @ViewBuilder
    private func alertGroup(_ title: String, explanation: String?, alerts: [MovementAlert]) -> some View {
        if !alerts.isEmpty {
            SectionHeader(title, explanation: explanation)
            VStack(alignment: .leading, spacing: 0) {
                ForEach(alerts) { alert in
                    AlertSummaryRow(
                        alert: alert,
                        investigationLabel: investigationsByTicker[alert.ticker]?.label,
                        investigationSemantic: AlertGrouper.statusSemantic(investigationsByTicker[alert.ticker]?.status ?? ""),
                        openStock: openStock
                    )
                    Divider()
                }
            }
        }
    }

    @ViewBuilder
    private var investigationsSection: some View {
        if !model.investigations.isEmpty {
            SectionHeader("调查任务", explanation: "每条异动最多关联一个调查；状态由服务端任务推进。")
            TimelineList(model.investigations.map { item in
                TimelineEntry(
                    id: "\(item.id)",
                    title: "\(item.ticker) · \(AlertGrouper.statusLabel(item.status))",
                    timestamp: String(item.startedAt.prefix(16).replacingOccurrences(of: "T", with: " ")),
                    detail: "已收集 \(item.newsCount) 条新闻；截止 \(String(item.endsAt.prefix(16).replacingOccurrences(of: "T", with: " ")))"
                        + (item.lastError.map { "；最近错误：\($0)" } ?? ""),
                    systemImage: investigationSymbol(item.status)
                )
            })
        }
    }
}
