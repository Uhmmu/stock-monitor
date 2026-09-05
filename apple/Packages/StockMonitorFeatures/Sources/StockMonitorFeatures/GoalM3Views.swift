import StockMonitorDesign
import SwiftUI
import UniformTypeIdentifiers
#if os(macOS)
    import AppKit
#endif

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
            OverviewView(model: OverviewModel(service: service), openStock: select)
        case .watchlist:
            WatchlistView(model: WatchlistModel(service: service), openStock: select)
        case .alerts:
            ActivityView(model: ActivityModel(service: service), openStock: select)
        case .news:
            NewsCenterView(model: NewsModel(service: service), openStock: select)
        case .calendar:
            InvestmentCalendarView(model: CalendarModel(service: service), openStock: select)
        case .reports:
            ReportsView(model: ReportsModel(service: service), openStock: select)
        default:
            CompanyEntryView(route: route, symbol: navigation.selectedSymbol, navigate: navigation.navigate)
        }
    }

    private func select(_ symbol: String) {
        navigation.selectedSymbol = symbol
        openStock(symbol)
    }
}

private struct SectionHeader: View {
    let title: String
    let subtitle: String?
    init(_ title: String, subtitle: String? = nil) {
        self.title = title; self.subtitle = subtitle
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

private struct FeatureErrorBanner: View {
    let error: M3FeatureError?
    var body: some View {
        if let error {
            Label(error.text, systemImage: "exclamationmark.triangle.fill")
                .font(.callout)
                .foregroundStyle(.orange)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(.orange.opacity(0.1), in: .rect(cornerRadius: 8))
                .accessibilityIdentifier("feature.error")
        }
    }
}

public struct OverviewView: View {
    @State private var model: OverviewModel
    @State private var exportingQuotes = false
    let openStock: (String) -> Void

    public init(model: OverviewModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model); self.openStock = openStock
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 22) {
                    HStack(alignment: .firstTextBaseline) {
                        SectionHeader("市场总览", subtitle: model.dashboard?.market.isOpen == true ? "美股常规交易时段" : "当前休市或非常规时段")
                        Spacer()
                        SemanticStatusLabel(model.streamConnected ? "实时连接" : "快照", status: model.streamConnected ? .live : .stale)
                        if let lastUpdated = model.lastUpdated {
                            Text(lastUpdated, style: .time).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    FeatureErrorBanner(error: model.error)
                    indexStrip
                    benchmarkStrip
                    quoteTable
                    HStack(alignment: .top, spacing: 20) {
                        recentAlerts.frame(maxWidth: .infinity, alignment: .topLeading)
                        recentReports.frame(maxWidth: .infinity, alignment: .topLeading)
                    }
                }
                .padding(24)
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

    @ViewBuilder private var benchmarkStrip: some View {
        if let benchmark = model.benchmark {
            VStack(alignment: .leading, spacing: 10) {
                SectionHeader("组合基准", subtitle: benchmark.configured ? benchmark.portfolioReturnSource : "尚未配置入市基准")
                HStack(spacing: 18) {
                    LabeledContent("组合", value: benchmark.portfolioReturnPercent.map { $0.formatted(.number.precision(.fractionLength(2))) + "%" } ?? "数据不足")
                    ForEach(benchmark.benchmarks.prefix(3)) { item in
                        LabeledContent(item.name, value: item.returnPercent.map { $0.formatted(.number.precision(.fractionLength(2))) + "%" } ?? item.message ?? "数据不足")
                    }
                }.monospacedDigit()
            }
        }
    }

    private var indexStrip: some View {
        HStack(spacing: 12) {
            ForEach(model.indices) { index in
                VStack(alignment: .leading, spacing: 4) {
                    Text(index.name).font(.caption).foregroundStyle(.secondary)
                    Text(index.price.map { $0.formatted(.number.precision(.fractionLength(2))) } ?? "数据不足")
                        .font(.title3.monospacedDigit().weight(.semibold))
                    ChangeLabel(value: index.changePercent)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(14)
                .background(.background.secondary, in: .rect(cornerRadius: 10))
            }
        }
    }

    private var quoteTable: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                SectionHeader("自选行情", subtitle: "快照恢复后接入单一 authenticated SSE")
                Spacer()
                Button("复制", systemImage: "doc.on.doc") { copyQuotes() }
                Button("导出", systemImage: "square.and.arrow.up") { exportingQuotes = true }
            }
            Table(dashboardStocks) {
                TableColumn("代码") { stock in Button(stock.ticker) { openStock(stock.ticker) }.buttonStyle(.plain).fontWeight(.semibold) }
                TableColumn("公司") { stock in Text(stock.companyName ?? "—").foregroundStyle(stock.companyName == nil ? .secondary : .primary) }
                TableColumn("价格") { stock in
                    let live = model.liveQuotes[stock.ticker]
                    Text((live?.price ?? stock.price)?.formatted(.number.precision(.fractionLength(2))) ?? "数据不足").monospacedDigit()
                }
                TableColumn("涨跌") { stock in
                    let live = model.liveQuotes[stock.ticker]
                    let change = live.flatMap { quote -> Double? in
                        guard let price = quote.price, let close = quote.previousClose, close != 0 else { return nil }
                        return (price / close - 1) * 100
                    } ?? stock.changePercent
                    ChangeLabel(value: change)
                }
                TableColumn("来源") { stock in Text(model.liveQuotes[stock.ticker]?.provider ?? stock.priceSource ?? "数据不足").foregroundStyle(.secondary) }
                TableColumn("状态") { stock in
                    let quote = model.liveQuotes[stock.ticker]
                    SemanticStatusLabel(quote?.isStale == false ? "Live" : "快照", status: quote?.isStale == false ? .live : .stale)
                }
            }
            .frame(minHeight: 260)
        }
    }

    private var dashboardStocks: [DashboardStock] {
        guard let dashboard = model.dashboard else { return [] }
        return dashboard.stocks
    }

    private var quoteCSV: String {
        let rows = dashboardStocks.map { stock in
            let quote = model.liveQuotes[stock.ticker]
            let price = quote?.price ?? stock.price
            let change = quote.flatMap { live -> Double? in
                guard let price = live.price, let close = live.previousClose, close != 0 else { return nil }
                return (price / close - 1) * 100
            } ?? stock.changePercent
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

    private var recentAlerts: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader("最近异动")
            ForEach(model.alerts) { alert in
                Button { openStock(alert.ticker) } label: {
                    HStack { Text(alert.ticker).fontWeight(.semibold); Text(alert.period).foregroundStyle(.secondary); Spacer(); ChangeLabel(value: alert.changePercent) }
                }.buttonStyle(.plain).padding(.vertical, 4)
            }
            if model.alerts.isEmpty {
                Text("暂无异动").foregroundStyle(.secondary)
            }
        }
    }

    private var recentReports: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader("最新报告")
            ForEach(model.reports) { report in
                HStack {
                    Text(report.ticker).fontWeight(.semibold); Text(report.title).lineLimit(1); Spacer(); if let confidence = report.confidence {
                        Text(confidence).foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 4)
            }
            if model.reports.isEmpty {
                Text("暂无报告").foregroundStyle(.secondary)
            }
        }
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

private struct ChangeLabel: View {
    let value: Double?
    var body: some View {
        if let value {
            (Text(value, format: .number.precision(.fractionLength(2)).sign(strategy: .always()).scale(1)) + Text("%"))
                .foregroundStyle(color)
        } else {
            Text("—")
        }
    }

    private var color: Color {
        (value ?? 0) > 0 ? .green : (value ?? 0) < 0 ? .red : .secondary
    }
}

public struct WatchlistView: View {
    @State private var model: WatchlistModel
    @Environment(\.undoManager) private var undoManager
    let openStock: (String) -> Void
    @State private var groupName = ""
    @State private var showingNewGroup = false
    @State private var showingGroupManager = false
    @State private var editingThresholds: ManagedStock?
    @State private var removeCandidate: ManagedStock?

    public init(model: WatchlistModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model); self.openStock = openStock
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            HSplitView {
                VStack(spacing: 0) {
                    searchBar
                    List(selection: $model.selectedSymbol) {
                        ForEach(groupedStocks, id: \.0) { group, stocks in
                            Section(group) {
                                ForEach(stocks) { stock in stockRow(stock).tag(stock.ticker) }
                                    .onMove { source, destination in Task { await model.move(from: source, to: destination) } }
                            }
                        }
                    }
                    FeatureErrorBanner(error: model.error).padding()
                }
                .frame(minWidth: 430)
                selectedDetail.frame(minWidth: 300, idealWidth: 360)
            }
        }
        .navigationTitle("自选股")
        .task { await model.load() }
        .onChange(of: model.searchQuery) { _, _ in model.search() }
        .onChange(of: model.selectedSymbol) { _, _ in Task { await model.loadPeers() } }
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
        .sheet(item: $editingThresholds) { stock in
            ThresholdEditor(stock: stock) { twenty, hour, day in
                Task { await model.updateThresholds(stock: stock, twentyMinutes: twenty, oneHour: hour, day: day) }
            }
        }
        .accessibilityIdentifier("m3.watchlist")
    }

