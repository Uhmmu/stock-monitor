import StockMonitorDesign
import SwiftUI
#if os(macOS)
    import AppKit
#endif

// MARK: - 新闻中心（R4.1：标题主导 + 分层详情）

public struct NewsCenterView: View {
    @State private var model: NewsModel
    @State private var selected: NewsItem?
    @Bindable private var navigation: AppNavigationModel
    let openStock: (String) -> Void
    public init(model: NewsModel, navigation: AppNavigationModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model); self.navigation = navigation; self.openStock = openStock
    }

    public var body: some View {
        VStack(spacing: 0) {
            PageHeader("新闻中心", eyebrow: "Market Intelligence", summary: "标题优先，证券、来源、时间与 AI 内容保持清晰分层。") {
                SemanticStatusLabel("\(model.total) 条", status: model.items.isEmpty ? .unavailable : .info)
            }
            .padding(.horizontal, StockMonitorSpacing.medium)
            .padding(.top, StockMonitorSpacing.medium)
            filterBar
            FeatureErrorBanner(error: model.error).padding(.horizontal, StockMonitorSpacing.regular)
            List(model.items, selection: selectedBinding) { item in
                NewsListRow(item: item, openStock: openStock)
                    .tag(item.id)
                    .onTapGesture { selected = item }
            }
            .alternatingRowBackgrounds(.disabled)
            if model.canLoadMore {
                Button("加载更多") { Task { await model.load(reset: false) } }.padding(StockMonitorSpacing.small)
            }
        }
        .navigationTitle("新闻中心").task {
            restoreInteractionState()
            await model.load()
            restoreSelection()
        }
        .onChange(of: model.scope) { _, _ in persistFilters() }
        .onChange(of: model.symbol) { _, _ in persistFilters() }
        .onChange(of: model.topic) { _, _ in persistFilters() }
        .onChange(of: selected) { _, value in navigation.rememberSelection(value.map { String($0.id) }, for: .news) }
        .sheet(item: $selected) { item in
            NewsReader(item: item, summarize: { Task { await model.summarize(item) } }).frame(minWidth: 680, minHeight: 560)
        }
        .accessibilityIdentifier("m3.news")
    }

    private func restoreInteractionState() {
        let state = navigation.state(for: .news)
        let parts = state.filterQuery.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
        if let scope = parts.first.flatMap(NewsModel.Scope.init(rawValue:)) {
            model.scope = scope
        }
        if parts.count > 1, !parts[1].isEmpty {
            model.symbol = parts[1]
        }
        if parts.count > 2 {
            model.topic = parts[2]
        }
    }

    private func restoreSelection() {
        guard let raw = navigation.state(for: .news).selectedIdentifier, let id = Int(raw) else { return }
        selected = model.items.first { $0.id == id }
    }

    private func persistFilters() {
        navigation.updateState(for: .news) {
            $0.filterQuery = [model.scope.rawValue, model.symbol, model.topic].joined(separator: "|")
        }
    }

    private var selectedBinding: Binding<Int?> {
        Binding(
            get: { selected?.id },
            set: { id in selected = model.items.first { $0.id == id } }
        )
    }

    private var filterBar: some View {
        HStack(spacing: StockMonitorSpacing.regular) {
            Picker("范围", selection: $model.scope) { ForEach(NewsModel.Scope.allCases) { Text($0.rawValue).tag($0) } }
                .pickerStyle(.segmented)
                .frame(width: 180)
            if model.scope == .company {
                TextField("证券代码", text: $model.symbol).textFieldStyle(.roundedBorder).frame(width: 120)
            }
            TextField("主题筛选", text: $model.topic).textFieldStyle(.roundedBorder).frame(width: 180).disabled(model.scope == .company)
            Button("应用") { Task { await model.load() } }
            Spacer()
            Text("\(model.total) 条").stockMonitorTypography(.metadata)
        }
        .stockMonitorFilterBar()
        .padding(StockMonitorSpacing.regular)
        .accessibilityIdentifier("r4.news.filters")
    }
}

