import Charts
import StockMonitorCore
import StockMonitorDesign
import SwiftUI

// MARK: - AI 情绪台 + 历史健康

@MainActor
@Observable
public final class MoodModel {
    public enum Tab: String, CaseIterable, Identifiable {
        case overview = "情绪总览"
        case health = "历史健康"
        public var id: Self {
            self
        }
    }

    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var tab: Tab = .overview
    public private(set) var overview: MoodOverview?
    public private(set) var health: MoodHistoryHealth?
    public private(set) var gaps: MoodHistoryGaps?
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService
    private var pollingTask: Task<Void, Never>?

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func select(_ tab: Tab) {
        self.tab = tab
    }

    public func loadOverview() async {
        state = overview == nil ? .loading : .refreshing
        do {
            overview = try await service.moodOverview()
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = overview == nil ? .error : .stale
        }
    }

    public func loadHealth() async {
        do {
            async let health = service.moodHistoryHealth()
            async let gaps = service.moodHistoryGaps()
            let values = try await (health, gaps)
            self.health = values.0
            self.gaps = values.1
        } catch {
            self.error = .from(error)
        }
    }
}

public struct MoodView: View {
    @State private var model: MoodModel

    init(model: MoodModel) {
        _model = State(initialValue: model)
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    M4SectionHeader("AI 情绪台", subtitle: "规则化情绪快照；不足时显示数据不足")
                    Spacer()
                    Picker("分区", selection: Binding(get: { model.tab }, set: { model.select($0) })) {
                        ForEach(MoodModel.Tab.allCases) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented).frame(width: 240)
                }
                .padding(20)
                FeatureErrorBanner(error: model.error).padding(.horizontal, 20)
                Group {
                    switch model.tab {
                    case .overview: overviewTab
                    case .health: healthTab
                    }
                }
                .padding(.horizontal, 20).padding(.bottom, 20)
            }
        }
        .navigationTitle("AI 情绪台")
        .task { await model.loadOverview() }
        .accessibilityIdentifier("m4.mood")
    }

    @ViewBuilder
    private var overviewTab: some View {
        if let overview = model.overview {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 16) {
                        if let asOf = overview.asOf {
                            LabeledContent("数据截至", value: String(asOf.prefix(10)))
                        }
                        if let market = overview.market {
                            SemanticStatusLabel(market.state ?? "—", status: moodStatus(market.state))
                            if let score = market.moodScore {
                                LabeledContent("评分", value: score.formatted(.number.precision(.fractionLength(1))))
                            }
                        }
                    }.font(.callout)
                    sectorList("板块情绪", overview.sectors)
                    sectorList("AI 产业链情绪", overview.aiChain)
                    DisclosureGroup("涨跌与拥挤信号") {
                        JSONEvidenceView(value: overview.movers).padding(.top, 6)
                    }
                    .font(.headline)
                    DisclosureGroup("背离与状态迁移") {
                        JSONEvidenceView(value: overview.divergences).padding(.top, 6)
                        JSONEvidenceView(value: overview.transitions).padding(.top, 6)
                    }
                    .font(.headline)
                    DisclosureGroup("报告摘要") {
                        JSONEvidenceView(value: overview.report).padding(.top, 6)
                    }
                    .font(.headline)
                }.padding(4)
            }
        } else {
            ContentUnavailableView("情绪数据不足", systemImage: "waveform.path.ecg")
        }
    }

    private func sectorList(_ title: String, _ items: [MoodSnapshotItem]) -> some View {
        DisclosureGroup("\(title)（\(items.count)）") {
            ForEach(items.prefix(30)) { item in
                HStack {
                    Text(item.nameZh ?? item.name ?? item.scopeKey).fontWeight(.medium)
                    Spacer()
                    SemanticStatusLabel(item.state ?? "—", status: moodStatus(item.state))
                    if let score = item.moodScore {
                        Text(score.formatted(.number.precision(.fractionLength(1)))).monospacedDigit()
                    }
                    Text(item.direction == "up" ? "↑" : item.direction == "down" ? "↓" : "—")
                        .foregroundStyle(item.direction == "up" ? .green : item.direction == "down" ? .red : .secondary)
                }
                .font(.callout).padding(.vertical, 2)
            }
            if items.count > 30 {
                Text("仅展示前 30 项（共 \(items.count) 项）").font(.caption).foregroundStyle(.secondary)
            }
        }
        .font(.headline)
    }

    private func moodStatus(_ state: String?) -> SemanticStatusLabel.Status {
        switch state {
        case "LEADERSHIP", "TRENDING_UP": .live
        case "CROWDED", "STRETCHED": .warning
        default: .unavailable
        }
    }

    private var healthTab: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let health = model.health {
                    HStack(spacing: 16) {
                        LabeledContent("健康状态", value: health.healthStatus ?? "数据不足")
                        LabeledContent("历史天数", value: "\(health.historyDays ?? 0)")
                        LabeledContent("完整天数", value: "\(health.completeDays ?? 0)")
                        if let partial = health.partialDays {
                            LabeledContent("部分天数", value: "\(partial)")
                        }
                    }.font(.callout)
                    DisclosureGroup("最近运行") {
                        JSONEvidenceView(value: health.run).padding(.top, 6)
                    }
                    .font(.headline)
                    DisclosureGroup("交易日历健康") {
                        JSONEvidenceView(value: health.calendar).padding(.top, 6)
                    }
                    .font(.headline)
                } else {
                    Text("历史健康数据不足").foregroundStyle(.secondary)
                }
                if let gaps = model.gaps {
                    DisclosureGroup("缺口状态（\(gaps.status ?? "—")）") {
                        JSONEvidenceView(value: gaps.gaps).padding(.top, 6)
                    }
                    .font(.headline)
                }
            }.padding(4)
        }
        .task {
            if model.health == nil {
                await model.loadHealth()
            }
        }
    }
}