    private var groupedStocks: [(String, [ManagedStock])] {
        let groups = Dictionary(uniqueKeysWithValues: (model.snapshot?.groups ?? []).map { ($0.id, $0.name) })
        return Dictionary(grouping: model.stocks) { $0.userGroupID.flatMap { groups[$0] } ?? "未分组" }
            .map { ($0.key, $0.value.sorted { $0.displayOrder < $1.displayOrder }) }.sorted { $0.0 < $1.0 }
    }

    private var searchBar: some View {
        VStack(spacing: 0) {
            TextField("搜索代码或公司", text: $model.searchQuery)
                .textFieldStyle(.roundedBorder).padding(12)
            if !model.searchResults.isEmpty {
                List(model.searchResults) { candidate in
                    HStack {
                        VStack(alignment: .leading) { Text(candidate.displaySymbol).fontWeight(.semibold); Text(candidate.displayName).font(.caption).foregroundStyle(.secondary) }
                        Spacer(); Text(candidate.exchange ?? candidate.market ?? "").font(.caption).foregroundStyle(.secondary)
                        Button("添加") { Task { await model.add(candidate) } }.buttonStyle(.bordered)
                        if model.selectedSymbol != nil {
                            Button("同行") { Task { await model.addPeer(candidate) } }.buttonStyle(.bordered)
                        }
                    }
                }.frame(height: min(CGFloat(model.searchResults.count) * 52, 260))
            }
        }
    }