/// 新闻行：标题主导；证券、来源、时间与 AI 状态是次级 metadata，不挤压主标题。
struct NewsListRow: View {
    let item: NewsItem
    let openStock: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
            Text(item.displayTitle)
                .font(.headline)
                .lineLimit(2)
            HStack(spacing: StockMonitorSpacing.regular) {
                if let ticker = item.ticker {
                    Button(ticker) { openStock(ticker) }.buttonStyle(.plain).fontWeight(.medium)
                }
                Text(item.provider).stockMonitorTypography(.metadata)
                Text(String(item.timestamp.prefix(16).replacingOccurrences(of: "T", with: " "))).stockMonitorTypography(.metadata)
                aiBadge
            }
            Text(item.aiSummary ?? item.summary ?? "摘要数据不足")
                .stockMonitorTypography(.body)
                .foregroundStyle(.secondary)
                .lineLimit(3)
        }
        .padding(.vertical, StockMonitorSpacing.small)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(item.displayTitle)，\(item.provider)")
    }

    @ViewBuilder private var aiBadge: some View {
        switch item.aiSummaryStatus {
        case "ready", "done":
            SemanticStatusLabel("AI 摘要", status: .info)
        case "pending", "running":
            SemanticStatusLabel("AI 摘要生成中", status: .stale)
        case "failed":
            SemanticStatusLabel("AI 摘要失败", status: .warning)
        default:
            EmptyView()
        }
    }
}

private struct NewsReader: View {
    let item: NewsItem
    let summarize: () -> Void
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
                    Text(item.displayTitle).font(.title2.weight(.semibold)).textSelection(.enabled)
                    HStack(spacing: StockMonitorSpacing.regular) {
                        if let ticker = item.ticker {
                            Text(ticker).fontWeight(.medium)
                        }
                        Text(item.provider).stockMonitorTypography(.metadata)
                        Text(String(item.timestamp.prefix(19).replacingOccurrences(of: "T", with: " "))).stockMonitorTypography(.metadata)
                        Spacer()
                        if let raw = item.url, let url = URL(string: raw) {
                            ConfirmedExternalLink(url: url)
                        }
                    }
                    Divider()
                    if let summary = item.aiSummary {
                        DisclosureSection("AI 摘要（模型生成）", expanded: true) {
                            SafeMarkdownText(summary)
                        }
                        .stockMonitorSurface(.grouped)
                    } else {
                        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
                            Button("生成一次 AI 摘要", action: summarize).buttonStyle(.borderedProminent)
                            Text("AI 摘要由服务端模型生成，与原文摘要分层展示。").stockMonitorTypography(.metadata)
                        }
                    }
                    if let summary = item.summary {
                        DisclosureSection("原文摘要", expanded: true) {
                            SafeMarkdownText(summary)
                        }
                    }
                    if let analysis = item.aiAnalysis {
                        DisclosureSection("AI 分析（模型生成）") {
                            SafeMarkdownText(analysis.displayText)
                        }
                        .stockMonitorSurface(.grouped)
                    }
                }
                .padding(StockMonitorSpacing.xLarge)
                .frame(maxWidth: StockMonitorContentWidth.readable, alignment: .leading)
            }
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() } } }
        }
        .accessibilityIdentifier("r4.news.reader")
    }
}

// MARK: - 投资日历（R4.1：agenda 分组 + 类型符号语义）

public struct InvestmentCalendarView: View {
    @State private var model: CalendarModel
    let openStock: (String) -> Void
    public init(model: CalendarModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model); self.openStock = openStock
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            PageScaffold(width: StockMonitorContentWidth.wide) {
                PageHeader("投资日历", summary: "按日议程分组；事件类型同时提供符号与文字。") {
                    SemanticStatusLabel("\(model.items.count) 条事件", status: model.items.isEmpty ? .unavailable : .info)
                }
            } content: {
                FeatureErrorBanner(error: model.error)
                calendarSummary
                agenda
                if model.nextCursor != nil {
                    Button("加载更多") { Task { await model.load(reset: false) } }
                }
            }
        }
        .navigationTitle("投资日历").task { await model.load() }.accessibilityIdentifier("m3.calendar")
    }

    private var pendingConfirmation: Int {
        model.items.filter { !$0.isConfirmed && $0.isEstimated }.count
    }

    private var staleCount: Int {
        model.items.filter(\.stale).count
    }

    private var calendarSummary: some View {
        let symbols = Set(model.items.compactMap(\.symbol))
        return MetricGrid([
            .init(label: "事件总数", value: .init(text: "\(model.items.count) 条"), status: .neutral),
            .init(label: "覆盖证券", value: .init(text: "\(symbols.count) 只"), status: .neutral),
            .init(label: "待确认", value: .init(text: "\(pendingConfirmation) 条"), status: pendingConfirmation > 0 ? .warning : .live),
            .init(label: "旧缓存", value: .init(text: "\(staleCount) 条"), status: staleCount > 0 ? .stale : .live),
        ])
    }

    @ViewBuilder private var agenda: some View {
        let days = CalendarAgendaBuilder.days(model.items)
        if days.isEmpty {
            EmptyState("暂无已追踪事件", systemImage: "calendar.badge.exclamationmark", description: "日历只覆盖自选与持仓相关证券，不是全市场。")
        } else {
            ForEach(days) { day in
                SectionHeader(day.date, explanation: "\(day.events.count) 条事件")
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(day.events) { event in
                        CalendarAgendaRow(event: event, openStock: openStock)
                        Divider()
                    }
                }
            }
        }
    }
}