// MARK: - 管理员 Mood Lab

@MainActor
@Observable
public final class MoodLabModel {
    public private(set) var state: ResourcePresentationState = .loading
    public private(set) var overview: MoodValidationOverview?
    public private(set) var runs: [MoodValidationRun] = []
    public private(set) var results: [MoodValidationResultItem] = []
    public private(set) var selectedRunID: Int?
    public private(set) var starting = false
    public private(set) var recoveryNotice: String?
    public private(set) var gaps: MoodHistoryGaps?
    public private(set) var error: M3FeatureError?
    public let service: ResearchWorkspaceService
    private var pollingTask: Task<Void, Never>?

    public init(service: ResearchWorkspaceService) {
        self.service = service
    }

    public func load() async {
        state = overview == nil ? .loading : .refreshing
        do {
            async let overview = service.moodLabOverview()
            async let runs = service.moodLabRuns()
            async let gaps = service.moodHistoryGaps()
            let values = try await (overview, runs, gaps)
            self.overview = values.0
            self.runs = values.1.runs
            self.gaps = values.2
            if selectedRunID == nil {
                selectedRunID = values.0.run?.runID
            }
            state = .ready
            error = nil
        } catch {
            self.error = .from(error)
            state = overview == nil ? .error : .stale
        }
    }

    public func startRun() async {
        starting = true
        defer { starting = false }
        do {
            let run = try await service.startMoodLabRun(
                request: MoodValidationRunRequest(
                    dateFrom: nil, dateTo: nil,
                    scopes: ["market", "sector", "ai_chain", "watchlist"],
                    horizons: [1, 5, 10, 20, 60]
                )
            )
            recoveryNotice = run.queued == true ? "已排队新验证任务 #\(run.runID)。" : "已有任务在执行，复用任务 #\(run.runID)。"
            await load()
            pollActiveRun()
        } catch {
            self.error = .from(error)
        }
    }

    /// active-only 指数退避轮询：任务进入终态后立即停止，不产生后台常驻请求。
    private func pollActiveRun() {
        pollingTask?.cancel()
        pollingTask = Task { [weak self] in
            let policy = ActiveJobPollingPolicy()
            var attempt = 0
            while !Task.isCancelled {
                guard let self else { return }
                guard let active = runs.first(where: { $0.status == "pending" || $0.status == "running" }) ?? overview?.run,
                      let status = active.status
                else { return }
                guard let asyncStatus = AsyncJobStatus(rawValue: status),
                      let delay = policy.delay(afterAttempt: attempt, status: asyncStatus)
                else {
                    await load()
                    return
                }
                try? await Task.sleep(for: .seconds(delay))
                guard !Task.isCancelled else { return }
                await load()
                attempt += 1
                if attempt > 40 {
                    return
                }
            }
        }
    }

    public func select(runID: Int) async {
        selectedRunID = runID
        do {
            results = try await service.moodLabResults(runID: runID).results
        } catch {
            self.error = .from(error)
        }
    }

    public func recover(tradingDate: String, scopes: [String], reason: String) async {
        do {
            let result = try await service.recoverMoodHistory(
                request: MoodRecoveryRequest(tradingDate: tradingDate, scopes: scopes, reason: reason)
            )
            recoveryNotice = "恢复结果：" + result.displayText
        } catch {
            self.error = .from(error)
        }
    }
}

public struct MoodLabView: View {
    @State private var model: MoodLabModel
    @State private var recoveryDate = ""
    @State private var recoveryScopes = "market"
    @State private var recoveryReason = ""

    init(model: MoodLabModel) {
        _model = State(initialValue: model)
    }