    private func stockRow(_ stock: ManagedStock) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text(stock.ticker).fontWeight(.semibold); if stock.isPeerReferenced {
                        Image(systemName: "link").foregroundStyle(.secondary)
                    }
                }
                Text(stock.companyName ?? "名称数据不足").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(stock.price?.formatted(.number.precision(.fractionLength(2))) ?? "—").monospacedDigit()
            ChangeLabel(value: stock.changePercent).frame(width: 72, alignment: .trailing)
            if let id = stock.watchlistID, model.pendingIDs.contains(id) {
                ProgressView().controlSize(.small)
            }
        }
        .contentShape(.rect)
        .onTapGesture(count: 2) { openStock(stock.ticker) }
        .contextMenu {
            Button("打开公司入口") { openStock(stock.ticker) }
            Menu("移动到分组") { ForEach(model.snapshot?.groups ?? []) { group in Button(group.name) { Task { await model.assign(stock: stock, to: group.id) } } } }
            Button(stock.alertEnabled ? "关闭异动提醒" : "开启异动提醒") { Task { await model.setAlert(!stock.alertEnabled, stock: stock) } }
            Button("编辑异动阈值…") { editingThresholds = stock }
            Divider()
            Button("移除", role: .destructive) { removeCandidate = stock }
        }
    }

    @ViewBuilder private var selectedDetail: some View {
        if let symbol = model.selectedSymbol, let stock = model.stocks.first(where: { $0.ticker == symbol }) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    SectionHeader(stock.ticker, subtitle: stock.companyName)
                    HStack {
                        Button("公司入口") { openStock(stock.ticker) }.buttonStyle(.borderedProminent)
                        Toggle("行情监控", isOn: Binding(
                            get: { model.contractItems[stock.watchlistID ?? -1]?.enabled ?? true },
                            set: { value in Task { await model.setMonitoring(value, stock: stock) } }
                        ))
                        Toggle("异动提醒", isOn: Binding(get: { stock.alertEnabled }, set: { value in Task { await model.setAlert(value, stock: stock) } }))
                    }
                    LabeledContent("行业", value: stock.officialIndustry ?? "数据不足")
                    LabeledContent("20 分钟阈值", value: stock.threshold20m.map { "\($0)%" } ?? "默认")
                    Divider()
                    SectionHeader("同行样本", subtitle: "代码映射完全由服务端 Security entity 决定")
                    ForEach(model.peers) { peer in
                        HStack {
                            Text(peer.ticker).fontWeight(.medium)
                            Text(peer.source == "official" ? "官方" : "手动").font(.caption).foregroundStyle(.secondary)
                            Spacer()
                            Button(peer.source == "manual" ? "移除" : (peer.excluded ? "恢复" : "排除")) { Task { await model.togglePeer(peer) } }
                                .buttonStyle(.borderless)
                        }
                    }
                    if model.peers.isEmpty {
                        Text("暂无同行数据").foregroundStyle(.secondary)
                    }
                }.padding(20)
            }
        } else {
            ContentUnavailableView("选择一只证券", systemImage: "cursorarrow.click")
        }
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