// MARK: - 报告中心（R4.1：搜索 + 目录 + 复制 + 回证券）

public struct ReportsView: View {
    @State private var model: ReportsModel
    @State private var searchText = ""
    let openStock: (String) -> Void
    public init(model: ReportsModel, openStock: @escaping (String) -> Void) {
        _model = State(initialValue: model); self.openStock = openStock
    }

    public var body: some View {
        HSplitView {
            VStack(spacing: 0) {
                searchField
                Divider()
                List(filteredReports, selection: reportSelection) { report in
                    ReportListRow(report: report).tag(report.id)
                }
                if model.canLoadMore {
                    Button("加载更多") { Task { await model.load(reset: false) } }.padding(StockMonitorSpacing.small)
                }
            }.frame(minWidth: 300, idealWidth: 380)
            reportDetail
                .frame(minWidth: 420)
        }
        .overlay(alignment: .top) { FeatureErrorBanner(error: model.error).padding(StockMonitorSpacing.regular) }
        .navigationTitle("报告中心").task { await model.load() }.accessibilityIdentifier("m3.reports")
    }

    private var reportSelection: Binding<Int?> {
        Binding(
            get: { model.selected?.id },
            set: { id in
                guard let report = model.reports.first(where: { $0.id == id }) else { return }
                Task { await model.select(report) }
            }
        )
    }

    private var filteredReports: [ReportSummary] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return model.reports }
        return model.reports.filter {
            $0.title.localizedCaseInsensitiveContains(query) || $0.ticker.localizedCaseInsensitiveContains(query)
        }
    }

    private var searchField: some View {
        HStack(spacing: StockMonitorSpacing.small) {
            TextField("搜索标题或代码", text: $searchText)
                .textFieldStyle(.roundedBorder)
            Text("\(filteredReports.count) 份").stockMonitorTypography(.metadata)
        }
        .padding(StockMonitorSpacing.regular)
    }

    @ViewBuilder private var reportDetail: some View {
        if let report = model.selected {
            ReportReaderView(report: report, openStock: openStock)
        } else {
            ContentUnavailableView("选择一份报告", systemImage: "doc.richtext", description: Text("左侧列表支持按标题或代码过滤；选中后可查看目录与全文。"))
        }
    }
}

struct ReportListRow: View {
    let report: ReportSummary

    var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
            Text(report.title).fontWeight(.medium).lineLimit(2)
            HStack(spacing: StockMonitorSpacing.regular) {
                Text(report.ticker).fontWeight(.medium)
                Text(String(report.createdAt.prefix(10))).stockMonitorTypography(.metadata)
                if let confidence = report.confidence {
                    Text("置信度 \(confidence)").stockMonitorTypography(.metadata)
                }
            }
        }
        .padding(.vertical, StockMonitorSpacing.xSmall)
        .accessibilityElement(children: .combine)
    }
}

/// 报告阅读：目录跳转、复制全文、回到关联证券；加载更多不动阅读位置。
struct ReportReaderView: View {
    let report: ReportDetail
    let openStock: (String) -> Void

    private var sections: [ReportSectionParser.Section] {
        ReportSectionParser.sections(from: report.content)
    }