    public var body: some View {
        ResourceStateView(state: model.state) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    M4SectionHeader("Mood 验证实验室", subtitle: "创建验证任务与历史恢复需要管理员权限；读取端点对所有登录用户开放")
                    HStack {
                        Button("开始新验证") { Task { await model.startRun() } }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.starting)
                        if model.starting {
                            ProgressView().controlSize(.small)
                        }
                        Button("刷新") { Task { await model.load() } }
                    }
                    if let notice = model.recoveryNotice {
                        Label(notice, systemImage: "info.circle").font(.callout).foregroundStyle(.secondary)
                    }
                    if let overview = model.overview {
                        HStack(spacing: 16) {
                            LabeledContent("状态", value: overview.status ?? "数据不足")
                            if let run = overview.run {
                                LabeledContent("任务", value: "#\(run.runID)")
                                LabeledContent("进度", value: "\(Int((run.progress ?? 0) * 100))%")
                            }
                        }.font(.callout)
                        DisclosureGroup("研究汇总") {
                            JSONEvidenceView(value: overview.studies).padding(.top, 6)
                        }
                        .font(.headline)
                        if let warnings = overview.warnings, !warnings.isEmpty {
                            Label(warnings.joined(separator: "；"), systemImage: "exclamationmark.triangle")
                                .font(.caption).foregroundStyle(.orange)
                        }
                    }
                    runsTable
                    resultsSection
                    recoverySection
                }
                .padding(24)
            }
        }
        .navigationTitle("Mood 验证实验室")
        .task { await model.load() }
        .overlay(alignment: .top) { FeatureErrorBanner(error: model.error).padding() }
        .accessibilityIdentifier("m4.mood-lab")
    }

    private var runsTable: some View {
        VStack(alignment: .leading, spacing: 8) {
            M4SectionHeader("验证任务")
            Table(model.runs) {
                TableColumn("任务") { run in Text("#\(run.runID)") }
                TableColumn("状态") { run in Text(run.status ?? "—") }
                TableColumn("进度") { run in
                    Text(run.progress.map { "\(Int($0 * 100))%" } ?? "数据不足").monospacedDigit()
                }
                TableColumn("创建") { run in
                    Text(run.createdAt.map { String($0.prefix(19).replacingOccurrences(of: "T", with: " ")) } ?? "—")
                }
                TableColumn("完成") { run in
                    Text(run.completedAt.map { String($0.prefix(19).replacingOccurrences(of: "T", with: " ")) } ?? "—")
                }
                TableColumn("结果") { run in
                    Button("查看") { Task { await model.select(runID: run.runID) } }
                        .buttonStyle(.borderless)
                }
            }
            .frame(minHeight: 140)
        }
    }

    @ViewBuilder
    private var resultsSection: some View {
        if model.selectedRunID != nil {
            DisclosureGroup("任务 #\(model.selectedRunID ?? 0) 结果（\(model.results.count) 条）") {
                if model.results.isEmpty {
                    Text("尚未加载结果或任务无结果").foregroundStyle(.secondary).padding(.top, 6)
                } else {
                    Table(Array(model.results.prefix(150))) {
                        TableColumn("研究") { item in Text(item.studyType ?? "—") }
                        TableColumn("范围") { item in Text("\(item.scopeType ?? "—"):\(item.scopeKey ?? "—")") }
                        TableColumn("状态") { item in Text(item.state ?? "—") }
                        TableColumn("周期") { item in Text(item.horizon.map(String.init) ?? "—") }
                        TableColumn("样本数") { item in Text(item.sampleCount.map(String.init) ?? "数据不足") }
                        TableColumn("指标") { item in JSONEvidenceView(value: item.metrics) }
                    }
                    .frame(minHeight: 180)
                    if model.results.count > 150 {
                        Text("仅展示前 150 条（共 \(model.results.count) 条）").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .font(.headline)
        }
    }

    private var recoverySection: some View {
        VStack(alignment: .leading, spacing: 10) {
            M4SectionHeader("历史缺口恢复", subtitle: "为指定交易日重建缺失的 EOD 快照；需要填写恢复原因")
            HStack {
                TextField("交易日（YYYY-MM-DD）", text: $recoveryDate).textFieldStyle(.roundedBorder).frame(width: 170)
                TextField("范围（逗号分隔，如 market,sector）", text: $recoveryScopes).textFieldStyle(.roundedBorder).frame(width: 240)
                TextField("恢复原因（≥3 个字符）", text: $recoveryReason).textFieldStyle(.roundedBorder).frame(width: 220)
                Button("执行恢复") {
                    let scopes = recoveryScopes.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
                    Task {
                        await model.recover(tradingDate: recoveryDate, scopes: scopes, reason: recoveryReason)
                    }
                }
                .buttonStyle(.bordered)
                .disabled(recoveryDate.count != 10 || recoveryReason.count < 3)
            }
            if let gaps = model.gaps {
                DisclosureGroup("缺口详情（\(gaps.status ?? "—")）") {
                    JSONEvidenceView(value: gaps.gaps).padding(.top, 6)
                }
                .font(.headline)
            }
        }
        .padding(14)
        .background(.background.secondary, in: .rect(cornerRadius: 10))
    }
}