private struct ThresholdEditor: View {
    let stock: ManagedStock
    let save: (Double?, Double?, Double?) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var twenty = ""
    @State private var hour = ""
    @State private var day = ""
    var body: some View {
        NavigationStack {
            Form {
                TextField("20 分钟（%）", text: $twenty)
                TextField("1 小时（%）", text: $hour)
                TextField("当日（%）", text: $day)
                Text("留空会沿用服务端默认值；所有阈值必须大于 0。")
                    .font(.caption).foregroundStyle(.secondary)
            }.formStyle(.grouped).padding()
                .navigationTitle("\(stock.ticker) 异动阈值")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("保存") { save(Double(twenty), Double(hour), Double(day)); dismiss() }
                            .disabled([twenty, hour, day].compactMap(Double.init).contains { $0 <= 0 })
                    }
                }
        }.frame(width: 460, height: 320)
            .onAppear {
                twenty = stock.threshold20m.map { String($0) } ?? ""
                hour = stock.threshold1h.map { String($0) } ?? ""
                day = stock.thresholdDay.map { String($0) } ?? ""
            }
    }
}

public struct ActivityView: View {
    @State private var model: ActivityModel
    let openStock: (String) -> Void
    public init(model: ActivityModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model); self.openStock = openStock
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            VStack(alignment: .leading, spacing: 14) {
                FeatureErrorBanner(error: model.error)
                Table(model.alerts) {
                    TableColumn("证券") { item in Button(item.ticker) { openStock(item.ticker) }.buttonStyle(.plain).fontWeight(.semibold) }
                    TableColumn("周期", value: \.period)
                    TableColumn("幅度") { ChangeLabel(value: $0.changePercent) }
                    TableColumn("触发时间", value: \.triggeredAt)
                }
                DisclosureGroup("调查任务（\(model.investigations.count)）") {
                    ForEach(model.investigations) { item in
                        HStack {
                            Text(item.ticker).fontWeight(.semibold)
                            Text(item.status)
                            Spacer()
                            Text("\(item.newsCount) 条新闻").foregroundStyle(.secondary)
                        }.padding(.vertical, 4)
                    }
                }
                if model.canLoadMore {
                    Button("加载更多") { Task { await model.load(reset: false) } }.frame(maxWidth: .infinity)
                }
            }.padding(20)
        }
        .navigationTitle("异动中心").task { await model.load() }.accessibilityIdentifier("m3.alerts")
    }
}