    /// 目录条目与 section 锚点一一对应：只有带标题的 section 进入目录。
    private var outlineEntries: [ReportOutlineAnchor] {
        sections.enumerated().compactMap { index, section in
            guard let heading = section.heading, let level = section.level else { return nil }
            return ReportOutlineAnchor(anchor: "report-section-\(index)", level: level, title: heading)
        }
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: StockMonitorSpacing.regular) {
                    Text(report.title).font(.title2.weight(.semibold)).textSelection(.enabled)
                    HStack(spacing: StockMonitorSpacing.regular) {
                        Button(report.ticker) { openStock(report.ticker) }.buttonStyle(.plain).fontWeight(.medium)
                        Text(String(report.createdAt.prefix(19).replacingOccurrences(of: "T", with: " "))).stockMonitorTypography(.metadata)
                        if let model = report.model, !model.isEmpty {
                            Text(model).stockMonitorTypography(.metadata)
                        }
                        Spacer()
                        Button("复制全文", systemImage: "doc.on.doc") { copyContent(report.content) }
                        Button("回到证券", systemImage: "chart.line.uptrend.xyaxis") { openStock(report.ticker) }
                    }
                    Divider()
                    outline(proxy: proxy)
                    ForEach(Array(sections.enumerated()), id: \.offset) { index, section in
                        ReportSectionView(section: section, anchor: "report-section-\(index)")
                    }
                }
                .padding(StockMonitorSpacing.xLarge)
                .frame(maxWidth: StockMonitorContentWidth.readable + 80, alignment: .leading)
            }
        }
        .accessibilityIdentifier("r4.reports.reader")
    }

    @ViewBuilder
    private func outline(proxy: ScrollViewProxy) -> some View {
        if outlineEntries.count >= 2 {
            DisclosureSection("目录（\(outlineEntries.count) 节）", expanded: true) {
                VStack(alignment: .leading, spacing: StockMonitorSpacing.xSmall) {
                    ForEach(outlineEntries) { entry in
                        Button {
                            withAnimation(StockMonitorMotion.responsive) {
                                proxy.scrollTo(entry.anchor, anchor: .top)
                            }
                        } label: {
                            HStack(spacing: StockMonitorSpacing.small) {
                                Text(String(repeating: "· ", count: max(0, entry.level - 1)))
                                Text(entry.title).lineLimit(1)
                            }
                            .stockMonitorTypography(.metadata)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(.rect)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private func copyContent(_ text: String) {
        #if os(macOS)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(text, forType: .string)
        #endif
    }
}

/// 把 markdown 按标题切成 section，标题视图成为目录锚点。
enum ReportSectionParser {
    struct Section {
        let heading: String?
        let level: Int?
        let body: String
    }

    static func sections(from markdown: String) -> [Section] {
        var results: [Section] = []
        var currentHeading: String?
        var currentLevel: Int?
        var body: [String] = []
        func flush() {
            guard currentHeading != nil || !body.isEmpty else { return }
            results.append(Section(heading: currentHeading, level: currentLevel, body: body.joined(separator: "\n")))
            body = []
        }
        for line in markdown.split(separator: "\n", omittingEmptySubsequences: false) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("#"), (1 ... 4).contains(trimmed.prefix { $0 == "#" }.count) {
                flush()
                let level = trimmed.prefix { $0 == "#" }.count
                currentHeading = trimmed.dropFirst(level).trimmingCharacters(in: .whitespaces)
                currentLevel = level
            } else {
                body.append(String(line))
            }
        }
        flush()
        return results
    }
}

struct ReportSectionView: View {
    let section: ReportSectionParser.Section
    let anchor: String

    var body: some View {
        VStack(alignment: .leading, spacing: StockMonitorSpacing.small) {
            if let heading = section.heading, let level = section.level {
                Text(heading)
                    .font(level <= 2 ? .title3.weight(.semibold) : .headline)
                    .textSelection(.enabled)
            }
            if !section.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                SafeMarkdownText(section.body)
            }
        }
        .id(anchor)
        .accessibilityElement(children: .contain)
    }
}

/// 报告目录锚点条目。
struct ReportOutlineAnchor: Identifiable, Equatable {
    let anchor: String
    let level: Int
    let title: String

    var id: String {
        anchor
    }
}

struct SafeMarkdownText: View {
    let text: String
    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        let value = (try? AttributedString(markdown: text, options: options)) ?? AttributedString(text)
        Text(value).textSelection(.enabled).lineSpacing(4)
    }
}

struct ConfirmedExternalLink: View {
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