public struct NewsCenterView: View {
    @State private var model: NewsModel
    @State private var selected: NewsItem?
    let openStock: (String) -> Void
    public init(model: NewsModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model); self.openStock = openStock
    }

    public var body: some View {
        VStack(spacing: 0) {
            HStack {
                Picker("范围", selection: $model.scope) { ForEach(NewsModel.Scope.allCases) { Text($0.rawValue).tag($0) } }.pickerStyle(.segmented).frame(width: 180)
                if model.scope == .company {
                    TextField("证券代码", text: $model.symbol).textFieldStyle(.roundedBorder).frame(width: 120)
                }
                TextField("主题筛选", text: $model.topic).textFieldStyle(.roundedBorder).frame(width: 180).disabled(model.scope == .company)
                Button("应用") { Task { await model.load() } }
                Spacer(); Text("\(model.total) 条").foregroundStyle(.secondary)
            }.padding(12)
            FeatureErrorBanner(error: model.error).padding(.horizontal)
            List(model.items, selection: Binding(get: { selected?.id }, set: { id in selected = model.items.first { $0.id == id } })) { item in
                VStack(alignment: .leading, spacing: 6) {
                    Text(item.displayTitle).font(.headline).lineLimit(2)
                    HStack {
                        Text(item.provider); if let ticker = item.ticker {
                            Button(ticker) { openStock(ticker) }.buttonStyle(.plain)
                        }; Spacer(); Text(item.timestamp)
                    }
                    .font(.caption).foregroundStyle(.secondary)
                    Text(item.aiSummary ?? item.summary ?? "摘要数据不足").lineLimit(3).foregroundStyle(.secondary)
                }.padding(.vertical, 6).tag(item.id).onTapGesture { selected = item }
            }
            if model.canLoadMore {
                Button("加载更多") { Task { await model.load(reset: false) } }.padding(8)
            }
        }
        .navigationTitle("新闻中心").task { await model.load() }
        .sheet(item: $selected) { item in NewsReader(item: item, summarize: { Task { await model.summarize(item) } }).frame(minWidth: 680, minHeight: 560) }
        .accessibilityIdentifier("m3.news")
    }
}

private struct NewsReader: View {
    let item: NewsItem
    let summarize: () -> Void
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text(item.displayTitle).font(.largeTitle.bold())
                    HStack {
                        Text(item.provider); Text(item.timestamp); Spacer(); if let raw = item.url, let url = URL(string: raw) {
                            ConfirmedExternalLink(url: url)
                        }
                    }.foregroundStyle(.secondary)
                    Divider()
                    if let summary = item.aiSummary {
                        Text("AI 摘要").font(.headline); SafeMarkdownText(summary)
                    } else {
                        Button("生成一次 AI 摘要", action: summarize).buttonStyle(.borderedProminent); Text(item.summary ?? "正文与摘要数据不足").foregroundStyle(.secondary)
                    }
                    if let analysis = item.aiAnalysis {
                        Text("分析").font(.headline); SafeMarkdownText(analysis.displayText)
                    }
                }.padding(28).frame(maxWidth: 820, alignment: .leading)
            }
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() } } }
        }
    }
}

public struct InvestmentCalendarView: View {
    @State private var model: CalendarModel
    let openStock: (String) -> Void
    public init(model: CalendarModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model); self.openStock = openStock
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            VStack(spacing: 10) {
                FeatureErrorBanner(error: model.error)
                Table(model.items) {
                    TableColumn("日期", value: \.eventDate)
                    TableColumn("证券") {
                        event in if let symbol = event.symbol {
                            Button(symbol) { openStock(symbol) }.buttonStyle(.plain)
                        } else {
                            Text("市场")
                        }
                    }
                    TableColumn("事件", value: \.title)
                    TableColumn("类型", value: \.eventType)
                    TableColumn("影响") { event in
                        SemanticStatusLabel(
                            event.impactLevel,
                            status: event.impactLevel == "critical" || event.impactLevel == "high" ? .warning : .unavailable
                        )
                    }
                    TableColumn("来源") { event in VStack(alignment: .leading) {
                        Text(event.primarySource); if event.stale {
                            Text("旧缓存").font(.caption).foregroundStyle(.orange)
                        }
                    } }
                }
                if model.nextCursor != nil {
                    Button("加载更多") { Task { await model.load(reset: false) } }
                }
            }.padding(16)
        }
        .navigationTitle("投资日历").task { await model.load() }.accessibilityIdentifier("m3.calendar")
    }
}

public struct ReportsView: View {
    @State private var model: ReportsModel
    let openStock: (String) -> Void
    public init(model: ReportsModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model); self.openStock = openStock
    }

    public var body: some View {
        HSplitView {
            VStack(spacing: 0) {
                List(model.reports, selection: Binding(get: { model.selected?.id }, set: {
                    id in if let report = model.reports.first(where: { $0.id == id }) {
                        Task { await model.select(report) }
                    }
                })) { report in
                    VStack(alignment: .leading, spacing: 4) { Text(report.title).fontWeight(.medium); HStack {
                        Text(report.ticker); Text(report.createdAt); if let confidence = report.confidence {
                            Text("置信度 \(confidence)")
                        }
                    }.font(.caption).foregroundStyle(.secondary) }.tag(report.id)
                }
                if model.canLoadMore {
                    Button("加载更多") { Task { await model.load(reset: false) } }.padding(8)
                }
            }.frame(minWidth: 300, idealWidth: 380)
            ScrollView {
                if let report = model.selected {
                    VStack(alignment: .leading, spacing: 14) {
                        Text(report.title).font(.largeTitle.bold())
                        HStack {
                            Button(report.ticker) { openStock(report.ticker) }.buttonStyle(.plain); Text(report.createdAt); if let source = report.model {
                                Text(source)
                            }
                        }.foregroundStyle(.secondary)
                        Divider(); SafeMarkdownText(report.content)
                    }.padding(28).frame(maxWidth: 860, alignment: .leading)
                } else {
                    ContentUnavailableView("选择一份报告", systemImage: "doc.richtext")
                }
            }.frame(minWidth: 420)
        }
        .overlay(alignment: .top) { FeatureErrorBanner(error: model.error).padding() }
        .navigationTitle("报告中心").task { await model.load() }.accessibilityIdentifier("m3.reports")
    }
}

private struct SafeMarkdownText: View {
    let text: String
    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        let value = (try? AttributedString(markdown: text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(text)
        Text(value).textSelection(.enabled).lineSpacing(4)
    }
}

private struct ConfirmedExternalLink: View {
    let url: URL
    @State private var showingConfirmation = false
    @Environment(\.openURL) private var openURL
    var body: some View {
        Button("打开原文", systemImage: "arrow.up.right.square") { showingConfirmation = true }
            .confirmationDialog("打开外部网站？", isPresented: $showingConfirmation) {
                Button("打开 \(url.host ?? url.absoluteString)") { openURL(url) }
                Button("取消", role: .cancel) {}
            } message: { Text(url.host ?? url.absoluteString) }
    }
}

private struct CompanyEntryView: View {
    let route: AppRoute
    let symbol: String?
    let navigate: (AppRoute) -> Void
    private let destinations: [AppRoute] = [.news, .fundamentals, .valuation, .technical, .sec, .holdings, .compare, .ai]
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            SectionHeader(symbol ?? route.title, subtitle: symbol == nil ? "请先从总览或自选股选择证券" : "统一公司研究入口")
            if symbol != nil {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 150))], spacing: 12) {
                    ForEach(destinations) { destination in
                        Button { navigate(destination) } label: {
                            Label(destination.title, systemImage: destination.systemImage)
                                .frame(maxWidth: .infinity, alignment: .leading).padding(8)
                        }.buttonStyle(.bordered)
                    }
                }
            }
        }.padding(28).frame(maxWidth: 780, alignment: .topLeading).navigationTitle(route.title)
    }
}
